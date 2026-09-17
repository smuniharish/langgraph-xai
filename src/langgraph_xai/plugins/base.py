"""Plugin contracts for artifacts outside the core sink protocols."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from langgraph_xai.core.models import (
    AttributionResult,
    Decision,
    Evidence,
    Explanation,
    MemoryReference,
    PolicyDecision,
)

type SemanticArtifact = (
    Evidence | Decision | AttributionResult | Explanation | PolicyDecision | MemoryReference
)


@runtime_checkable
class XAIPlugin(Protocol):
    """An optional, instance-scoped consumer of explicit semantic artifacts."""

    async def record(self, artifact: SemanticArtifact) -> None: ...

    async def flush(self) -> None: ...

    async def close(self) -> None: ...
