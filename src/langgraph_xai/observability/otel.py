"""OpenTelemetry observability adapter."""

from __future__ import annotations

from contextlib import AbstractContextManager
from typing import TYPE_CHECKING, Any

from .base import (
    ObservabilityAdapter,
    correlation_fields,
    event_payload,
    maybe_await,
    optional_import,
)
from .errors import ObservabilityAdapterError

if TYPE_CHECKING:
    from ..core.models import CanonicalEvent


class OpenTelemetryObservability(ObservabilityAdapter):
    """Emit canonical events as OpenTelemetry spans without changing global state."""

    def __init__(
        self,
        tracer: Any | None = None,
        *,
        tracer_name: str = "langgraph_xai",
        owns_provider: bool = False,
    ) -> None:
        super().__init__()
        if tracer is None:
            trace = optional_import("opentelemetry.trace", "opentelemetry-api")
            tracer = trace.get_tracer(tracer_name)
        self.tracer = tracer
        self.owns_provider = owns_provider

    async def _emit(self, event: CanonicalEvent) -> None:
        start_span = getattr(self.tracer, "start_as_current_span", None)
        if not callable(start_span):
            start_span = getattr(self.tracer, "start_span", None)
        if not callable(start_span):
            raise ObservabilityAdapterError(
                f"{type(self.tracer).__name__} does not provide an OpenTelemetry span method"
            )
        span = start_span(event.event_type)
        if isinstance(span, AbstractContextManager):
            with span as active:
                self._set_span_data(active, event)
        else:
            span = await maybe_await(span)
            self._set_span_data(span, event)
            end = getattr(span, "end", None)
            if callable(end):
                await maybe_await(end())

    @staticmethod
    def _set_span_data(span: Any, event: CanonicalEvent) -> None:
        attributes = correlation_fields(event)
        attributes["xai.event_type"] = event.event_type
        attributes["xai.payload"] = str(event_payload(event))
        set_attribute = getattr(span, "set_attribute", None)
        if not callable(set_attribute):
            raise ObservabilityAdapterError("OpenTelemetry span does not provide set_attribute()")
        for key, value in attributes.items():
            set_attribute(key, value)

    def _flush(self) -> Any:
        if not self.owns_provider:
            return None
        provider = getattr(self.tracer, "provider", None)
        force_flush = getattr(provider, "force_flush", None)
        return force_flush() if callable(force_flush) else None

    def _close(self) -> Any:
        if not self.owns_provider:
            return None
        provider = getattr(self.tracer, "provider", None)
        shutdown = getattr(provider, "shutdown", None)
        return shutdown() if callable(shutdown) else None


OTelObservability = OpenTelemetryObservability
OpenTelemetryProvider = OpenTelemetryObservability
