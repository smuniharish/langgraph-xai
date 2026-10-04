"""The streaming-event, as-completed batch, and transform entry points, and unrecordable calls."""

import asyncio
from collections.abc import AsyncIterator, Callable, Iterable
from typing import Any

import pytest
from langgraph.stream.run_stream import AsyncGraphRunStream, GraphRunStream

from langgraph_xai import (
    ExecutionStatus,
    FailureMode,
    XAIConfig,
    XAIInstrumentationError,
    XAIRuntime,
)
from tests.helpers import State, executions, linear_graph


def increment(state: State) -> State:
    return {"count": state["count"] + 1}


def failing_on_one(state: State) -> State:
    if state["count"] == 1:
        raise ValueError("node failed")
    return increment(state)


def statuses(records) -> list[ExecutionStatus]:
    return sorted(item.status for item in records)


async def test_astream_events_records_the_run_and_yields_events_unchanged() -> None:
    compiled = linear_graph(("a", increment), ("b", increment))
    xai = XAIRuntime()

    with xai.collect_runs() as runs:
        events = [event async for event in xai.instrument(compiled).astream_events({"count": 1})]
    plain = [event async for event in compiled.astream_events({"count": 1})]

    (run,) = runs
    assert [(event["event"], event["name"]) for event in events] == [
        (event["event"], event["name"]) for event in plain
    ]
    assert events[-1]["data"]["output"] == {"count": 3}
    assert [node.node_id for node in run.execution.nodes] == ["a", "b"]
    assert run.execution.status is ExecutionStatus.COMPLETED


async def test_closing_astream_events_early_records_a_cancelled_run() -> None:
    xai = XAIRuntime()
    events = xai.instrument(linear_graph(("a", increment), ("b", increment))).astream_events(
        {"count": 1}
    )

    await anext(events)
    await events.aclose()

    assert statuses(await executions(xai)) == [ExecutionStatus.CANCELLED]


def test_batch_as_completed_records_one_run_per_input() -> None:
    xai = XAIRuntime()
    graph = xai.instrument(linear_graph(("inc", increment)))

    with xai.collect_runs() as runs:
        pairs = list(graph.batch_as_completed([{"count": 1}, {"count": 5}, {"count": 9}]))
        single = list(graph.batch_as_completed([{"count": 0}]))
        empty = list(graph.batch_as_completed([]))

    assert sorted(pairs, key=lambda pair: pair[0]) == [
        (0, {"count": 2}),
        (1, {"count": 6}),
        (2, {"count": 10}),
    ]
    assert single == [(0, {"count": 1})]
    assert empty == []
    assert len({run.run_id for run in runs}) == 4
    assert all(run.execution.status is ExecutionStatus.COMPLETED for run in runs)


def test_batch_as_completed_returns_or_raises_failures() -> None:
    xai = XAIRuntime()
    graph = xai.instrument(linear_graph(("boom", failing_on_one)))

    pairs = dict(graph.batch_as_completed([{"count": 1}, {"count": 2}], return_exceptions=True))
    with pytest.raises(ValueError, match="node failed"):
        list(graph.batch_as_completed([{"count": 1}, {"count": 2}], {"max_concurrency": 1}))

    assert isinstance(pairs[0], ValueError)
    assert pairs[1] == {"count": 3}
    assert xai.run_sync(executions(xai))[0].context.graph_id == "graph"


async def test_abatch_as_completed_records_one_run_per_input() -> None:
    xai = XAIRuntime()
    graph = xai.instrument(linear_graph(("inc", increment)))

    with xai.collect_runs() as runs:
        pairs = [
            pair
            async for pair in graph.abatch_as_completed(
                [{"count": 1}, {"count": 5}], {"max_concurrency": 1}
            )
        ]
        empty = [pair async for pair in graph.abatch_as_completed([])]

    assert sorted(pairs, key=lambda pair: pair[0]) == [(0, {"count": 2}), (1, {"count": 6})]
    assert empty == []
    assert len(runs) == 2
    assert all(run.execution.status is ExecutionStatus.COMPLETED for run in runs)


