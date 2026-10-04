"""Interrupts, checkpoints, and resume links for checkpointed LangGraph graphs."""

import asyncio
import operator
from typing import Annotated, Any, TypedDict

import pytest
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from langgraph_xai import (
    RUN_ID_METADATA_KEY,
    ExecutionStatus,
    HumanInteractionType,
    XAIConfig,
    XAIInstrumentationError,
    XAIRuntime,
)
from langgraph_xai.core import CheckpointEvent
from tests.helpers import State, executions, linear_graph, stored


class Review(TypedDict, total=False):
    amount: float
    approved: bool
    note: str


def increment(state: State) -> State:
    return {"count": state["count"] + 1}


def review_graph(checkpointer: Any = None, **compile_kwargs: Any):
    def prepare(state: Review) -> Review:
        return {"note": "prepared"}

    def review(state: Review) -> Review:
        return {"approved": bool(interrupt({"amount": state.get("amount")}))}

    return linear_graph(
        ("prepare", prepare),
        ("review", review),
        state=Review,
        checkpointer=checkpointer or InMemorySaver(),
        **compile_kwargs,
    )


def thread(name: str) -> RunnableConfig:
    return {"configurable": {"thread_id": name}}


def checkpoint_id(config: Any) -> str:
    return config["configurable"]["checkpoint_id"]


def kinds(run) -> list[HumanInteractionType]:
    return [item.interaction_type for item in run.execution.human_interactions]


async def test_a_checkpointed_run_records_the_last_checkpoint_it_wrote() -> None:
    xai = XAIRuntime()
    graph = xai.instrument(linear_graph(("inc", increment), checkpointer=InMemorySaver()))

    with xai.collect_runs() as runs:
        await graph.ainvoke({"count": 1}, thread("audit"))
    (run,) = runs
    snapshot = await graph.aget_state(thread("audit"))

    (checkpoint,) = run.execution.checkpoints
    assert checkpoint.checkpoint_id == checkpoint_id(snapshot.config)
    assert checkpoint.parent_checkpoint_id == checkpoint_id(snapshot.parent_config)
    assert not checkpoint.restored
    assert checkpoint.metadata == {
        "source": snapshot.metadata["source"],
        "step": snapshot.metadata["step"],
    }
    assert snapshot.metadata[RUN_ID_METADATA_KEY] == str(run.run_id)
    assert run.execution.status is ExecutionStatus.COMPLETED
    assert run.execution.continuation_of is None
    assert (await executions(xai))[0].checkpoints == [checkpoint]
    assert [event.checkpoint for event in await stored(xai, item_type=CheckpointEvent)] == [
        checkpoint
    ]


async def test_a_run_that_writes_no_checkpoint_records_only_where_it_resumed() -> None:
    xai = XAIRuntime()
    graph = xai.instrument(linear_graph(("inc", increment), checkpointer=InMemorySaver()))

    with xai.collect_runs() as runs:
        await graph.ainvoke({"count": 1}, thread("done"))
        await graph.ainvoke(None, thread("done"))
    first, again = runs
    (written,) = first.execution.checkpoints

    assert again.execution.continuation_of == first.run_id
    assert [(item.checkpoint_id, item.restored) for item in again.execution.checkpoints] == [
        (written.checkpoint_id, True)
    ]
    assert again.execution.human_interactions == []
    assert again.execution.status is ExecutionStatus.COMPLETED


async def test_interrupt_and_resume_are_linked_through_the_checkpoint() -> None:
    xai = XAIRuntime()
    graph = xai.instrument(review_graph())

    with xai.collect_runs() as runs:
        await graph.ainvoke({"amount": 9200.0}, thread("review"))
        paused_state = await graph.aget_state(thread("review"))
        await graph.ainvoke(Command(resume=True), thread("review"))
    paused, resumed = runs
    (pending,) = paused_state.interrupts

    (question,) = paused.execution.human_interactions
    assert paused.execution.status is ExecutionStatus.INTERRUPTED
    assert question.interaction_type is HumanInteractionType.INTERRUPT
    assert question.request_reference == pending.id
    assert question.metadata == {"value": {"amount": 9200.0}}
    (paused_checkpoint,) = paused.execution.checkpoints
    assert paused_checkpoint.checkpoint_id == checkpoint_id(paused_state.config)

    assert resumed.execution.continuation_of == paused.run_id
    restored, final = resumed.execution.checkpoints
    assert restored.restored
    assert restored.checkpoint_id == paused_checkpoint.checkpoint_id
    assert not final.restored
    (answer,) = resumed.execution.human_interactions
    assert answer.interaction_type is HumanInteractionType.RESUME
    assert answer.request_reference == pending.id
    assert answer.metadata == {"value": True}
    assert resumed.execution.status is ExecutionStatus.COMPLETED
    assert (await graph.aget_state(thread("review"))).values["approved"] is True


