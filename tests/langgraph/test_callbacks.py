from dataclasses import dataclass
from uuid import uuid4

import pytest
from hypothesis import given
from hypothesis import strategies as st
from langchain_core.documents import Document
from langgraph.errors import GraphInterrupt
from langgraph.types import Command, Interrupt
from pydantic import BaseModel

from langgraph_xai import XAIConfig, XAIRuntime
from langgraph_xai.instrumentation.callbacks import (
    _AsyncXAICallbackHandler,
    _parent_node,
    _serialized_name,
    _XAICallbackHandler,
    node_state,
    node_update,
    retrieved_document,
)


class Model(BaseModel):
    kept: int | None = None
    explicit_none: str | None = None
    unset_none: str | None = None


@dataclass
class Record:
    value: int | None
    other: int | None = None


def test_node_update_follows_langgraph_semantics() -> None:
    assert node_update({"a": 1}) == {"a": 1}
    assert node_update(None) == {}
    assert node_update("text") == {}
    assert node_update(Command(goto="next")) == {}
    assert node_update(Command(update={"a": 1})) == {"a": 1}
    assert node_update(Command(update=[("a", 1), ("b", 2)])) == {"a": 1, "b": 2}
    assert node_update([("a", 1), "not-a-pair"]) == {}
    assert node_update([]) == {}
    assert node_update(
        [Command(update={"messages": ["m1"], "x": 1}), {"messages": ["m2"], "x": 2}]
    ) == {"messages": ["m1", "m2"], "x": 2}
    assert node_update(Model(kept=1, explicit_none=None)) == {"kept": 1, "explicit_none": None}
    assert node_update(Record(value=1)) == {"value": 1}


def test_node_state_accepts_mappings_models_and_dataclasses() -> None:
    assert node_state({"a": 1}) == {"a": 1}
    assert node_state(Model(kept=2)) == {"kept": 2, "explicit_none": None, "unset_none": None}
    assert node_state(Record(value=3)) == {"value": 3, "other": None}
    assert node_state(Record) is None
    assert node_state("text") is None


def test_name_and_namespace_helpers() -> None:
    assert _serialized_name({"name": "search"}, "tool") == "search"
    assert _serialized_name({"id": ["langchain", "tools", "Search"]}, "tool") == "Search"
    assert _serialized_name({"id": []}, "tool") == "tool"
    assert _serialized_name(None, "tool") == "tool"
    assert _parent_node(None) is None
    assert _parent_node("node:1") is None
    assert _parent_node("outer:1|middle:2|inner:3") == "middle"


def test_retrieved_documents_are_described_by_reference() -> None:
    document = Document(page_content="private", metadata={"id": "meta-id", "score": True})

    described = retrieved_document(document, 4)

    assert described.document_id == "meta-id"
    assert described.rank == 4
    assert described.score is None
    assert retrieved_document(Document(page_content="x"), 1).document_id == "1"
    assert retrieved_document(Document(page_content="x", id="d9"), 2).document_id == "d9"
    sourced = retrieved_document(
        Document(page_content="x", metadata={"source": "kb://a", "relevance_score": 0.5}), 3
    )
    assert (sourced.document_id, sourced.score, sourced.content_reference) == (
        "kb://a",
        0.5,
        "kb://a",
    )


async def test_only_langgraph_node_runs_are_tracked() -> None:
    xai = XAIRuntime()
    run = await xai.start_run()
    handler = _AsyncXAICallbackHandler(xai, run)
    node_metadata = {"langgraph_node": "node", "langgraph_step": 1}
    hidden, unnamed, other, real = uuid4(), uuid4(), uuid4(), uuid4()

    await handler.on_chain_start(
        {}, {}, run_id=hidden, metadata=node_metadata, tags=["langsmith:hidden"], name="node"
    )
    await handler.on_chain_start({}, {}, run_id=unnamed, metadata=node_metadata)
    await handler.on_chain_start({}, {}, run_id=other, metadata=node_metadata, name="helper")
    await handler.on_chain_start({}, {}, run_id=real, metadata=None, name="node")
    for run_id in (hidden, unnamed, other, real, uuid4()):
        await handler.on_chain_end({"x": 1}, run_id=run_id)
        await handler.on_chain_error(ValueError("x"), run_id=run_id)
        await handler.on_tool_end("out", run_id=run_id)
        await handler.on_tool_error(ValueError("x"), run_id=run_id)
        await handler.on_retriever_end([], run_id=run_id)
        await handler.on_retriever_error(ValueError("x"), run_id=run_id)

    assert run.execution.nodes == []
    assert run.execution.tools == []
    assert run.execution.retrievals == []


