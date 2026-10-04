"""Capture across LangGraph features: map-reduce, the functional API, caching, and more."""

import operator
from dataclasses import dataclass
from typing import Annotated, Any, Literal, TypedDict

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.cache.memory import InMemoryCache
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.errors import GraphRecursionError
from langgraph.func import entrypoint, task
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.runtime import Runtime
from langgraph.types import CachePolicy, Command, Send, interrupt

from langgraph_xai import ExecutionStatus, HumanInteractionType, XAIRuntime
from tests.helpers import State, linear_graph


class Fanout(TypedDict, total=False):
    items: list[int]
    results: Annotated[list[int], operator.add]


def nodes(run) -> list[tuple[str, str]]:
    return [(node.node_id, node.status.value) for node in run.execution.nodes]


async def test_send_fan_out_records_every_mapped_task() -> None:
    builder = StateGraph(Fanout)
    builder.add_node("square", lambda state: {"results": [state["item"] ** 2]})
    builder.add_conditional_edges(
        START, lambda state: [Send("square", {"item": item}) for item in state["items"]]
    )
    builder.add_edge("square", END)
    xai = XAIRuntime()

    with xai.collect_runs() as runs:
        output = await xai.instrument(builder.compile()).ainvoke({"items": [1, 2, 3]})
    (run,) = runs

    assert output["results"] == [1, 4, 9]
    assert nodes(run) == [("square", "completed")] * 3
    assert all(node.attempt == 1 for node in run.execution.nodes)
    assert sorted(
        str(change.after)
        for transition in run.execution.state_transitions
        for change in transition.changes
    ) == ["[1]", "[4]", "[9]"]


async def test_functional_api_tasks_and_entrypoints_are_recorded() -> None:
    @task
    def double(number: int) -> int:
        return number * 2

    @entrypoint(checkpointer=InMemorySaver())
    def workflow(numbers: list[int]) -> int:
        total = sum(future.result() for future in [double(number) for number in numbers])
        return total if interrupt({"total": total}) else 0

    xai = XAIRuntime()
    graph = xai.instrument(workflow)
    config = {"configurable": {"thread_id": "functional"}}

    with xai.collect_runs() as runs:
        await graph.ainvoke([1, 2, 3], config)
        result = await graph.ainvoke(Command(resume=True), config)
    paused, resumed = runs

    assert result == 12
    assert sorted(nodes(paused)) == [("double", "completed")] * 3 + [("workflow", "interrupted")]
    assert paused.execution.human_interactions[0].metadata == {"value": {"total": 12}}
    # On resume LangGraph reuses the finished tasks' results; only the entrypoint runs again.
    assert nodes(resumed) == [("workflow", "completed")]
    assert resumed.execution.continuation_of == paused.run_id
    assert [item.interaction_type for item in resumed.execution.human_interactions] == [
        HumanInteractionType.RESUME
    ]


async def test_node_cache_hits_are_not_recorded_as_executions() -> None:
    calls: list[int] = []

    def expensive(state: Fanout) -> Fanout:
        calls.append(1)
        return {"results": [len(calls)]}

    builder = StateGraph(Fanout)
    builder.add_node("expensive", expensive, cache_policy=CachePolicy())
    builder.add_edge(START, "expensive")
    builder.add_edge("expensive", END)
    xai = XAIRuntime()
    graph = xai.instrument(builder.compile(cache=InMemoryCache()))

    with xai.collect_runs() as runs:
        first = await graph.ainvoke({"items": [1]})
        cached = await graph.ainvoke({"items": [1]})
    computed, hit = runs

    assert first == cached == {"items": [1], "results": [1]}
    assert len(calls) == 1
    assert nodes(computed) == [("expensive", "completed")]
    assert hit.execution.nodes == hit.execution.state_transitions == []
    assert hit.execution.status is ExecutionStatus.COMPLETED