async def _drain(items) -> list[Any]:
    return [item async for item in items]


async def call(graph, method: str, payload: Any, config: RunnableConfig) -> Any:
    # Every way of running a graph, so each is checked against the same expectations.
    sync_calls = {
        "invoke": lambda: graph.invoke(payload, config),
        "invoke-v2": lambda: graph.invoke(payload, config, version="v2"),
        "stream": lambda: list(graph.stream(payload, config)),
        "stream-v2": lambda: list(graph.stream(payload, config, version="v2")),
        "stream-modes": lambda: list(
            graph.stream(payload, config, stream_mode=["updates", "values", "messages"])
        ),
        "stream-subgraphs": lambda: list(graph.stream(payload, config, subgraphs=True)),
        "batch": lambda: graph.batch([payload], config),
        "batch_as_completed": lambda: list(graph.batch_as_completed([payload], config)),
    }
    if method in sync_calls:
        return await asyncio.to_thread(sync_calls[method])
    async_calls = {
        "ainvoke": lambda: graph.ainvoke(payload, config),
        "ainvoke-v2": lambda: graph.ainvoke(payload, config, version="v2"),
        "astream": lambda: _drain(graph.astream(payload, config)),
        "astream-v2": lambda: _drain(graph.astream(payload, config, version="v2")),
        "astream-messages": lambda: _drain(graph.astream(payload, config, stream_mode="messages")),
        "astream-subgraphs": lambda: _drain(graph.astream(payload, config, subgraphs=True)),
        "astream_events": lambda: _drain(graph.astream_events(payload, config, version="v2")),
        "abatch": lambda: graph.abatch([payload], config),
        "abatch_as_completed": lambda: _drain(graph.abatch_as_completed([payload], config)),
    }
    return await async_calls[method]()


METHODS = [
    "invoke",
    "invoke-v2",
    "stream",
    "stream-v2",
    "stream-modes",
    "stream-subgraphs",
    "batch",
    "batch_as_completed",
    "ainvoke",
    "ainvoke-v2",
    "astream",
    "astream-v2",
    "astream-messages",
    "astream-subgraphs",
    "astream_events",
    "abatch",
    "abatch_as_completed",
]


@pytest.mark.parametrize("method", METHODS)
async def test_every_entry_point_records_interrupts_resumes_and_checkpoints(method: str) -> None:
    xai = XAIRuntime()
    graph = xai.instrument(review_graph())
    config = thread(method)

    with xai.collect_runs() as runs:
        await call(graph, method, {"amount": 50.0}, config)
        await call(graph, method, Command(resume=False), config)
    paused, resumed = runs

    assert [paused.execution.status, resumed.execution.status] == [
        ExecutionStatus.INTERRUPTED,
        ExecutionStatus.COMPLETED,
    ]
    assert kinds(paused) == [HumanInteractionType.INTERRUPT]
    assert kinds(resumed) == [HumanInteractionType.RESUME]
    assert resumed.execution.continuation_of == paused.run_id
    assert [item.restored for item in resumed.execution.checkpoints] == [True, False]
    assert (await graph.aget_state(config)).values["approved"] is False


