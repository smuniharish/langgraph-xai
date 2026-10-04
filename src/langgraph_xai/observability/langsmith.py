"""LangSmith observability adapter."""

from __future__ import annotations

import asyncio
import threading
from collections import OrderedDict
from typing import TYPE_CHECKING, Any

from ..core.models import (
    ExecutionCompletedEvent,
    ExecutionFailedEvent,
    HumanInteractionType,
    InterruptEvent,
)
from .base import (
    DEFAULT_DEDUPLICATION_WINDOW,
    ObservabilityAdapter,
    correlation_fields,
    event_payload,
    optional_import,
)

if TYPE_CHECKING:
    from uuid import UUID

    from langsmith import Client
    from langsmith.run_trees import RunTree

    from ..core.models import CanonicalEvent

_RUN_FIELDS = ("xai.event_id", "xai.event_type")


def _outcome(event: CanonicalEvent) -> tuple[dict[str, str], str | None] | None:
    if isinstance(event, ExecutionCompletedEvent):
        return {"status": "completed"}, None
    if isinstance(event, ExecutionFailedEvent):
        return {"status": "failed"}, f"{event.error.exception_type}: {event.error.message}"
    if (
        isinstance(event, InterruptEvent)
        and event.interaction.interaction_type is HumanInteractionType.INTERRUPT
    ):
        return {"status": "interrupted"}, None
    return None


class LangSmithObservability(ObservabilityAdapter):
    """Emit canonical events as LangSmith runs, one trace per langgraph-xai run.

    The first event of a run opens a root run whose ID is the langgraph-xai
    ``run_id``, so the LangSmith trace ID equals the run ID. Every event becomes
    a completed child run whose ID is the event's ``id`` and whose name is the
    event type, with the canonical payload as ``inputs`` and the
    `correlation_fields` as metadata. The root run is ended when the run
    completes, fails, or is interrupted. Runs are created through LangSmith's
    ``RunTree``, so the client batches them in the background rather than
    blocking the graph.

    Without an injected client the adapter creates ``langsmith.Client()`` and
    owns it: `close` then closes it. `flush` always flushes the client. At most
    ``max_open_traces`` recent traces are tracked.

    Raises:
        ValueError: If ``max_open_traces`` is not positive.
    """

    def __init__(
        self,
        client: Client | None = None,
        *,
        project_name: str | None = None,
        max_open_traces: int = 1024,
        deduplication_window: int = DEFAULT_DEDUPLICATION_WINDOW,
    ) -> None:
        super().__init__(deduplication_window=deduplication_window)
        if max_open_traces < 1:
            raise ValueError("max_open_traces must be positive")
        self._run_tree: type[RunTree] = optional_import("langsmith.run_trees", "langsmith").RunTree
        self._owns_client = client is None
        self.client: Client = (
            client if client is not None else optional_import("langsmith", "langsmith").Client()
        )
        self.project_name = project_name
        self._max_open_traces = max_open_traces
        self._roots: OrderedDict[UUID, RunTree] = OrderedDict()
        self._roots_lock = threading.Lock()

    async def _emit(self, event: CanonicalEvent) -> None:
        root = self._root(event)
        child = root.create_child(
            name=event.event_type,
            run_type="chain",
            run_id=event.id,
            inputs=event_payload(event),
            start_time=event.timestamp,
            end_time=event.timestamp,
            extra={"metadata": correlation_fields(event)},
        )
        # Children are posted one by one, so the root never needs to hold them.
        root.child_runs.clear()
        child.post()
        outcome = _outcome(event)
        if outcome is not None and root.end_time is None:
            outputs, error = outcome
            root.end(outputs=outputs, error=error, end_time=event.timestamp)
            root.patch()

    def _root(self, event: CanonicalEvent) -> RunTree:
        context = event.context
        with self._roots_lock:
            root = self._roots.get(context.run_id)
            if root is not None:
                self._roots.move_to_end(context.run_id)
                return root
            options: dict[str, Any] = {}
            if self.project_name is not None:
                options["project_name"] = self.project_name
            metadata = {
                key: value
                for key, value in correlation_fields(event).items()
                if key not in _RUN_FIELDS
            }
            root = self._run_tree(
                id=context.run_id,
                name=f"langgraph-xai: {context.graph_id}",
                run_type="chain",
                inputs={
                    "application_id": context.application_id,
                    "tenant_id": context.tenant_id,
                    "graph_id": context.graph_id,
                },
                start_time=event.timestamp,
                extra={"metadata": metadata},
                ls_client=self.client,
                **options,
            )
            root.post()
            self._roots[context.run_id] = root
            if len(self._roots) > self._max_open_traces:
                self._roots.popitem(last=False)
            return root

    async def _flush(self) -> None:
        await asyncio.to_thread(self.client.flush)

    async def _close(self) -> None:
        if self._owns_client:
            await asyncio.to_thread(self.client.close)
