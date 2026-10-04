import asyncio
import contextlib
import dataclasses
from typing import Annotated, TypedDict

import pytest
from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langchain_core.documents import Document
from langchain_core.messages import AIMessage, AnyMessage
from langchain_core.retrievers import BaseRetriever
from langchain_core.runnables import RunnableLambda
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langgraph.types import Command, RetryPolicy, interrupt
from pydantic import BaseModel

from langgraph_xai import (
    ExecutionStatus,
    HumanInteractionType,
    ProvenanceStore,
    ToolStatus,
    XAIConfig,
    XAIInstrumentationError,
    XAIRuntime,
)
from langgraph_xai.core import StateTransitionEvent
from langgraph_xai.policy import REDACTED
from tests.helpers import FailingStore, State, linear_graph


async def run_once(graph, payload, config=None, xai: XAIRuntime | None = None):
    xai = xai or XAIRuntime()
    with xai.collect_runs() as runs:
        output = await xai.instrument(graph).ainvoke(payload, config)
    (run,) = runs
    return output, run.execution


def changes(execution) -> list[tuple[str, list[tuple[str, object, object]]]]:
    return [
        (item.node_id, [(c.path, c.before, c.after) for c in item.changes])
        for item in execution.state_transitions
    ]


def nodes(execution) -> list[tuple[str, str]]:
    return [(item.node_id, item.status.value) for item in execution.nodes]


async def test_partial_updates_record_only_what_the_node_changed() -> None:
    graph = linear_graph(("answer", lambda state: {"answer": "42"}))

    output, execution = await run_once(graph, {"question": "Why?", "count": 1})

    assert output == {"question": "Why?", "count": 1, "answer": "42"}
    assert changes(execution) == [("answer", [("answer", None, "42")])]
    assert nodes(execution) == [("answer", "completed")]
    (node,) = execution.nodes
    assert node.metadata["langgraph_step"] == 1
    assert node.parent_node_id is None
    assert node.ended_at is not None
    assert node.ended_at >= node.started_at


async def test_nodes_without_updates_record_no_transition() -> None:
    graph = linear_graph(("noop", lambda state: None), ("empty", lambda state: {}))

    _, execution = await run_once(graph, {"question": "q"})

    assert changes(execution) == []
    assert nodes(execution) == [("noop", "completed"), ("empty", "completed")]


async def test_command_updates_are_captured() -> None:
    builder = StateGraph(State)
    builder.add_node("route", lambda state: Command(update={"answer": "routed"}, goto="pairs"))
    builder.add_node("pairs", lambda state: Command(update=[("note", "from pairs")]))
    builder.add_edge(START, "route")
    builder.add_edge("pairs", END)

    _, execution = await run_once(builder.compile(), {"question": "q"})

    assert changes(execution) == [
        ("route", [("answer", None, "routed")]),
        ("pairs", [("note", None, "from pairs")]),
    ]


class Counter(BaseModel):
    value: int
    label: str = "start"


@dataclasses.dataclass
class Ticket:
    priority: int
    status: str = "open"


async def test_pydantic_and_dataclass_states_are_compared_field_by_field() -> None:
    pydantic_graph = linear_graph(("inc", lambda s: {"value": s.value + 1}), state=Counter)
    dataclass_graph = linear_graph(
        ("triage", lambda s: Ticket(priority=1, status="triaged")), state=Ticket
    )

    _, pydantic_execution = await run_once(pydantic_graph, {"value": 1})
    _, dataclass_execution = await run_once(dataclass_graph, {"priority": 3})

    assert changes(pydantic_execution) == [("inc", [("value", 1, 2)])]
    assert changes(dataclass_execution) == [
        ("triage", [("priority", 3, 1), ("status", "open", "triaged")])
    ]


async def test_runnables_nested_inside_a_node_are_not_mistaken_for_nodes() -> None:
    helper = RunnableLambda(lambda value: {"inner": 1}) | RunnableLambda(lambda value: value)

    def agent(state: State) -> State:
        helper.invoke({"question": state["question"]})
        return {"answer": "done"}

    _, execution = await run_once(linear_graph(("agent", agent)), {"question": "q"})

    assert changes(execution) == [("agent", [("answer", None, "done")])]
    assert nodes(execution) == [("agent", "completed")]


async def test_subgraph_nodes_record_their_parent_node() -> None:
    inner = linear_graph(("inner_node", lambda state: {"note": "inner"}))
    graph = linear_graph(("subgraph", inner))

    _, execution = await run_once(graph, {"question": "q"})

    by_name = {item.node_id: item for item in execution.nodes}
    assert by_name["inner_node"].parent_node_id == "subgraph"
    assert by_name["subgraph"].parent_node_id is None
    assert "|" in str(by_name["inner_node"].metadata["langgraph_checkpoint_ns"])