async def test_static_breakpoints_pause_and_continue_runs() -> None:
    xai = XAIRuntime()
    graph = xai.instrument(
        linear_graph(
            ("a", increment), ("b", increment), checkpointer=InMemorySaver(), interrupt_before=["b"]
        )
    )

    with xai.collect_runs() as runs:
        await graph.ainvoke({"count": 1}, thread("breakpoint"))
        await graph.ainvoke(None, thread("breakpoint"))
        await asyncio.to_thread(
            lambda: list(graph.stream({"count": 1}, thread("after"), interrupt_after=["a"]))
        )
    paused, continued, paused_after = runs

    (pause,) = paused.execution.human_interactions
    assert paused.execution.status is ExecutionStatus.INTERRUPTED
    assert pause.interaction_type is HumanInteractionType.INTERRUPT
    assert pause.metadata == {"pending_nodes": ["b"]}
    (resume,) = continued.execution.human_interactions
    assert resume.interaction_type is HumanInteractionType.RESUME
    assert resume.metadata == {"pending_nodes": ["b"]}
    assert continued.execution.continuation_of == paused.run_id
    assert continued.execution.status is ExecutionStatus.COMPLETED
    assert (await graph.aget_state(thread("breakpoint"))).values == {"count": 3}
    assert paused_after.execution.status is ExecutionStatus.INTERRUPTED
    assert paused_after.execution.human_interactions[0].metadata == {"pending_nodes": ["b"]}


class Votes(TypedDict, total=False):
    votes: Annotated[list[str], operator.add]


def voting_graph():
    def voter(name: str):
        def node(state: Votes) -> Votes:
            return {"votes": [f"{name}:{interrupt(name)}"]}

        return node

    builder = StateGraph(Votes)
    for name in ("left", "right"):
        builder.add_node(name, voter(name))
        builder.add_edge(START, name)
        builder.add_edge(name, END)
    return builder.compile(checkpointer=InMemorySaver())


async def test_parallel_interrupts_are_recorded_and_answered_together() -> None:
    xai = XAIRuntime()
    graph = xai.instrument(voting_graph())

    with xai.collect_runs() as runs:
        await graph.ainvoke({"votes": []}, thread("votes"))
        pending = (await graph.aget_state(thread("votes"))).interrupts
        answers = {item.id: f"yes-{item.value}" for item in pending}
        await graph.ainvoke(Command(resume=answers), thread("votes"))
    paused, resumed = runs

    assert {item.request_reference for item in paused.execution.human_interactions} == {
        item.id for item in pending
    }
    assert {item.metadata["value"] for item in paused.execution.human_interactions} == {
        "left",
        "right",
    }
    (answer,) = resumed.execution.human_interactions
    assert answer.request_reference is None
    assert answer.metadata == {"value": answers}
    assert resumed.execution.status is ExecutionStatus.COMPLETED
    assert sorted((await graph.aget_state(thread("votes"))).values["votes"]) == [
        "left:yes-left",
        "right:yes-right",
    ]


async def test_an_interrupt_inside_a_subgraph_is_recorded_once() -> None:
    def ask(state: Review) -> Review:
        return {"approved": bool(interrupt("inner question"))}

    inner = linear_graph(("ask", ask), state=Review)
    xai = XAIRuntime()
    graph = xai.instrument(
        linear_graph(("inner", inner), state=Review, checkpointer=InMemorySaver())
    )

    with xai.collect_runs() as runs:
        await graph.ainvoke({"amount": 1.0}, thread("nested"))
    (run,) = runs
    (pending,) = (await graph.aget_state(thread("nested"))).interrupts

    (question,) = run.execution.human_interactions
    assert question.request_reference == pending.id
    assert question.metadata == {"value": "inner question"}
    assert run.execution.status is ExecutionStatus.INTERRUPTED


async def test_state_edits_between_pause_and_resume_keep_the_link() -> None:
    xai = XAIRuntime()
    graph = xai.instrument(review_graph())

    with xai.collect_runs() as runs:
        await graph.ainvoke({"amount": 9200.0}, thread("edited"))
        await graph.aupdate_state(thread("edited"), {"amount": 10.0})
        await graph.aupdate_state(thread("edited"), {"note": "reviewed"})
        edited = await graph.aget_state(thread("edited"))
        await graph.ainvoke(Command(resume=True), thread("edited"))
    paused, resumed = runs

    assert edited.metadata["source"] == "update"
    assert resumed.execution.continuation_of == paused.run_id
    assert resumed.execution.checkpoints[0].checkpoint_id == checkpoint_id(edited.config)
    assert resumed.execution.checkpoints[0].metadata["source"] == "update"