async def test_abatch_as_completed_returns_or_raises_failures() -> None:
    xai = XAIRuntime()
    graph = xai.instrument(linear_graph(("boom", failing_on_one)))

    pairs = dict(
        [
            pair
            async for pair in graph.abatch_as_completed(
                [{"count": 1}, {"count": 2}], return_exceptions=True
            )
        ]
    )
    with pytest.raises(ValueError, match="node failed"):
        [pair async for pair in graph.abatch_as_completed([{"count": 1}])]

    assert isinstance(pairs[0], ValueError)
    assert pairs[1] == {"count": 3}
    assert statuses(await executions(xai)) == [
        ExecutionStatus.COMPLETED,
        ExecutionStatus.FAILED,
        ExecutionStatus.FAILED,
    ]


async def test_closing_abatch_as_completed_early_cancels_the_remaining_runs() -> None:
    release = asyncio.Event()

    async def wait_for_release(state: State) -> State:
        if state["count"] > 1:
            await release.wait()
        return increment(state)

    xai = XAIRuntime()
    graph = xai.instrument(linear_graph(("wait", wait_for_release)))
    pairs = graph.abatch_as_completed([{"count": 1}, {"count": 2}, {"count": 3}])

    first = await anext(pairs)
    await pairs.aclose()

    assert first == (0, {"count": 2})
    assert statuses(await executions(xai)) == [
        ExecutionStatus.CANCELLED,
        ExecutionStatus.CANCELLED,
        ExecutionStatus.COMPLETED,
    ]


async def test_nested_calls_of_the_new_entry_points_pass_through() -> None:
    xai = XAIRuntime()
    inner = xai.instrument(linear_graph(("inc", increment)))
    seen: dict[str, Any] = {}

    async def outer_node(state: State) -> State:
        seen["events"] = [event async for event in inner.astream_events({"count": 1})]
        seen["async"] = [pair async for pair in inner.abatch_as_completed([{"count": 1}])]
        seen["sync"] = await asyncio.to_thread(
            lambda: list(inner.batch_as_completed([{"count": 1}]))
        )
        return state

    with xai.collect_runs() as runs:
        await xai.instrument(linear_graph(("outer", outer_node))).ainvoke({"count": 1})

    assert len(runs) == 1
    assert seen["events"][-1]["data"]["output"] == {"count": 2}
    assert seen["async"] == seen["sync"] == [(0, {"count": 2})]


async def chunks(items: Iterable[State]) -> AsyncIterator[State]:
    for item in items:
        yield item


def test_transform_records_one_run_for_the_combined_input() -> None:
    compiled = linear_graph(("a", increment), ("b", increment))
    xai = XAIRuntime()
    graph = xai.instrument(compiled)

    with xai.collect_runs() as runs:
        outputs = list(graph.transform(iter([{"count": 1}, {"count": 5}])))
        empty = list(graph.transform(iter([])))

    (run,) = runs
    assert outputs == list(compiled.transform(iter([{"count": 1}, {"count": 5}])))
    assert outputs[-1] == {"b": {"count": 7}}
    assert empty == []
    assert [node.node_id for node in run.execution.nodes] == ["a", "b"]
    assert run.execution.status is ExecutionStatus.COMPLETED


def test_closing_transform_early_records_a_cancelled_run() -> None:
    xai = XAIRuntime()
    outputs = xai.instrument(linear_graph(("a", increment), ("b", increment))).transform(
        iter([{"count": 1}])
    )

    assert next(outputs) == {"a": {"count": 2}}
    outputs.close()

    assert statuses(xai.run_sync(executions(xai))) == [ExecutionStatus.CANCELLED]


async def test_atransform_records_one_run_for_the_combined_input() -> None:
    compiled = linear_graph(("a", increment), ("b", increment))
    xai = XAIRuntime()
    graph = xai.instrument(compiled)

    with xai.collect_runs() as runs:
        outputs = [item async for item in graph.atransform(chunks([{"count": 1}, {"count": 5}]))]
        empty = [item async for item in graph.atransform(chunks([]))]

    (run,) = runs
    assert outputs == [item async for item in compiled.atransform(chunks([{"count": 5}]))]
    assert empty == []
    assert run.execution.status is ExecutionStatus.COMPLETED


