"""Provider-neutral capability contracts consumed by `XAIRuntime`.

Storage is an abstract base class, `ProvenanceStore`: a store subclasses it and
inherits the lineage walk. Every other capability is a `typing.Protocol` that a
provider satisfies structurally, without inheriting from anything. The runtime
resolves capabilities by type through its `Registry` and never branches on
concrete classes, so adding a backend never requires a runtime change.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence

    from .models import (
        AttributionResult,
        CanonicalEvent,
        Execution,
        ExecutionContext,
        Explanation,
        ExplanationContext,
        PolicyAction,
        PolicyDecision,
        ProvenanceLink,
    )


class StoreQuery:
    """Base class for provider-specific, typed store query objects."""


class ProvenanceStore(ABC):
    """Base class for stores of executions, provenance links, and canonical events.

    The runtime uses `InMemoryProvenanceStore` unless another store is
    registered. To keep records in your own database, subclass this class and
    implement `write`, `get`, `query`, `parents`, and `children`; `lineage` and
    `close` work as inherited. The repository's ``examples/postgres_store.py``
    is a complete PostgreSQL store built this way.

    A store must:

    - make `write` an idempotent upsert keyed by record type and ID, where the
      latest write wins: an `Execution` is written when its run starts, when it
      finishes, and when a record is added after it finished;
    - scope `query` to one application and tenant, and `parents` and
      `children` to one run, so tenants and runs never see each other's records;
    - return results in a stable order.
    """

    @abstractmethod
    async def write(self, item: Execution | ProvenanceLink | CanonicalEvent) -> None:
        """Insert or replace one record."""
        ...

    @abstractmethod
    async def get(self, entity_id: str) -> Execution | ProvenanceLink | CanonicalEvent | None:
        """Return the record whose ``id`` is ``entity_id``, or ``None``."""
        ...

    @abstractmethod
    def query(
        self, query: StoreQuery
    ) -> AsyncIterator[Execution | ProvenanceLink | CanonicalEvent]:
        """Yield the records matching an isolation-aware query, in a stable order."""
        ...

    @abstractmethod
    async def parents(
        self, entity_id: str, *, context: ExecutionContext
    ) -> Sequence[ProvenanceLink]:
        """Return the links that point *into* ``entity_id`` (its direct sources) in one run."""
        ...

    @abstractmethod
    async def children(
        self, entity_id: str, *, context: ExecutionContext
    ) -> Sequence[ProvenanceLink]:
        """Return the links that point *out of* ``entity_id`` (what it produced) in one run."""
        ...

    async def lineage(
        self,
        entity_id: str,
        *,
        context: ExecutionContext,
        max_depth: int = 100,
    ) -> Sequence[ProvenanceLink]:
        """Return every upstream link of ``entity_id``, breadth-first and nearest first.

        Walks `parents` one level at a time and expands each entity once, so
        every link is returned exactly once and cycles terminate. Override it
        only to use a faster native query, such as a recursive SQL query.

        Raises:
            ValueError: If ``max_depth`` is less than 1.
        """
        if max_depth < 1:
            raise ValueError("max_depth must be positive")
        result: list[ProvenanceLink] = []
        visited = {entity_id}
        frontier = [entity_id]
        for _ in range(max_depth):
            next_frontier: list[str] = []
            for current in frontier:
                for link in await self.parents(current, context=context):
                    result.append(link)
                    source = str(link.source_id)
                    if source not in visited:
                        visited.add(source)
                        next_frontier.append(source)
            if not next_frontier:
                break
            frontier = next_frontier
        return tuple(result)

    async def close(self) -> None:  # noqa: B027 - optional hook, no-op by default
        """Release resources held by the store. The default does nothing."""


@runtime_checkable
class ObservabilityProvider(Protocol):
    """Telemetry sink for canonical events (LangSmith, Langfuse, OpenTelemetry, or none).

    The runtime forwards each canonical event to the registered provider, so an
    existing tracing stack gains the explainability layer without a separate
    integration per provider.
    """

    async def emit(self, event: CanonicalEvent) -> None:
        """Send one canonical event to the backend."""
        ...

    async def flush(self) -> None:
        """Deliver any buffered events."""
        ...

    async def close(self) -> None:
        """Flush and release the backend connection."""
        ...


@runtime_checkable
class AttributionEngine(Protocol):
    """Scores which factors and evidence contributed to a decision, and by how much.

    See [Concepts: Attribution](../concepts/attribution.md) for the output shape
    and what an `AttributionResult` does and does not claim.
    """

    async def attribute(self, context: ExplanationContext) -> AttributionResult:
        """Return signed contributions for the decision in ``context``."""
        ...


@runtime_checkable
class ExplanationEngine(Protocol):
    """Assembles the final `Explanation` from a policy-filtered context.

    Set ``requires_llm = True`` if `explain` calls a live model; the runtime then
    refuses to run it unless `XAIConfig.llm_explanation_enabled` is set.
    """

    requires_llm: bool

    async def explain(self, context: ExplanationContext) -> Explanation:
        """Render an explanation for ``context.audience``."""
        ...


@runtime_checkable
class PolicyProvider(Protocol):
    """Decides what an audience may see when an explanation is exposed.

    See [Concepts: Policies](../concepts/policies.md) for a real `PolicyDecision`
    and how the explanation engines honor it.
    """

    async def evaluate(self, context: ExplanationContext, action: PolicyAction) -> PolicyDecision:
        """Return the policy decision for ``action`` and ``context.audience``."""
        ...


@runtime_checkable
class CapturePolicy(Protocol):
    """Decides, per canonical event, whether it may be stored and emitted."""

    async def evaluate(self, event: CanonicalEvent) -> PolicyDecision:
        """Return a decision whose ``allowed`` flag gates the event."""
        ...