async def test_an_unreadable_edit_chain_leaves_the_run_unlinked(monkeypatch) -> None:
    compiled = review_graph()
    xai = XAIRuntime()
    graph = xai.instrument(compiled)
    await graph.ainvoke({"amount": 1.0}, thread("chain"))
    await graph.aupdate_state(thread("chain"), {"amount": 2.0})
    read_state = compiled.aget_state

    async def latest_only(config: Any, **kwargs: Any) -> Any:
        # Reading the edit's parent names a checkpoint; that history is unavailable.
        if config["configurable"].get("checkpoint_id"):
            raise OSError("history unavailable")
        return await read_state(config, **kwargs)

    monkeypatch.setattr(compiled, "aget_state", latest_only)
    with xai.collect_runs() as runs:
        await graph.ainvoke(Command(resume=True), thread("chain"))

    assert runs[0].execution.continuation_of is None
    assert runs[0].execution.status is ExecutionStatus.COMPLETED
    assert [type(error) for error in xai.errors] == [OSError]


async def test_a_cyclic_edit_chain_ends_the_search_for_the_writer(monkeypatch) -> None:
    compiled = review_graph()
    xai = XAIRuntime()
    graph = xai.instrument(compiled)
    await graph.ainvoke({"amount": 1.0}, thread("cycle"))
    await graph.aupdate_state(thread("cycle"), {"amount": 2.0})
    edited = await compiled.aget_state(thread("cycle"))
    reads: list[RunnableConfig] = []

    async def corrupt(config: RunnableConfig, **kwargs: Any) -> Any:
        # A corrupt store whose update checkpoint names itself as its parent.
        reads.append(config)
        return edited._replace(parent_config=edited.config)

    monkeypatch.setattr(compiled, "aget_state", corrupt)
    with xai.collect_runs() as runs:
        await graph.ainvoke(Command(resume=True), thread("cycle"))

    assert runs[0].execution.continuation_of is None
    assert len(reads) == 3


async def test_runtimes_sharing_a_checkpointer_link_runs_across_processes() -> None:
    compiled = review_graph()
    first, second = XAIRuntime(), XAIRuntime()

    with first.collect_runs() as paused:
        await first.instrument(compiled).ainvoke({"amount": 1.0}, thread("shared"))
    with second.collect_runs() as resumed:
        await second.instrument(compiled).ainvoke(Command(resume=True), thread("shared"))

    assert resumed[0].execution.continuation_of == paused[0].run_id
    assert (await executions(second))[0].continuation_of == paused[0].run_id


async def test_a_failed_run_can_be_retried_from_its_checkpoint() -> None:
    attempts: list[int] = []

    def flaky(state: State) -> State:
        attempts.append(state["count"])
        if len(attempts) == 1:
            raise ConnectionError("upstream unavailable")
        return increment(state)

    xai = XAIRuntime()
    graph = xai.instrument(
        linear_graph(("a", increment), ("flaky", flaky), checkpointer=InMemorySaver())
    )

    with xai.collect_runs() as runs:
        with pytest.raises(ConnectionError):
            await graph.ainvoke({"count": 1}, thread("retry"))
        await graph.ainvoke(None, thread("retry"))
    failed, retried = runs

    assert failed.execution.status is ExecutionStatus.FAILED
    (failed_checkpoint,) = failed.execution.checkpoints
    assert retried.execution.continuation_of == failed.run_id
    assert retried.execution.checkpoints[0].restored
    assert retried.execution.checkpoints[0].checkpoint_id == failed_checkpoint.checkpoint_id
    assert retried.execution.human_interactions == []
    assert retried.execution.status is ExecutionStatus.COMPLETED
    assert (await graph.aget_state(thread("retry"))).values == {"count": 3}


async def test_time_travel_restores_the_named_checkpoint() -> None:
    xai = XAIRuntime()
    graph = xai.instrument(
        linear_graph(("a", increment), ("b", increment), checkpointer=InMemorySaver())
    )

    with xai.collect_runs() as runs:
        await graph.ainvoke({"count": 1}, thread("travel"))
        history = [item async for item in graph.aget_state_history(thread("travel"))]
        before_b = next(item for item in history if item.next == ("b",))
        await graph.ainvoke(None, before_b.config)
    original, replay = runs

    assert replay.execution.continuation_of == original.run_id
    assert replay.execution.checkpoints[0].restored
    assert replay.execution.checkpoints[0].checkpoint_id == checkpoint_id(before_b.config)
    assert replay.execution.human_interactions == []
    assert replay.execution.context.checkpoint_id == checkpoint_id(before_b.config)


