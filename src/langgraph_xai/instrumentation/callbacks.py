"""LangChain callback handlers that capture LangGraph execution through public callbacks."""

from __future__ import annotations

import asyncio
import dataclasses
import math
import threading
from collections.abc import Mapping, Sequence
from time import monotonic
from typing import TYPE_CHECKING, Any

from langchain_core.callbacks import AsyncCallbackHandler, BaseCallbackHandler
from langgraph.constants import TAG_HIDDEN
from langgraph.errors import GraphBubbleUp, GraphInterrupt
from langgraph.types import Command
from pydantic import BaseModel

from langgraph_xai.core.models import (
    ExecutionStatus,
    FailureMode,
    RetrievedDocument,
    ToolStatus,
    utc_now,
)

if TYPE_CHECKING:
    from collections.abc import Coroutine
    from datetime import datetime
    from uuid import UUID

    from langchain_core.documents import Document
    from langgraph.types import Interrupt

    from langgraph_xai.runtime.runtime import Run, XAIRuntime

type _Recording = Coroutine[Any, Any, None] | None


def _serialized_name(serialized: Mapping[str, Any] | None, fallback: str) -> str:
    if serialized:
        value = serialized.get("name") or serialized.get("id")
        if isinstance(value, list):
            value = value[-1] if value else None
        if value:
            return str(value)
    return fallback


def _fields(value: Any) -> dict[str, Any] | None:
    if isinstance(value, BaseModel):
        return dict(value)
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {field.name: getattr(value, field.name) for field in dataclasses.fields(value)}
    return None


def node_state(value: Any) -> Mapping[str, Any] | None:
    """Return a node's input state as a mapping (dict, Pydantic, or dataclass state)."""
    if isinstance(value, Mapping):
        return value
    return _fields(value)


def node_update(output: Any) -> Mapping[str, Any]:
    """Return the state update a node returned, following LangGraph's update semantics.

    Handles mappings, ``Command(update=...)`` (mapping or ``(key, value)`` pairs),
    sequences of commands or mappings (as returned by ``create_agent`` nodes, merged
    in order, with list values concatenated), and Pydantic or dataclass state
    objects (only fields that were set or are not ``None``). ``None`` and any other
    output mean "no update".
    """
    if (
        isinstance(output, list | tuple)
        and output
        and all(isinstance(item, Command | Mapping) for item in output)
    ):
        merged: dict[str, Any] = {}
        for item in output:
            for key, value in node_update(item).items():
                previous = merged.get(key)
                merged[key] = (
                    [*previous, *value]
                    if isinstance(previous, list) and isinstance(value, list)
                    else value
                )
        return merged
    if isinstance(output, Command):
        output = output.update
    if isinstance(output, Mapping):
        return output
    if isinstance(output, BaseModel):
        return {
            name: value
            for name, value in output
            if value is not None or name in output.model_fields_set
        }
    fields = _fields(output)
    if fields is not None:
        return {name: value for name, value in fields.items() if value is not None}
    if (
        isinstance(output, Sequence)
        and not isinstance(output, str | bytes)
        and all(
            isinstance(item, tuple) and len(item) == 2 and isinstance(item[0], str)
            for item in output
        )
    ):
        return dict(output)
    return {}


def _parent_node(namespace: str | None) -> str | None:
    # A checkpoint namespace is "parent:<task id>|child:<task id>|...".
    if not namespace or "|" not in namespace:
        return None
    return namespace.split("|")[-2].split(":", 1)[0]


def _document_score(metadata: Mapping[str, Any]) -> float | None:
    for key in ("relevance_score", "score"):
        value = metadata.get(key)
        if isinstance(value, int | float) and not isinstance(value, bool):
            score = float(value)
            if math.isfinite(score):
                return score
    return None


def retrieved_document(document: Document, rank: int) -> RetrievedDocument:
    """Describe a LangChain ``Document`` by reference: ID, rank, score, and source.

    The document ID is the first of ``document.id``, ``metadata["id"]``,
    ``metadata["source"]``, and the rank that is set. The score is a finite
    ``metadata["relevance_score"]`` or ``metadata["score"]``. Content is never read.
    """
    metadata = document.metadata
    source = metadata.get("source")
    identifier = document.id or metadata.get("id") or source or rank
    return RetrievedDocument(
        document_id=str(identifier),
        rank=rank,
        score=_document_score(metadata),
        content_reference=None if source is None else str(source),
    )


@dataclasses.dataclass(slots=True)
class _NodeStart:
    name: str
    before: Mapping[str, Any]
    started_at: datetime
    attempt: int
    parent: str | None
    metadata: dict[str, Any]


@dataclasses.dataclass(slots=True)
class _CallStart:
    name: str
    started: float
    tool_call_id: str | None = None


