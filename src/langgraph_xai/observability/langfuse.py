"""Langfuse (SDK v4+) observability adapter."""

from __future__ import annotations

import asyncio
import re
from typing import TYPE_CHECKING

from .base import (
    DEFAULT_DEDUPLICATION_WINDOW,
    ObservabilityAdapter,
    correlation_fields,
    event_payload,
    optional_import,
)

if TYPE_CHECKING:
    from langfuse import Langfuse
    from langfuse.types import TraceContext

    from ..core.models import CanonicalEvent, ExecutionContext

_TRACE_ID = re.compile(r"[0-9a-f]{32}")


def langfuse_trace_context(context: ExecutionContext) -> TraceContext:
    """Return the Langfuse ``trace_context`` for an execution context.

    A ``trace_id`` that is already a valid Langfuse trace ID (32 lowercase hex
    characters) is used as-is, so the events join that existing trace.
    Otherwise every event of a run is grouped under ``run_id.hex``.
    """
    trace_id = context.trace_id
    if trace_id is not None and _TRACE_ID.fullmatch(trace_id):
        return {"trace_id": trace_id}
    return {"trace_id": context.run_id.hex}


class LangfuseObservability(ObservabilityAdapter):
    """Emit each canonical event as a Langfuse event observation.

    Events are created with ``client.create_event(...)``: the event type is the
    observation name, the canonical JSON payload is its ``input``, and the
    `correlation_fields` are its ``metadata``. All events of one run share one
    Langfuse trace (see `langfuse_trace_context`). The client batches and
    exports observations in the background. Without an injected client the
    adapter uses ``langfuse.get_client()`` and owns it: `close` then shuts it
    down. `flush` always flushes the client.
    """

    def __init__(
        self,
        client: Langfuse | None = None,
        *,
        deduplication_window: int = DEFAULT_DEDUPLICATION_WINDOW,
    ) -> None:
        super().__init__(deduplication_window=deduplication_window)
        self._owns_client = client is None
        self.client: Langfuse = (
            client if client is not None else optional_import("langfuse", "langfuse").get_client()
        )

    async def _emit(self, event: CanonicalEvent) -> None:
        self.client.create_event(
            name=event.event_type,
            trace_context=langfuse_trace_context(event.context),
            input=event_payload(event),
            metadata=correlation_fields(event),
        )

    async def _flush(self) -> None:
        await asyncio.to_thread(self.client.flush)

    async def _close(self) -> None:
        if self._owns_client:
            await asyncio.to_thread(self.client.shutdown)