async def test_checkpoints_without_a_valid_run_id_are_not_linked() -> None:
    compiled = linear_graph(
        ("a", increment), ("b", increment), checkpointer=InMemorySaver(), interrupt_before=["b"]
    )
    await compiled.ainvoke({"count": 1}, thread("plain"))
    tampered: RunnableConfig = {
        "configurable": {"thread_id": "tampered"},
        "metadata": {RUN_ID_METADATA_KEY: "not-a-uuid"},
    }
    await compiled.ainvoke({"count": 1}, tampered)
    xai = XAIRuntime()
    graph = xai.instrument(compiled)

    with xai.collect_runs() as runs:
        await graph.ainvoke(None, thread("plain"))
        await graph.ainvoke(None, thread("tampered"))

    assert [run.execution.continuation_of for run in runs] == [None, None]
    assert all(run.execution.checkpoints[0].restored for run in runs)


async def test_a_resume_on_a_thread_without_checkpoints_is_not_an_answer() -> None:
    xai = XAIRuntime()
    graph = xai.instrument(review_graph())

    with xai.collect_runs() as runs:
        await graph.ainvoke(Command(resume=True), thread("empty"))
    (run,) = runs

    # LangGraph starts a fresh run and ignores the resume value, so the node asks again.
    assert run.execution.continuation_of is None
    assert kinds(run) == [HumanInteractionType.INTERRUPT]
    assert [item.restored for item in run.execution.checkpoints] == [False]


