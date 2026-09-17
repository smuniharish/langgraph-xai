"""Langfuse v4 observability adapter."""

from __future__ import annotations

from contextlib import AbstractContextManager
from typing import TYPE_CHECKING, Any

from .base import (
    ObservabilityAdapter,
    callable_or_error,
    correlation_fields,
    event_payload,
    maybe_await,
    optional_import,
)
from .errors import ObservabilityAdapterError

if TYPE_CHECKING:
    from ..core.models import CanonicalEvent


class LangfuseObservability(ObservabilityAdapter):
    """Emit canonical events as Langfuse v4 events."""

    def __init__(self, client: Any | None = None) -> None:
        super().__init__()
        self._owns_client = client is None
        if client is None:
            client = optional_import("langfuse", "langfuse").get_client()
        self.client = client

    async def _emit(self, event: CanonicalEvent) -> None:
        payload = event_payload(event)
        metadata = correlation_fields(event)
        if callable(getattr(self.client, "start_as_current_observation", None)):
            method = callable_or_error(self.client, "start_as_current_observation")
            observation = method(
                name=event.event_type,
                as_type="span",
                metadata=metadata,
                input=payload,
                trace_context={"trace_id": event.context.trace_id}
                if event.context.trace_id
                else None,
            )
            observation = await maybe_await(observation)
            if isinstance(observation, AbstractContextManager):
                with observation as active:
                    end = getattr(active, "end", None)
                    if callable(end):
                        await maybe_await(end())
                return
            end = getattr(observation, "end", None)
            if callable(end):
                await maybe_await(end())
            return
        if callable(getattr(self.client, "create_event", None)):
            method = callable_or_error(self.client, "create_event")
            await maybe_await(
                method(
                    name=event.event_type,
                    metadata=metadata,
                    input=payload,
                    trace_id=event.context.trace_id,
                    id=str(event.event_id),
                )
            )
            return
        raise ObservabilityAdapterError(
            "Langfuse client does not provide create_event() or start_as_current_observation()"
        )

    def _flush(self) -> Any:
        if not self._owns_client:
            return None
        flush = getattr(self.client, "flush", None)
        return flush() if callable(flush) else None

    def _close(self) -> Any:
        if not self._owns_client:
            return None
        shutdown = getattr(self.client, "shutdown", None)
        if callable(shutdown):
            return shutdown()
        close = getattr(self.client, "close", None)
        return close() if callable(close) else None


LangfuseProvider = LangfuseObservability
