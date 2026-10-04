"""OpenTelemetry observability adapter."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from .base import (
    DEFAULT_DEDUPLICATION_WINDOW,
    ObservabilityAdapter,
    correlation_fields,
    optional_import,
)

if TYPE_CHECKING:
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.trace import Tracer

    from ..core.models import CanonicalEvent

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_MICROSECOND = timedelta(microseconds=1)


def _nanoseconds(moment: datetime) -> int:
    return (moment - _EPOCH) // _MICROSECOND * 1_000


class OpenTelemetryObservability(ObservabilityAdapter):
    """Emit each canonical event as an OpenTelemetry span.

    Each event becomes a zero-duration span named after its event type and
    stamped with the event's timestamp, created with ``tracer.start_span`` so
    the current span context is never changed. Span attributes are the
    `correlation_fields` plus ``xai.payload``, the event's canonical JSON. The
    span's parent is whatever span is current when the event is recorded.

    Pass ``tracer_provider`` (an SDK ``TracerProvider``) to let the adapter
    obtain its tracer and flush the provider on `flush`; set
    ``owns_provider=True`` as well to shut the provider down on `close`.
    Without either argument the global tracer provider is used and never
    flushed or shut down by the adapter.

    Raises:
        ValueError: If ``owns_provider`` is set without a ``tracer_provider``.
    """

    def __init__(
        self,
        tracer: Tracer | None = None,
        *,
        tracer_provider: TracerProvider | None = None,
        tracer_name: str = "langgraph_xai",
        owns_provider: bool = False,
        deduplication_window: int = DEFAULT_DEDUPLICATION_WINDOW,
    ) -> None:
        super().__init__(deduplication_window=deduplication_window)
        if owns_provider and tracer_provider is None:
            raise ValueError("owns_provider requires a tracer_provider")
        if tracer is None:
            tracer = (
                tracer_provider.get_tracer(tracer_name)
                if tracer_provider is not None
                else optional_import("opentelemetry.trace", "otel").get_tracer(tracer_name)
            )
        self.tracer: Tracer = tracer
        self.tracer_provider = tracer_provider
        self.owns_provider = owns_provider

    async def _emit(self, event: CanonicalEvent) -> None:
        attributes: dict[str, str] = correlation_fields(event)
        attributes["xai.payload"] = event.model_dump_json()
        timestamp = _nanoseconds(event.timestamp)
        span = self.tracer.start_span(event.event_type, attributes=attributes, start_time=timestamp)
        span.end(end_time=timestamp)

    async def _flush(self) -> None:
        if self.tracer_provider is not None:
            await asyncio.to_thread(self.tracer_provider.force_flush)

    async def _close(self) -> None:
        if self.owns_provider and self.tracer_provider is not None:
            await asyncio.to_thread(self.tracer_provider.shutdown)