class StateReads:
    """Counts the state reads made on a compiled graph."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, graph: Any, error: Exception | None = None):
        self.calls = 0
        self.error = error
        for name in ("get_state", "aget_state"):
            original = getattr(graph, name)
            monkeypatch.setattr(graph, name, self._spy(original, is_async=name == "aget_state"))

    def _spy(self, original, *, is_async: bool):
        def read(*args: Any, **kwargs: Any) -> Any:
            self.calls += 1
            if self.error is not None:
                raise self.error
            return original(*args, **kwargs)

        async def aread(*args: Any, **kwargs: Any) -> Any:
            self.calls += 1
            if self.error is not None:
                raise self.error
            return await original(*args, **kwargs)

        return aread if is_async else read


@pytest.mark.parametrize(
    ("compile_kwargs", "runtime_config"),
    [
        ({}, XAIConfig()),
        ({"checkpointer": InMemorySaver()}, XAIConfig(capture_checkpoints=False)),
    ],
    ids=["no-checkpointer", "opted-out"],
)
async def test_state_is_read_only_for_checkpointed_threads(
    monkeypatch, compile_kwargs, runtime_config
) -> None:
    compiled = linear_graph(("inc", increment), **compile_kwargs)
    reads = StateReads(monkeypatch, compiled)
    xai = XAIRuntime(config=runtime_config)

    with xai.collect_runs() as runs:
        await xai.instrument(compiled).ainvoke({"count": 1}, thread("t"))
        await asyncio.to_thread(xai.instrument(compiled).invoke, {"count": 1}, thread("t"))

    assert reads.calls == 0
    assert [run.execution.status for run in runs] == [ExecutionStatus.COMPLETED] * 2
    assert all(run.execution.checkpoints == [] for run in runs)


async def test_a_checkpointed_graph_without_a_thread_is_not_read(monkeypatch) -> None:
    compiled = linear_graph(("inc", increment), checkpointer=InMemorySaver())
    reads = StateReads(monkeypatch, compiled)
    xai = XAIRuntime()

    with pytest.raises(ValueError, match="thread_id"):
        await xai.instrument(compiled).ainvoke({"count": 1})

    assert reads.calls == 0
    assert [item.status for item in await executions(xai)] == [ExecutionStatus.FAILED]


async def test_interrupts_are_recorded_without_checkpoint_capture(monkeypatch) -> None:
    compiled = review_graph()
    reads = StateReads(monkeypatch, compiled)
    xai = XAIRuntime(config=XAIConfig(capture_checkpoints=False))
    graph = xai.instrument(compiled)

    with xai.collect_runs() as runs:
        await graph.ainvoke({"amount": 1.0}, thread("opt-out"))
        await graph.ainvoke(Command(resume=True), thread("opt-out"))
    paused, resumed = runs

    assert reads.calls == 0
    assert kinds(paused) == [HumanInteractionType.INTERRUPT]
    assert kinds(resumed) == [HumanInteractionType.RESUME]
    assert resumed.execution.continuation_of is None
    assert paused.execution.checkpoints == resumed.execution.checkpoints == []


async def test_a_cancelled_stream_does_not_read_state(monkeypatch) -> None:
    compiled = linear_graph(("a", increment), ("b", increment), checkpointer=InMemorySaver())
    reads = StateReads(monkeypatch, compiled)
    xai = XAIRuntime()
    stream = xai.instrument(compiled).astream({"count": 1}, thread("cancel"))

    await anext(stream)
    await stream.aclose()

    assert reads.calls == 0
    assert [item.status for item in await executions(xai)] == [ExecutionStatus.CANCELLED]


async def test_failed_state_reads_are_recorded_in_fail_open_mode(monkeypatch) -> None:
    compiled = review_graph()
    reads = StateReads(monkeypatch, compiled, error=OSError("checkpointer down"))
    xai = XAIRuntime()
    graph = xai.instrument(compiled)

    with xai.collect_runs() as runs:
        await graph.ainvoke({"amount": 1.0}, thread("down"))
        await asyncio.to_thread(graph.invoke, Command(resume=True), thread("down"))
    paused, resumed = runs

    assert reads.calls == 3
    assert [type(error) for error in xai.errors] == [OSError] * 3
    assert paused.execution.status is ExecutionStatus.INTERRUPTED
    assert resumed.execution.status is ExecutionStatus.COMPLETED
    assert resumed.execution.continuation_of is None
    assert paused.execution.checkpoints == resumed.execution.checkpoints == []


async def test_failed_state_reads_raise_after_the_run_is_recorded_in_fail_closed_mode(
    monkeypatch,
) -> None:
    compiled = linear_graph(("inc", increment), checkpointer=InMemorySaver())
    xai = XAIRuntime(config=XAIConfig(failure_mode="fail_closed"))
    graph = xai.instrument(compiled)
    StateReads(monkeypatch, compiled, error=OSError("checkpointer down"))

    with pytest.raises(XAIInstrumentationError, match="checkpointer down"):
        await graph.ainvoke({"count": 1}, thread("closed"))
    with pytest.raises(XAIInstrumentationError, match="checkpointer down"):
        await graph.ainvoke(None, thread("closed"))

    (recorded,) = await executions(xai)
    assert recorded.status is ExecutionStatus.COMPLETED


async def test_nodes_see_the_run_id_but_the_context_does_not_keep_it() -> None:
    seen: list[str] = []

    def node(state: State, config: RunnableConfig) -> State:
        seen.append(config["metadata"][RUN_ID_METADATA_KEY])
        return increment(state)

    xai = XAIRuntime()
    with xai.collect_runs() as runs:
        await xai.instrument(linear_graph(("node", node))).ainvoke(
            {"count": 1}, {"metadata": {"team": "risk"}}
        )
    (run,) = runs

    assert seen == [str(run.run_id)]
    assert run.execution.context.metadata == {"team": "risk"}


async def test_checkpoints_can_still_be_linked_manually() -> None:
    xai = XAIRuntime()
    graph = xai.instrument(linear_graph(("inc", increment), checkpointer=InMemorySaver()))

    with xai.collect_runs() as runs:
        await graph.ainvoke({"count": 1}, thread("manual"))
    (run,) = runs
    snapshot = await graph.aget_state(thread("manual"))
    manual = await xai.record_checkpoint(
        checkpoint_id(snapshot.config),
        parent_checkpoint_id=checkpoint_id(snapshot.parent_config),
        metadata={"reason": "audit"},
        run=run,
    )

    assert run.execution.checkpoints[-1] == manual
    assert (await executions(xai))[0].checkpoints[-1] == manual
    replay = {"configurable": {"thread_id": "manual", "checkpoint_id": manual.checkpoint_id}}
    assert (await graph.aget_state(replay)).values == {"count": 2}