def test_sync_handler_records_and_propagates_in_fail_closed_mode() -> None:
    open_runtime = XAIRuntime()
    run = open_runtime.run_sync(open_runtime.start_run())
    handler = _XAICallbackHandler(open_runtime, run)
    tool_run, retriever_run, node_run = uuid4(), uuid4(), uuid4()

    handler.on_tool_start({"name": "search"}, "q", run_id=tool_run, tool_call_id="call_1")
    handler.on_tool_end("result", run_id=tool_run)
    failed_tool = uuid4()
    handler.on_tool_start({"name": "search"}, "q", run_id=failed_tool)
    handler.on_tool_error(TimeoutError("slow"), run_id=failed_tool)
    found = uuid4()
    handler.on_retriever_start({}, "q", run_id=found, name="index")
    handler.on_retriever_end([Document(page_content="x", id="d1")], run_id=found)
    handler.on_retriever_start({}, "q", run_id=retriever_run, name="index")
    handler.on_retriever_error(LookupError("offline"), run_id=retriever_run)
    handler.on_chain_start(
        {}, {"a": 1}, run_id=node_run, metadata={"langgraph_node": "n"}, name="n"
    )
    handler.on_chain_error(ValueError("boom"), run_id=node_run)

    assert not handler.raise_error
    assert run.execution.tools[0].tool_call_id == "call_1"
    assert run.execution.tools[1].status.value == "timed_out"
    assert run.execution.retrievals[0].documents[0].document_id == "d1"
    assert run.execution.retrievals[1].metadata["error_type"] == "LookupError"
    assert run.execution.nodes[0].metadata["error_type"] == "ValueError"
    assert _XAICallbackHandler(XAIRuntime(config=XAIConfig(failure_mode="strict")), run).raise_error


async def test_async_handler_records_tools_without_a_call_id() -> None:
    xai = XAIRuntime()
    run = await xai.start_run()
    handler = _AsyncXAICallbackHandler(xai, run)
    tool_run = uuid4()

    await handler.on_tool_start({}, "q", run_id=tool_run)
    await handler.on_tool_end("result", run_id=tool_run)

    (tool,) = run.execution.tools
    assert tool.tool_name == "tool"
    assert tool.tool_call_id is None


@pytest.mark.parametrize("handler_type", [_XAICallbackHandler, _AsyncXAICallbackHandler])
def test_handlers_follow_the_runtime_failure_mode(handler_type) -> None:
    xai = XAIRuntime(config=XAIConfig(failure_mode="fail_closed"))
    run = xai.run_sync(xai.start_run())

    assert handler_type(xai, run).raise_error
    assert not handler_type(XAIRuntime(), run).raise_error


interrupt_batches = st.lists(st.lists(st.sampled_from("abcd"), max_size=3), max_size=6)


@given(batches=interrupt_batches)
def test_interrupts_are_collected_once_per_id_in_first_seen_order(
    batches: list[list[str]],
) -> None:
    xai = XAIRuntime()
    capture = _XAICallbackHandler(xai, xai.run_sync(xai.start_run())).capture

    for batch in batches:
        interrupts = [
            Interrupt(value=f"{name}-{index}", id=name) for index, name in enumerate(batch)
        ]
        capture.chain_error(uuid4(), GraphInterrupt(interrupts) if batch else GraphInterrupt())
        capture.chain_error(uuid4(), ValueError("not an interrupt"))

    expected: dict[str, str] = {}
    for batch in batches:
        for index, name in enumerate(batch):
            expected.setdefault(name, f"{name}-{index}")
    assert {name: item.value for name, item in capture.interrupts.items()} == expected
    assert list(capture.interrupts) == list(expected)
