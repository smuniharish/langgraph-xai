"""Create policy-minimized evidence records."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..core.models import Evidence, EvidenceType, ExecutionContext
from ..policy import sanitize_mapping

if TYPE_CHECKING:
    from collections.abc import Mapping


class EvidenceService:
    def __init__(self, context: ExecutionContext) -> None:
        self._context = context

    def create(
        self,
        evidence_type: EvidenceType | str,
        *,
        summary: str | None = None,
        content_reference: str | None = None,
        confidence: float | None = None,
        metadata: Mapping[object, object] | None = None,
    ) -> Evidence:
        return Evidence(
            context=self._context,
            evidence_type=evidence_type,
            summary=summary,
            content_reference=content_reference,
            confidence=confidence,
            metadata=sanitize_mapping(metadata or {}),
        )
