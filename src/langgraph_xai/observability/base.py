"""Shared implementation details for canonical-event observability adapters."""

from __future__ import annotations

import inspect
from abc import ABC, abstractmethod
from asyncio import Lock
from typing import TYPE_CHECKING, Any

from .errors import AdapterClosedError, ObservabilityAdapterError

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from uuid import UUID

    from ..core.models import CanonicalEvent

type EmitResult = Any


async def maybe_await(value: EmitResult) -> EmitResult:
    """Await SDK methods regardless of whether a fake or SDK is sync or async."""
    if inspect.isawaitable(value):
        return await value
    return value


def event_payload(event: CanonicalEvent) -> dict[str, Any]:
    """Serialize a canonical event without losing its correlation metadata."""
    return event.model_dump(mode="json")


def correlation_fields(event: CanonicalEvent) -> dict[str, str]:
    """Return non-empty correlation IDs using stable, provider-neutral names."""
    context = event.context
    fields: dict[str, str] = {
        "xai.event_id": str(event.event_id),
        "xai.run_id": str(context.run_id),
    }
    for name in ("trace_id", "span_id", "parent_id", "checkpoint_id"):
        value = getattr(context, name)
        if value is not None:
            fields[f"xai.{name}"] = value
    return fields


class ObservabilityAdapter(ABC):
    """Base class implementing the async provider protocol safely."""

    def __init__(self) -> None:
        self._closed = False
        self._seen_event_ids: set[UUID] = set()
        self._lock = Lock()

    async def emit(self, event: CanonicalEvent) -> None:
        if self._closed:
            raise AdapterClosedError(f"{type(self).__name__} is closed")
        async with self._lock:
            if event.event_id in self._seen_event_ids:
                return
            try:
                await self._emit(event)
            except ObservabilityAdapterError:
                raise
            except Exception as exc:
                raise ObservabilityAdapterError(
                    f"{type(self).__name__} failed to emit {event.event_type}"
                ) from exc
            self._seen_event_ids.add(event.event_id)

    async def flush(self) -> None:
        if self._closed:
            raise AdapterClosedError(f"{type(self).__name__} is closed")
        try:
            await maybe_await(self._flush())
        except ObservabilityAdapterError:
            raise
        except Exception as exc:
            raise ObservabilityAdapterError(f"{type(self).__name__} failed to flush") from exc

    async def close(self) -> None:
        if self._closed:
            return
        try:
            await maybe_await(self._close())
        except ObservabilityAdapterError:
            raise
        except Exception as exc:
            raise ObservabilityAdapterError(f"{type(self).__name__} failed to close") from exc
        finally:
            self._closed = True

    @abstractmethod
    async def _emit(self, event: CanonicalEvent) -> None:
        """Send one event to the concrete backend."""

    def _flush(self) -> Awaitable[None] | None:
        return None

    def _close(self) -> Awaitable[None] | None:
        return None


def optional_import(module: str, package: str) -> Any:
    """Import an optional SDK only when its adapter is instantiated."""
    try:
        return __import__(module, fromlist=["*"])
    except ImportError as exc:
        from .errors import OptionalDependencyError

        raise OptionalDependencyError(
            f"{package} observability requires the optional dependency {package!r}"
        ) from exc


def callable_or_error(client: Any, name: str) -> Callable[..., Any]:
    method = getattr(client, name, None)
    if not callable(method):
        raise ObservabilityAdapterError(
            f"{type(client).__name__} does not provide required method {name}()"
        )
    return method