class _Capture:
    """Turn LangChain callbacks for one run into runtime recordings.

    Start callbacks are recorded synchronously; end/error callbacks return the
    coroutine that records the outcome, or ``None`` when nothing is recorded.
    Interrupts raised anywhere in the run are collected in ``interrupts``, keyed
    by ``Interrupt.id``.
    """

    def __init__(self, runtime: XAIRuntime, run: Run) -> None:
        self.runtime = runtime
        self.run = run
        self.interrupts: dict[str, Interrupt] = {}
        self._nodes: dict[UUID, _NodeStart] = {}
        self._tools: dict[UUID, _CallStart] = {}
        self._retrievers: dict[UUID, _CallStart] = {}
        self._attempts: dict[str, int] = {}
        self._lock = threading.Lock()

    def chain_start(
        self,
        run_id: UUID,
        inputs: Any,
        tags: Sequence[str] | None,
        metadata: Mapping[str, Any] | None,
        name: str | None,
    ) -> None:
        # The rule LangGraph itself uses to recognize a node's own run.
        if (
            not metadata
            or name is None
            or name != metadata.get("langgraph_node")
            or TAG_HIDDEN in (tags or ())
        ):
            return
        namespace = metadata.get("langgraph_checkpoint_ns")
        node_metadata = {
            key: metadata[key]
            for key in ("langgraph_step", "langgraph_checkpoint_ns")
            if metadata.get(key) is not None
        }
        with self._lock:
            attempt_key = str(namespace or run_id)
            attempt = self._attempts.get(attempt_key, 0) + 1
            self._attempts[attempt_key] = attempt
            self._nodes[run_id] = _NodeStart(
                name=name,
                before=node_state(inputs) or {},
                started_at=utc_now(),
                attempt=attempt,
                parent=_parent_node(namespace),
                metadata=node_metadata,
            )

    def chain_end(self, run_id: UUID, outputs: Any) -> _Recording:
        start = self._pop(self._nodes, run_id)
        return None if start is None else self._node_completed(start, outputs)

    def chain_error(self, run_id: UUID, error: BaseException) -> _Recording:
        if isinstance(error, GraphInterrupt):
            # args[0] holds the interrupts; a subgraph re-raises its node's interrupts.
            with self._lock:
                for interrupt in error.args[0] if error.args else ():
                    self.interrupts.setdefault(interrupt.id, interrupt)
        start = self._pop(self._nodes, run_id)
        if start is None:
            return None
        if isinstance(error, GraphInterrupt):
            return self._node_finished(start, ExecutionStatus.INTERRUPTED)
        if isinstance(error, GraphBubbleUp):
            # e.g. ParentCommand: the node completed by handing control to its parent graph.
            return self._node_finished(start, ExecutionStatus.COMPLETED)
        if isinstance(error, asyncio.CancelledError):
            return self._node_finished(start, ExecutionStatus.CANCELLED)
        return self._node_finished(
            start, ExecutionStatus.FAILED, {"error_type": type(error).__name__}
        )

    def tool_start(
        self, run_id: UUID, serialized: Mapping[str, Any] | None, kwargs: Mapping[str, Any]
    ) -> None:
        tool_call_id = kwargs.get("tool_call_id")
        start = _CallStart(
            name=kwargs.get("name") or _serialized_name(serialized, "tool"),
            started=monotonic(),
            tool_call_id=None if tool_call_id is None else str(tool_call_id),
        )
        with self._lock:
            self._tools[run_id] = start

    def tool_end(self, run_id: UUID) -> _Recording:
        start = self._pop(self._tools, run_id)
        return None if start is None else self._tool(run_id, start, ToolStatus.SUCCEEDED)

    def tool_error(self, run_id: UUID, error: BaseException) -> _Recording:
        start = self._pop(self._tools, run_id)
        if start is None:
            return None
        if isinstance(error, TimeoutError):
            status = ToolStatus.TIMED_OUT
        elif isinstance(error, asyncio.CancelledError | GraphBubbleUp):
            status = ToolStatus.CANCELLED
        else:
            status = ToolStatus.FAILED
        return self._tool(run_id, start, status, type(error).__name__)

    def retriever_start(
        self, run_id: UUID, serialized: Mapping[str, Any] | None, kwargs: Mapping[str, Any]
    ) -> None:
        start = _CallStart(
            name=kwargs.get("name") or _serialized_name(serialized, "retriever"),
            started=monotonic(),
        )
        with self._lock:
            self._retrievers[run_id] = start

    def retriever_end(self, run_id: UUID, documents: Sequence[Document]) -> _Recording:
        start = self._pop(self._retrievers, run_id)
        return None if start is None else self._retrieval(run_id, start, documents)

    def retriever_error(self, run_id: UUID, error: BaseException) -> _Recording:
        start = self._pop(self._retrievers, run_id)
        return (
            None
            if start is None
            else self._retrieval(run_id, start, (), {"error_type": type(error).__name__})
        )

    def _pop[Start](self, starts: dict[UUID, Start], run_id: UUID) -> Start | None:
        with self._lock:
            return starts.pop(run_id, None)

    async def _node_completed(self, start: _NodeStart, outputs: Any) -> None:
        await self.runtime.record_state_delta(
            start.name,
            start.before,
            {**start.before, **node_update(outputs)},
            metadata=start.metadata,
            run=self.run,
        )
        await self._node_finished(start, ExecutionStatus.COMPLETED)

    async def _node_finished(
        self,
        start: _NodeStart,
        status: ExecutionStatus,
        extra: Mapping[str, Any] | None = None,
    ) -> None:
        await self.runtime.record_node(
            start.name,
            status=status,
            started_at=start.started_at,
            attempt=start.attempt,
            parent_node_id=start.parent,
            metadata={**start.metadata, **(extra or {})},
            run=self.run,
        )

    async def _tool(
        self,
        run_id: UUID,
        start: _CallStart,
        status: ToolStatus,
        error_type: str | None = None,
    ) -> None:
        metadata = {"langchain_run_id": str(run_id)}
        if error_type is not None:
            metadata["error_type"] = error_type
        await self.runtime.record_tool(
            start.name,
            status=status,
            tool_call_id=start.tool_call_id,
            latency_ms=(monotonic() - start.started) * 1000,
            metadata=metadata,
            run=self.run,
        )

    async def _retrieval(
        self,
        run_id: UUID,
        start: _CallStart,
        documents: Sequence[Document],
        extra: Mapping[str, Any] | None = None,
    ) -> None:
        await self.runtime.record_retrieval(
            start.name,
            documents=[
                retrieved_document(document, rank)
                for rank, document in enumerate(documents, start=1)
            ],
            metadata={
                "langchain_run_id": str(run_id),
                "latency_ms": (monotonic() - start.started) * 1000,
                **(extra or {}),
            },
            run=self.run,
        )