async def test_closing_atransform_early_records_a_cancelled_run() -> None:
    xai = XAIRuntime()
    outputs = xai.instrument(linear_graph(("a", increment), ("b", increment))).atransform(
        chunks([{"count": 1}])
    )

    assert await anext(outputs) == {"a": {"count": 2}}
    await outputs.aclose()

    assert statuses(await executions(xai)) == [ExecutionStatus.CANCELLED]


@pytest.mark.filterwarnings("ignore:The v3 streaming protocol:DeprecationWarning")
async def test_v3_streaming_reaches_the_graph_unrecorded_under_fail_open() -> None:
    xai = XAIRuntime()
    graph = xai.instrument(linear_graph(("inc", increment)))

    with xai.collect_runs() as runs:
        sync_stream = graph.stream_events({"count": 1}, version="v3")
        async_stream = await graph.astream_events({"count": 1}, version="v3")
        sync_output = sync_stream.output
        async_output = await async_stream.output()

    assert isinstance(sync_stream, GraphRunStream)
    assert isinstance(async_stream, AsyncGraphRunStream)
    assert sync_output == async_output == {"count": 2}
    assert runs == []
    assert [str(error) for error in xai.errors] == [
        "stream_events is not recorded by langgraph-xai; use stream() or astream_events()",
        "astream_events(version='v3') is not recorded by langgraph-xai; use version='v2'",
    ]
    assert all(isinstance(error, NotImplementedError) for error in xai.errors)


@pytest.mark.filterwarnings("ignore:astream_log is deprecated:DeprecationWarning")
async def test_astream_log_reaches_the_graph_unrecorded_under_fail_open() -> None:
    xai = XAIRuntime()
    graph = xai.instrument(linear_graph(("inc", increment)))

    with xai.collect_runs() as runs:
        patches = [patch async for patch in graph.astream_log({"count": 1})]

    assert patches
    assert runs == []
    assert isinstance(xai.errors[0], NotImplementedError)


@pytest.mark.parametrize("mode", [FailureMode.FAIL_CLOSED, FailureMode.STRICT])
@pytest.mark.parametrize(
    "call",
    [
        lambda graph: graph.stream_events({"count": 1}, version="v3"),
        lambda graph: graph.astream_events({"count": 1}, version="v3"),
        lambda graph: graph.astream_log({"count": 1}),
    ],
    ids=["stream_events", "astream_events_v3", "astream_log"],
)
def test_unrecordable_calls_raise_without_running_the_graph(
    mode: FailureMode, call: Callable[[Any], object]
) -> None:
    ran: list[State] = []

    def record(state: State) -> State:
        ran.append(state)
        return state

    xai = XAIRuntime(XAIConfig(failure_mode=mode))

    with pytest.raises(XAIInstrumentationError, match="is not recorded by langgraph-xai"):
        call(xai.instrument(linear_graph(("record", record))))

    assert ran == []
    assert len(xai.errors) == 1


@pytest.mark.filterwarnings("ignore:The v3 streaming protocol:DeprecationWarning")
async def test_nested_unrecordable_and_transform_calls_pass_through() -> None:
    xai = XAIRuntime(XAIConfig(failure_mode=FailureMode.FAIL_CLOSED))
    inner = xai.instrument(linear_graph(("inc", increment)))
    seen: dict[str, Any] = {}

    async def outer_node(state: State) -> State:
        stream = await inner.astream_events({"count": 1}, version="v3")
        seen["v3"] = await stream.output()
        seen["atransform"] = [item async for item in inner.atransform(chunks([{"count": 1}]))]
        seen["transform"] = await asyncio.to_thread(
            lambda: list(inner.transform(iter([{"count": 1}])))
        )
        return state

    with xai.collect_runs() as runs:
        await xai.instrument(linear_graph(("outer", outer_node))).ainvoke({"count": 1})

    assert len(runs) == 1
    assert seen["v3"] == {"count": 2}
    assert seen["atransform"] == seen["transform"] == [{"inc": {"count": 2}}]
    assert xai.errors == ()
