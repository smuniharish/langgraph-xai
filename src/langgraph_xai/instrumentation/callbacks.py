"""LangChain callback handlers using only its public callback surface."""

from __future__ import annotations

import threading
from collections.abc import Mapping
from time import monotonic
from typing import TYPE_CHECKING, Any

from langchain_core.callbacks import AsyncCallbackHandler, BaseCallbackHandler

from langgraph_xai.core.models import RetrievedDocument, ToolStatus

if TYPE_CHECKING:
    from collections.abc import Sequence
    from uuid import UUID

    from langchain_core.documents import Document

    from langgraph_xai.runtime.runtime import Run, XAIRuntime


def _name(serialized: dict[str, Any] | None, fallback: str) -> str:
    if serialized:
        value = serialized.get("name") or serialized.get("id")
        if isinstance(value, list):
            value = value[-1] if value else None
        if value:
            return str(value)
    return fallback


def _mapping(value: Any) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


class _CaptureState:
    def __init__(self) -> None:
        self._chains: dict[UUID, tuple[str, Mapping[str, Any] | None]] = {}
        self._tools: dict[UUID, tuple[str, float]] = {}
        self._retrievers: dict[UUID, str] = {}
        self._lock = threading.Lock()

    def chain_start(
        self,
        run_id: UUID,
        parent_run_id: UUID | None,
        serialized: dict[str, Any] | None,
        inputs: Any,
        metadata: dict[str, Any] | None,
        name: str | None,
    ) -> None:
        if parent_run_id is None:
            return
        node = (metadata or {}).get("langgraph_node") or name or _name(serialized, "node")
        with self._lock:
            self._chains[run_id] = (str(node), _mapping(inputs))

    def chain_end(self, run_id: UUID) -> tuple[str, Mapping[str, Any] | None] | None:
        with self._lock:
            return self._chains.pop(run_id, None)

    def tool_start(self, run_id: UUID, serialized: dict[str, Any] | None) -> None:
        with self._lock:
            self._tools[run_id] = (_name(serialized, "tool"), monotonic())

    def tool_end(self, run_id: UUID) -> tuple[str, float] | None:
        with self._lock:
            return self._tools.pop(run_id, None)

    def retriever_start(self, run_id: UUID, serialized: dict[str, Any] | None) -> None:
        with self._lock:
            self._retrievers[run_id] = _name(serialized, "retriever")

    def retriever_end(self, run_id: UUID) -> str:
        with self._lock:
            return self._retrievers.pop(run_id, "retriever")


class XAICallbackHandler(BaseCallbackHandler):
    """Synchronous handler used by ``invoke``, ``stream``, and ``batch``."""

    def __init__(self, runtime: XAIRuntime, run: Run) -> None:
        self.runtime = runtime
        self.run = run
        self.state = _CaptureState()

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
        self.state.chain_start(
            run_id, parent_run_id, serialized, inputs, metadata, kwargs.get("name")
        )

    def on_chain_end(
        self,
        outputs: dict[str, Any],
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        started = self.state.chain_end(run_id)
        if started:
            self.runtime.run_sync(
                self.runtime.record_state_delta(
                    started[0], started[1], _mapping(outputs), run=self.run
                )
            )

    def on_tool_start(
        self,
        serialized: dict[str, Any],
        input_str: str,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        self.state.tool_start(run_id, serialized)

    def on_tool_end(
        self,
        output: Any,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        started = self.state.tool_end(run_id)
        if started:
            self.runtime.run_sync(
                self.runtime.record_tool(
                    started[0],
                    status=ToolStatus.SUCCEEDED,
                    tool_call_id=str(run_id),
                    latency_ms=(monotonic() - started[1]) * 1000,
                    run=self.run,
                )
            )

    def on_tool_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        started = self.state.tool_end(run_id)
        if started:
            self.runtime.run_sync(
                self.runtime.record_tool(
                    started[0],
                    status=ToolStatus.FAILED,
                    tool_call_id=str(run_id),
                    latency_ms=(monotonic() - started[1]) * 1000,
                    metadata={"error_type": type(error).__name__},
                    run=self.run,
                )
            )

    def on_retriever_start(
        self,
        serialized: dict[str, Any],
        query: str,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        self.state.retriever_start(run_id, serialized)

    def on_retriever_end(
        self,
        documents: Sequence[Document],
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        retriever = self.state.retriever_end(run_id)
        self.runtime.run_sync(
            self.runtime.record_retrieval(
                retriever,
                documents=[
                    RetrievedDocument(document_id=str(document.id or index + 1), rank=index + 1)
                    for index, document in enumerate(documents)
                ],
                run=self.run,
            )
        )


class AsyncXAICallbackHandler(AsyncCallbackHandler):
    """Asynchronous handler used by ``ainvoke``, ``astream``, and ``abatch``."""

    def __init__(self, runtime: XAIRuntime, run: Run) -> None:
        self.runtime = runtime
        self.run = run
        self.state = _CaptureState()

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
        self.state.chain_start(
            run_id, parent_run_id, serialized, inputs, metadata, kwargs.get("name")
        )

    async def on_chain_end(
        self,
        outputs: dict[str, Any],
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        started = self.state.chain_end(run_id)
        if started:
            await self.runtime.record_state_delta(
                started[0], started[1], _mapping(outputs), run=self.run
            )

    async def on_tool_start(
        self,
        serialized: dict[str, Any],
        input_str: str,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        self.state.tool_start(run_id, serialized)

    async def on_tool_end(
        self,
        output: Any,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        started = self.state.tool_end(run_id)
        if started:
            await self.runtime.record_tool(
                started[0],
                status=ToolStatus.SUCCEEDED,
                tool_call_id=str(run_id),
                latency_ms=(monotonic() - started[1]) * 1000,
                run=self.run,
            )

    async def on_tool_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        started = self.state.tool_end(run_id)
        if started:
            await self.runtime.record_tool(
                started[0],
                status=ToolStatus.FAILED,
                tool_call_id=str(run_id),
                latency_ms=(monotonic() - started[1]) * 1000,
                metadata={"error_type": type(error).__name__},
                run=self.run,
            )

    async def on_retriever_start(
        self,
        serialized: dict[str, Any],
        query: str,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        self.state.retriever_start(run_id, serialized)

    async def on_retriever_end(
        self,
        documents: Sequence[Document],
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        retriever = self.state.retriever_end(run_id)
        await self.runtime.record_retrieval(
            retriever,
            documents=[
                RetrievedDocument(document_id=str(document.id or index + 1), rank=index + 1)
                for index, document in enumerate(documents)
            ],
            run=self.run,
        )
