"""Plugin contract for semantic artifacts recorded outside the core sinks."""

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
    """An instance-scoped consumer of semantic artifacts.

    Evidence, decisions, memory references, and artifacts passed to
    `XAIRuntime.record_artifact` are delivered to every registered plugin as they
    are recorded. Implement this to persist them, forward them to a review
    queue, or index them for search.
    """

    async def record(self, artifact: SemanticArtifact) -> None:
        """Receive one semantic artifact."""
        ...

    async def flush(self) -> None:
        """Deliver any buffered artifacts."""
        ...

    async def close(self) -> None:
        """Flush and release resources."""
        ...