async def test_recursion_limit_errors_fail_the_run() -> None:
    builder = StateGraph(State)
    builder.add_node("loop", lambda state: {"count": state["count"] + 1})
    builder.add_edge(START, "loop")
    builder.add_edge("loop", "loop")
    xai = XAIRuntime()

    with xai.collect_runs() as runs, pytest.raises(GraphRecursionError):
        await xai.instrument(builder.compile()).ainvoke({"count": 0}, {"recursion_limit": 3})
    (run,) = runs

    assert run.execution.status is ExecutionStatus.FAILED
    assert run.execution.exceptions[0].exception_type == "GraphRecursionError"
    assert nodes(run) == [("loop", "completed")] * 3


@dataclass
class Caller:
    user: str


class Greeting(TypedDict, total=False):
    note: str


async def test_runtime_context_reaches_nodes_unchanged() -> None:
    def greet(state: Greeting, runtime: Runtime[Caller]) -> Greeting:
        return {"note": f"hello {runtime.context.user}"}

    builder = StateGraph(Greeting, context_schema=Caller)
    builder.add_node("greet", greet)
    builder.add_edge(START, "greet")
    builder.add_edge("greet", END)
    xai = XAIRuntime()

    with xai.collect_runs() as runs:
        output = await xai.instrument(builder.compile()).ainvoke({}, context=Caller(user="ana"))

    assert output == {"note": "hello ana"}
    assert nodes(runs[0]) == [("greet", "completed")]


async def test_conditional_edges_record_only_the_branch_taken() -> None:
    def route(state: State) -> Literal["high", "low"]:
        return "high" if state["count"] > 5 else "low"

    builder = StateGraph(State)
    builder.add_node("score", lambda state: {"count": state["count"] * 2})
    builder.add_node("high", lambda state: {"note": "high"})
    builder.add_node("low", lambda state: {"note": "low"})
    builder.add_edge(START, "score")
    builder.add_conditional_edges("score", route)
    builder.add_edge("high", END)
    builder.add_edge("low", END)
    xai = XAIRuntime()
    graph = xai.instrument(builder.compile())

    with xai.collect_runs() as runs:
        await graph.ainvoke({"count": 4})
        await graph.ainvoke({"count": 1})

    assert [nodes(run) for run in runs] == [
        [("score", "completed"), ("high", "completed")],
        [("score", "completed"), ("low", "completed")],
    ]


async def test_messages_state_records_the_messages_a_node_wrote() -> None:
    def respond(state: MessagesState) -> dict[str, Any]:
        return {"messages": [AIMessage("hi", id="ai-1")]}

    builder = StateGraph(MessagesState)
    builder.add_node("respond", respond)
    builder.add_edge(START, "respond")
    builder.add_edge("respond", END)
    xai = XAIRuntime()

    with xai.collect_runs() as runs:
        await xai.instrument(builder.compile()).ainvoke(
            {"messages": [HumanMessage("hello", id="h-1")]}
        )

    ((change,),) = [transition.changes for transition in runs[0].execution.state_transitions]
    assert change.path == "messages"
    assert isinstance(change.before, list)
    assert isinstance(change.after, list)
    assert [item["id"] for item in change.before if isinstance(item, dict)] == ["h-1"]
    assert [item["id"] for item in change.after if isinstance(item, dict)] == ["ai-1"]


@pytest.mark.parametrize("durability", ["exit", "async", "sync"])
async def test_every_durability_mode_records_the_final_checkpoint(durability: str) -> None:
    xai = XAIRuntime()
    graph = xai.instrument(
        linear_graph(
            ("a", lambda state: {"count": state["count"] + 1}),
            ("b", lambda state: {"count": state["count"] + 1}),
            checkpointer=InMemorySaver(),
        )
    )
    config = {"configurable": {"thread_id": durability}}

    with xai.collect_runs() as runs:
        await graph.ainvoke({"count": 1}, config, durability=durability)
    latest = await graph.aget_state(config)

    (checkpoint,) = runs[0].execution.checkpoints
    assert checkpoint.checkpoint_id == latest.config["configurable"]["checkpoint_id"]
    assert latest.values == {"count": 3}