async def test_failed_nodes_and_retried_attempts_are_recorded() -> None:
    attempts = {"count": 0}

    def flaky(state: State) -> State:
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise ConnectionError("upstream reset")
        return {"answer": "recovered"}

    builder = StateGraph(State)
    builder.add_node("flaky", flaky, retry_policy=RetryPolicy(max_attempts=2, initial_interval=0))
    builder.add_edge(START, "flaky")
    builder.add_edge("flaky", END)

    _, execution = await run_once(builder.compile(), {"question": "q"})

    first, second = execution.nodes
    assert (first.status, first.attempt, first.metadata["error_type"]) == (
        ExecutionStatus.FAILED,
        1,
        "ConnectionError",
    )
    assert (second.status, second.attempt) == (ExecutionStatus.COMPLETED, 2)
    assert execution.status is ExecutionStatus.COMPLETED


async def test_a_failing_node_fails_the_run() -> None:
    def broken(state: State) -> State:
        raise ValueError("bad input")

    xai = XAIRuntime()
    with xai.collect_runs() as runs, pytest.raises(ValueError, match="bad input"):
        await xai.instrument(linear_graph(("broken", broken))).ainvoke({"question": "q"})

    execution = runs[0].execution
    assert nodes(execution) == [("broken", "failed")]
    assert execution.status is ExecutionStatus.FAILED
    assert execution.exceptions[0].exception_type == "ValueError"


class Approval(TypedDict, total=False):
    amount: float
    approved: bool


async def test_interrupt_and_resume_are_recorded_on_two_runs() -> None:
    def review(state: Approval) -> Approval:
        return {"approved": bool(interrupt({"question": "approve?", "amount": state["amount"]}))}

    graph = linear_graph(("review", review), state=Approval, checkpointer=InMemorySaver())
    xai = XAIRuntime()
    instrumented = xai.instrument(graph)
    thread = {"configurable": {"thread_id": "wire-1"}}

    with xai.collect_runs() as runs:
        paused = await instrumented.ainvoke({"amount": 9000.0}, thread)
        (pending,) = paused["__interrupt__"]
        answer = {"approved": True, "api_key": "reviewer-secret"}
        resumed = await instrumented.ainvoke(Command(resume={pending.id: answer}), thread)

    first, second = (run.execution for run in runs)
    assert resumed == {"amount": 9000.0, "approved": True}
    assert first.status is ExecutionStatus.INTERRUPTED
    assert nodes(first) == [("review", "interrupted")]
    (pause,) = first.human_interactions
    assert pause.interaction_type is HumanInteractionType.INTERRUPT
    assert pause.metadata["value"] == {"question": "approve?", "amount": 9000.0}
    assert pause.request_reference == pending.id
    assert second.status is ExecutionStatus.COMPLETED
    (resume,) = second.human_interactions
    assert resume.interaction_type is HumanInteractionType.RESUME
    assert resume.metadata == {"value": {pending.id: {"approved": True, "api_key": REDACTED}}}
    assert first.context.thread_id == second.context.thread_id == "wire-1"


async def test_parent_commands_complete_the_subgraph_node() -> None:
    inner_builder = StateGraph(State)
    inner_builder.add_node(
        "handoff", lambda state: Command(graph=Command.PARENT, goto="finish", update={"note": "up"})
    )
    inner_builder.add_edge(START, "handoff")
    outer = StateGraph(State)
    outer.add_node("delegate", inner_builder.compile())
    outer.add_node("finish", lambda state: {"answer": state["note"]})
    outer.add_edge(START, "delegate")
    outer.add_edge("finish", END)

    output, execution = await run_once(outer.compile(), {"question": "q"})

    assert output["answer"] == "up"
    assert dict(nodes(execution))["handoff"] == "completed"
    assert execution.status is ExecutionStatus.COMPLETED


async def test_cancelled_nodes_are_recorded_as_cancelled() -> None:
    started = asyncio.Event()

    async def slow(state: State) -> State:
        started.set()
        await asyncio.sleep(10)
        return {}

    xai = XAIRuntime()
    with xai.collect_runs() as runs:
        task = asyncio.ensure_future(xai.instrument(linear_graph(("slow", slow))).ainvoke({}))
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    execution = runs[0].execution
    assert execution.status is ExecutionStatus.CANCELLED
    assert nodes(execution) == [("slow", "cancelled")]


class Conversation(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]


@tool
def lookup(account: str) -> str:
    """Look up an account."""
    return f"{account}: ok"


@tool
def broken_lookup(account: str) -> str:
    """Always fails."""
    raise RuntimeError("service down")


@tool
def slow_lookup(account: str) -> str:
    """Always times out."""
    raise TimeoutError("deadline exceeded")


