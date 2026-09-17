"""LangSmith observability adapter."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .base import (
    ObservabilityAdapter,
    callable_or_error,
    correlation_fields,
    event_payload,
    maybe_await,
    optional_import,
)

if TYPE_CHECKING:
    from ..core.models import CanonicalEvent


class LangSmithObservability(ObservabilityAdapter):
    """Emit canonical events as LangSmith runs."""

    def __init__(self, client: Any | None = None, *, project_name: str | None = None) -> None:
        super().__init__()
        self._owns_client = client is None
        if client is None:
            client = optional_import("langsmith", "langsmith").Client()
        self.client = client
        self.project_name = project_name

    async def _emit(self, event: CanonicalEvent) -> None:
        create_run = callable_or_error(self.client, "create_run")
        payload = event_payload(event)
        context = event.context
        kwargs: dict[str, Any] = {
            "name": event.event_type,
            "run_type": "chain",
            "inputs": payload,
            "id": event.event_id,
            "trace_id": context.trace_id,
            "parent_run_id": context.parent_id,
            "extra": {"metadata": correlation_fields(event)},
        }
        if self.project_name is not None:
            kwargs["project_name"] = self.project_name
        await maybe_await(
            create_run(**{key: value for key, value in kwargs.items() if value is not None})
        )

    def _flush(self) -> Any:
        if not self._owns_client:
            return None
        flush = getattr(self.client, "flush", None)
        return flush() if callable(flush) else None

    def _close(self) -> Any:
        if not self._owns_client:
            return None
        close = getattr(self.client, "close", None)
        return close() if callable(close) else None


LangSmithProvider = LangSmithObservability
