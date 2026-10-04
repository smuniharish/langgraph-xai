"""Shared builders and fake providers for the test suite."""

from __future__ import annotations

import asyncio
import itertools
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, TypedDict

from langgraph.graph import END, START, StateGraph

from langgraph_xai import (
    Decision,
    DecisionFactor,
    Evidence,
    EvidenceType,
    Execution,
    ExecutionContext,
    ExecutionStatus,
    ExplanationContext,
    ProvenanceStore,
    StoreFilter,
    XAIRuntime,
)
from langgraph_xai.storage import InMemoryProvenanceStore

if TYPE_CHECKING:
    from langgraph_xai.core import CanonicalEvent
    from langgraph_xai.plugins import SemanticArtifact


class State(TypedDict, total=False):
    """A small graph state used across instrumentation tests."""

    question: str
    answer: str
    count: int
    note: str


def context(tenant: str = "tenant", **overrides: Any) -> ExecutionContext:
    return ExecutionContext(application_id="app", tenant_id=tenant, graph_id="graph", **overrides)


def execution(ctx: ExecutionContext | None = None) -> Execution:
    return Execution(
        context=ctx or context(),
        status=ExecutionStatus.COMPLETED,
        started_at=datetime.now(UTC),
    )


def explanation_context(
    *,
    audience: str = "developer",
    with_evidence: bool = True,
    policies: list[Any] | None = None,
) -> ExplanationContext:
    ctx = context()
    evidence = [
        Evidence(
            context=ctx,
            evidence_type=EvidenceType.TOOL_RESULT,
            summary="Fraud detector scored the transaction 0.91.",
            content_reference="fraud://8841",
            confidence=0.9,
            quality=0.5,
        ),
        Evidence(
            context=ctx,
            evidence_type=EvidenceType.POLICY,
            summary="Policy requires review above 0.8.",
            confidence=1.0,
        ),
    ]
    decision = Decision(
        context=ctx,
        decision_type="routing",
        selected_action="HUMAN_REVIEW",
        candidate_actions=["AUTO_APPROVE", "HUMAN_REVIEW"],
        evidence_ids=[item.id for item in evidence] if with_evidence else [],
        factors=[
            DecisionFactor(name="risk", value=0.91, weight=0.8, evidence_ids=[evidence[0].id]),
            DecisionFactor(name="threshold", value=0.8, weight=0.2),
        ],
        confidence=0.9,
    )
    return ExplanationContext(
        execution=execution(ctx),
        decision=decision,
        evidence=evidence if with_evidence else [],
        policies=policies or [],
        audience=audience,
    )


def linear_graph(*nodes: tuple[str, Any], state: type = State, **compile_kwargs: Any):
    """Compile a graph that runs ``nodes`` (functions or runnables) in order."""
    builder = StateGraph(state)
    names = [name for name, _ in nodes]
    for name, function in nodes:
        builder.add_node(name, function)
    builder.add_edge(START, names[0])
    for first, second in itertools.pairwise(names):
        builder.add_edge(first, second)
    builder.add_edge(names[-1], END)
    return builder.compile(**compile_kwargs)


async def stored(runtime: XAIRuntime, **filters: Any) -> list[Any]:
    store = runtime.registry.require(ProvenanceStore)
    query = StoreFilter(
        application_id=runtime.application_id,
        tenant_id=runtime.tenant_id,
        limit=500,
        **filters,
    )
    return [item async for item in store.query(query)]


async def executions(runtime: XAIRuntime) -> list[Execution]:
    return [
        item for item in await stored(runtime, item_type=Execution) if isinstance(item, Execution)
    ]


class FailingStore(InMemoryProvenanceStore):
    """A store whose writes fail, optionally only for some record types."""

    def __init__(self, error: Exception | None = None, *, only: tuple[type, ...] = ()) -> None:
        super().__init__()
        self.error = error or OSError("storage unavailable")
        self.only = only

    async def write(self, item: Any) -> None:
        if not self.only or isinstance(item, self.only):
            raise self.error
        await super().write(item)


class RecordingObservability:
    """An observability provider that records every call."""

    def __init__(self, *, fail: bool = False, delay: float = 0.0) -> None:
        self.events: list[CanonicalEvent] = []
        self.flushed = 0
        self.closed = 0
        self.fail = fail
        self.delay = delay

    async def emit(self, event: CanonicalEvent) -> None:
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.fail:
            raise ConnectionError("exporter unavailable")
        self.events.append(event)

    async def flush(self) -> None:
        self.flushed += 1
        if self.fail:
            raise ConnectionError("exporter unavailable")

    async def close(self) -> None:
        self.closed += 1
        if self.fail:
            raise ConnectionError("exporter unavailable")


class RecordingPlugin:
    """A plugin that records artifacts and lifecycle calls, optionally failing."""

    def __init__(self, name: str = "plugin", *, fail: bool = False, log: list[str] | None = None):
        self.name = name
        self.fail = fail
        self.artifacts: list[SemanticArtifact] = []
        self.log = log if log is not None else []

    async def record(self, artifact: SemanticArtifact) -> None:
        self.log.append(f"{self.name}.record")
        if self.fail:
            raise ValueError(f"{self.name} failed")
        self.artifacts.append(artifact)

    async def flush(self) -> None:
        self.log.append(f"{self.name}.flush")
        if self.fail:
            raise ValueError(f"{self.name} failed")

    async def close(self) -> None:
        self.log.append(f"{self.name}.close")
        if self.fail:
            raise ValueError(f"{self.name} failed")