async def test_tool_calls_record_the_model_tool_call_id_and_outcome() -> None:
    graph = linear_graph(
        ("tools", ToolNode([lookup, broken_lookup, slow_lookup], handle_tool_errors=True)),
        state=Conversation,
    )
    request = AIMessage(
        content="",
        tool_calls=[
            {"name": "lookup", "args": {"account": "a-1"}, "id": "call_ok"},
            {"name": "broken_lookup", "args": {"account": "a-2"}, "id": "call_failed"},
            {"name": "slow_lookup", "args": {"account": "a-3"}, "id": "call_slow"},
        ],
    )

    output, execution = await run_once(graph, {"messages": [request]})

    tools = {item.tool_call_id: item for item in execution.tools}
    assert len(output["messages"]) == 4
    assert tools["call_ok"].status is ToolStatus.SUCCEEDED
    assert tools["call_ok"].tool_name == "lookup"
    assert tools["call_failed"].status is ToolStatus.FAILED
    assert tools["call_failed"].metadata["error_type"] == "RuntimeError"
    assert tools["call_slow"].status is ToolStatus.TIMED_OUT
    assert all(item.latency_ms is not None and item.latency_ms >= 0 for item in tools.values())
    assert all("langchain_run_id" in item.metadata for item in tools.values())


async def test_tools_paused_by_an_interrupt_are_recorded_as_cancelled() -> None:
    @tool
    def guarded_transfer(amount: int) -> str:
        """Transfer money after human approval."""
        return "sent" if interrupt({"amount": amount}) else "declined"

    graph = linear_graph(
        ("tools", ToolNode([guarded_transfer])), state=Conversation, checkpointer=InMemorySaver()
    )
    request = AIMessage(
        content="",
        tool_calls=[{"name": "guarded_transfer", "args": {"amount": 5}, "id": "call_transfer"}],
    )

    _, execution = await run_once(
        graph, {"messages": [request]}, {"configurable": {"thread_id": "t"}}
    )

    (paused,) = execution.tools
    assert paused.status is ToolStatus.CANCELLED
    assert paused.metadata["error_type"] == "GraphInterrupt"
    assert execution.status is ExecutionStatus.INTERRUPTED


class PolicyRetriever(BaseRetriever):
    fail: bool = False

    def _get_relevant_documents(
        self, query: str, *, run_manager: CallbackManagerForRetrieverRun
    ) -> list[Document]:
        if self.fail:
            raise LookupError("index offline")
        return [
            Document(
                page_content="secret text", id="doc-1", metadata={"source": "kb://1", "score": 0.9}
            ),
            Document(page_content="more", metadata={"source": "kb://2", "relevance_score": 0.4}),
            Document(page_content="anonymous", metadata={"score": float("nan")}),
        ]


async def test_retrievals_record_documents_by_reference() -> None:
    retriever = PolicyRetriever().with_config(run_name="policy-index")
    failing = PolicyRetriever(fail=True).with_config(run_name="offline-index")

    def search(state: State) -> State:
        retriever.invoke(state["question"])
        with contextlib.suppress(LookupError):
            failing.invoke(state["question"])
        return {"answer": "found"}

    _, execution = await run_once(linear_graph(("search", search)), {"question": "refunds?"})

    ok, failed = execution.retrievals
    assert ok.retriever_id == "policy-index"
    assert [
        (doc.document_id, doc.rank, doc.score, doc.content_reference) for doc in ok.documents
    ] == [("doc-1", 1, 0.9, "kb://1"), ("kb://2", 2, 0.4, "kb://2"), ("3", 3, None, None)]
    assert "secret text" not in ok.model_dump_json()
    assert failed.retriever_id == "offline-index"
    assert failed.documents == []
    assert failed.metadata["error_type"] == "LookupError"


@pytest.mark.parametrize("method", ["ainvoke", "invoke"])
async def test_fail_closed_errors_propagate_out_of_graph_callbacks(method: str) -> None:
    xai = XAIRuntime(config=XAIConfig(failure_mode="fail_closed"))
    xai.register(ProvenanceStore, FailingStore(only=(StateTransitionEvent,)))
    graph = xai.instrument(linear_graph(("answer", lambda state: {"answer": "x"})))
    call = (
        graph.ainvoke({"question": "q"})
        if method == "ainvoke"
        else asyncio.to_thread(graph.invoke, {"question": "q"})
    )

    with pytest.raises(XAIInstrumentationError, match="storage unavailable"):
        await call


async def test_fail_open_keeps_the_graph_running_when_capture_fails() -> None:
    xai = XAIRuntime()
    xai.register(ProvenanceStore, FailingStore(only=(StateTransitionEvent,)))

    output = await xai.instrument(linear_graph(("answer", lambda state: {"answer": "x"}))).ainvoke(
        {"question": "q"}
    )

    assert output["answer"] == "x"
    assert xai.errors
