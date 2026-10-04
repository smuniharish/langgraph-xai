"""Shared implementation for canonical-event observability adapters."""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from collections import OrderedDict
from importlib import import_module
from typing import TYPE_CHECKING, Any

from .errors import AdapterClosedError, ObservabilityAdapterError, OptionalDependencyError

if TYPE_CHECKING:
    from uuid import UUID

    from ..core.models import CanonicalEvent

DEFAULT_DEDUPLICATION_WINDOW = 4096


def event_payload(event: CanonicalEvent) -> dict[str, Any]:
    """Serialize a canonical event to JSON-compatible data."""
    return event.model_dump(mode="json")


def correlation_fields(event: CanonicalEvent) -> dict[str, str]:
    """Return the ``xai.*`` identifiers that correlate an event across systems.

    Always includes ``xai.event_id`` (the event's ``id``), ``xai.event_type``,
    ``xai.application_id``, ``xai.tenant_id``, ``xai.graph_id``, and
    ``xai.run_id``; adds ``xai.thread_id``, ``xai.trace_id``, and
    ``xai.checkpoint_id`` when the event's context carries them.
    """
    context = event.context
    fields = {
        "xai.event_id": str(event.id),
        "xai.event_type": event.event_type,
        "xai.application_id": context.application_id,
        "xai.tenant_id": context.tenant_id,
        "xai.graph_id": context.graph_id,
        "xai.run_id": str(context.run_id),
    }
    for name, value in (
        ("thread_id", context.thread_id),
        ("trace_id", context.trace_id),
        ("checkpoint_id", context.checkpoint_id),
    ):
        if value is not None:
            fields[f"xai.{name}"] = value
    return fields


class ObservabilityAdapter(ABC):
    """Base class implementing the `ObservabilityProvider` lifecycle safely.

    Subclasses implement `_emit` (and optionally `_flush`/`_close`). The base
    class rejects use after `close`, wraps backend errors in
    `ObservabilityAdapterError`, and drops duplicate events: an event whose
    ``id`` was emitted within the last ``deduplication_window`` events is
    skipped (``0`` disables deduplication). A failed emit is forgotten, so the
    same event can be retried. Emits are not serialized, so concurrent events
    reach the backend concurrently.
    """

    def __init__(self, *, deduplication_window: int = DEFAULT_DEDUPLICATION_WINDOW) -> None:
        if deduplication_window < 0:
            raise ValueError("deduplication_window must not be negative")
        self._closed = False
        self._window = deduplication_window
        self._seen: OrderedDict[UUID, None] = OrderedDict()
        self._lock = threading.Lock()

    async def emit(self, event: CanonicalEvent) -> None:
        """Send ``event`` once, unless it was already emitted recently."""
        if self._closed:
            raise AdapterClosedError(f"{type(self).__name__} is closed")
        if not self._claim(event.id):
            return
        try:
            await self._emit(event)
        except BaseException as exc:
            self._release(event.id)
            if isinstance(exc, Exception) and not isinstance(exc, ObservabilityAdapterError):
                raise ObservabilityAdapterError(
                    f"{type(self).__name__} failed to emit {event.event_type}"
                ) from exc
            raise

    async def flush(self) -> None:
        """Deliver any events the backend has buffered."""
        if self._closed:
            raise AdapterClosedError(f"{type(self).__name__} is closed")
        try:
            await self._flush()
        except ObservabilityAdapterError:
            raise
        except Exception as exc:
            raise ObservabilityAdapterError(f"{type(self).__name__} failed to flush") from exc

    async def close(self) -> None:
        """Release backend resources; idempotent."""
        if self._closed:
            return
        try:
            await self._close()
        except ObservabilityAdapterError:
            raise
        except Exception as exc:
            raise ObservabilityAdapterError(f"{type(self).__name__} failed to close") from exc
        finally:
            self._closed = True

    @abstractmethod
    async def _emit(self, event: CanonicalEvent) -> None:
        """Send one event to the concrete backend."""

    async def _flush(self) -> None:  # noqa: B027 - optional hook, no-op by default
        """Flush the backend; no-op by default."""

    async def _close(self) -> None:  # noqa: B027 - optional hook, no-op by default
        """Close the backend; no-op by default."""

    def _claim(self, event_id: UUID) -> bool:
        if not self._window:
            return True
        with self._lock:
            if event_id in self._seen:
                return False
            self._seen[event_id] = None
            if len(self._seen) > self._window:
                self._seen.popitem(last=False)
            return True

    def _release(self, event_id: UUID) -> None:
        with self._lock:
            self._seen.pop(event_id, None)


def optional_import(module: str, extra: str) -> Any:
    """Import an optional SDK, raising `OptionalDependencyError` naming the extra to install."""
    try:
        return import_module(module)
    except ImportError as exc:
        raise OptionalDependencyError(
            f"this adapter requires the {extra!r} extra: pip install 'langgraph-xai[{extra}]'"
        ) from exc
