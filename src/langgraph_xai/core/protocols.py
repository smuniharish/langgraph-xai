"""Provider-neutral capability contracts used by `XAIRuntime`."""

from __future__ import annotations

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
    """Marker protocol for provider-specific, typed store query objects."""


@runtime_checkable
class ProvenanceStore(Protocol):
    """Durable storage for executions, provenance links, and canonical events.

    Implement this to back xgraph with a real database instead of the
    built-in `InMemoryProvenanceStore`. The
    runtime never checks *which* store is registered — it only calls these
    methods, so a new backend requires no runtime changes.
    """

    async def write(self, item: Execution | ProvenanceLink | CanonicalEvent) -> None: ...

    async def get(self, entity_id: str) -> Execution | ProvenanceLink | CanonicalEvent | None: ...

    def query(
        self, query: StoreQuery
    ) -> AsyncIterator[Execution | ProvenanceLink | CanonicalEvent]: ...

    async def parents(
        self, entity_id: str, *, context: ExecutionContext
    ) -> Sequence[ProvenanceLink]:
        """Return the links that point *into* ``entity_id`` (its direct sources)."""

    async def children(
        self, entity_id: str, *, context: ExecutionContext
    ) -> Sequence[ProvenanceLink]:
        """Return the links that point *out of* ``entity_id`` (what it produced)."""

    async def lineage(
        self,
        entity_id: str,
        *,
        context: ExecutionContext,
        max_depth: int = 100,
    ) -> Sequence[ProvenanceLink]:
        """Walk ``parents`` repeatedly to return the full upstream chain."""

    async def close(self) -> None: ...


@runtime_checkable
class ObservabilityProvider(Protocol):
    """Telemetry sink for canonical events (Langfuse, OpenTelemetry, LangSmith, or none).

    xgraph does not replace these tools — it emits its own canonical events
    to whichever one is registered, so existing dashboards/traces gain
    xgraph's semantic layer without a separate integration per provider.
    """

    async def emit(self, event: CanonicalEvent) -> None: ...

    async def flush(self) -> None: ...

    async def close(self) -> None: ...


@runtime_checkable
class AttributionEngine(Protocol):
    """Computes which factors/evidence contributed to a decision, and by how much.

    See [Concepts: Attribution](../concepts/attribution.md) for the
    output shape and what an `AttributionResult` does and does not claim.
    """

    async def attribute(self, context: ExplanationContext) -> AttributionResult: ...


@runtime_checkable
class ExplanationEngine(Protocol):
    """Assembles the final `Explanation` from a policy-filtered context.

    Set ``requires_llm = True`` if `explain` calls a live model; the runtime
    then refuses to run it unless `XAIConfig.llm_explanation_enabled` is set.
    """

    requires_llm: bool

    async def explain(self, context: ExplanationContext) -> Explanation: ...


@runtime_checkable
class PolicyProvider(Protocol):
    """Decides what an audience may see when an explanation is exposed.

    See [Concepts: Policies](../concepts/policies.md) for a real
    `PolicyDecision` and the disclosure-matrix example for every audience.
    """

    async def evaluate(
        self, context: ExplanationContext, action: PolicyAction
    ) -> PolicyDecision: ...


@runtime_checkable
class CapturePolicy(Protocol):
    """Decides, per event, whether raw capture should proceed, be redacted, or be dropped."""

    async def evaluate(self, event: CanonicalEvent) -> PolicyDecision: ...


# Compatibility aliases for early adopters.
Storage = ProvenanceStore
Observability = ObservabilityProvider
AttributionProvider = AttributionEngine
ExplanationProvider = ExplanationEngine
Policy = PolicyProvider
Capture = CapturePolicy