class _XAICallbackHandler(BaseCallbackHandler):
    """Synchronous handler attached by ``invoke`` and ``stream``.

    Failures propagate to the graph call (``raise_error``) unless the runtime's
    failure mode is ``FAIL_OPEN``.
    """

    def __init__(self, runtime: XAIRuntime, run: Run) -> None:
        self.capture = _Capture(runtime, run)
        self.raise_error = runtime.config.failure_mode is not FailureMode.FAIL_OPEN

    def _record(self, recording: _Recording) -> None:
        if recording is not None:
            self.capture.runtime.run_sync(recording)

    def on_chain_start(
        self,
        serialized: dict[str, Any],
        inputs: dict[str, Any],
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        self.capture.chain_start(run_id, inputs, tags, metadata, kwargs.get("name"))

    def on_chain_end(
        self,
        outputs: dict[str, Any],
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        self._record(self.capture.chain_end(run_id, outputs))

    def on_chain_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        self._record(self.capture.chain_error(run_id, error))

    def on_tool_start(
        self,
        serialized: dict[str, Any],
        input_str: str,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        self.capture.tool_start(run_id, serialized, kwargs)

    def on_tool_end(
        self,
        output: Any,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        self._record(self.capture.tool_end(run_id))

    def on_tool_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        self._record(self.capture.tool_error(run_id, error))

    def on_retriever_start(
        self,
        serialized: dict[str, Any],
        query: str,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        self.capture.retriever_start(run_id, serialized, kwargs)

    def on_retriever_end(
        self,
        documents: Sequence[Document],
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        self._record(self.capture.retriever_end(run_id, documents))

    def on_retriever_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        self._record(self.capture.retriever_error(run_id, error))


class _AsyncXAICallbackHandler(AsyncCallbackHandler):
    """Asynchronous handler attached by ``ainvoke`` and ``astream``.

    Failures propagate to the graph call (``raise_error``) unless the runtime's
    failure mode is ``FAIL_OPEN``. The handler runs inline, so LangChain awaits
    each recording directly instead of scheduling a task per callback.
    """

    run_inline = True

    def __init__(self, runtime: XAIRuntime, run: Run) -> None:
        self.capture = _Capture(runtime, run)
        self.raise_error = runtime.config.failure_mode is not FailureMode.FAIL_OPEN

    async def on_chain_start(
        self,
        serialized: dict[str, Any],
        inputs: dict[str, Any],
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        self.capture.chain_start(run_id, inputs, tags, metadata, kwargs.get("name"))

    async def on_chain_end(
        self,
        outputs: dict[str, Any],
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        if (recording := self.capture.chain_end(run_id, outputs)) is not None:
            await recording

    async def on_chain_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        if (recording := self.capture.chain_error(run_id, error)) is not None:
            await recording

    async def on_tool_start(
        self,
        serialized: dict[str, Any],
        input_str: str,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        self.capture.tool_start(run_id, serialized, kwargs)

    async def on_tool_end(
        self,
        output: Any,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        if (recording := self.capture.tool_end(run_id)) is not None:
            await recording

    async def on_tool_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        if (recording := self.capture.tool_error(run_id, error)) is not None:
            await recording

    async def on_retriever_start(
        self,
        serialized: dict[str, Any],
        query: str,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        self.capture.retriever_start(run_id, serialized, kwargs)

    async def on_retriever_end(
        self,
        documents: Sequence[Document],
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        if (recording := self.capture.retriever_end(run_id, documents)) is not None:
            await recording

    async def on_retriever_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        if (recording := self.capture.retriever_error(run_id, error)) is not None:
            await recording
