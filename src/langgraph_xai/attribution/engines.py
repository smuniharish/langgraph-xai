"""Provider-neutral attribution implementations.

Scores are signed contributions to the selected decision: positive values
support it and negative values oppose it.  Normalized results have an
absolute-score sum of one (or zero when there are no contributions).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from uuid import UUID

from ..core.models import (
    AttributionContribution,
    AttributionResult,
    DecisionFactor,
    Evidence,
    ExplanationContext,
)

Rule = Callable[[DecisionFactor, ExplanationContext], float]


def _sort_key(value: UUID | str) -> str:
    return str(value)


def _normalize(
    contributions: list[AttributionContribution],
) -> list[AttributionContribution]:
    total = sum(abs(item.score) for item in contributions)
    if not total:
        return contributions
    return [item.model_copy(update={"score": item.score / total}) for item in contributions]


def _confidence(contributions: list[AttributionContribution]) -> float | None:
    if not contributions:
        return None
    return min(1.0, sum(abs(item.score) for item in contributions))


class RuleBasedAttribution:
    """Attribute a decision from its explicit factors and configured rules."""

    def __init__(
        self,
        rules: Mapping[str, float | Rule] | None = None,
        *,
        normalize: bool = True,
    ) -> None:
        self.rules = dict(rules or {})
        self.normalize = normalize

    async def attribute(self, context: ExplanationContext) -> AttributionResult:
        factors = sorted(
            context.decision.factors if context.decision else [],
            key=lambda f: f.name,
        )
        contributions = [self._contribution(factor, context) for factor in factors]
        if self.normalize:
            contributions = _normalize(contributions)
        return AttributionResult(
            context=context.execution.context,
            subject_id=(context.decision.id if context.decision else context.execution.id),
            method="rule_based",
            contributions=contributions,
            normalized=self.normalize,
            confidence=_confidence(contributions),
        )

    def _contribution(
        self, factor: DecisionFactor, context: ExplanationContext
    ) -> AttributionContribution:
        rule = self.rules.get(factor.name)
        if callable(rule):
            score = rule(factor, context)
        elif rule is not None:
            score = rule
        elif factor.weight is not None:
            score = factor.weight
        else:
            score = 1.0
        return AttributionContribution(
            factor_id=factor.name,
            factor_type="decision_factor",
            score=float(score),
            label=factor.name,
            evidence_ids=sorted(factor.evidence_ids, key=_sort_key),
            rationale=f"Rule score for factor '{factor.name}'.",
        )


class EvidenceAttribution:
    """Attribute a decision from evidence confidence and quality."""

    def __init__(self, *, normalize: bool = True) -> None:
        self.normalize = normalize

    async def attribute(self, context: ExplanationContext) -> AttributionResult:
        evidence = {item.id: item for item in context.evidence}
        ids = set(context.decision.evidence_ids if context.decision else ())
        for factor in context.decision.factors if context.decision else ():
            ids.update(factor.evidence_ids)
        selected = sorted(
            (item for item in context.evidence if not ids or item.id in ids),
            key=lambda item: _sort_key(item.id),
        )
        contributions = [self._contribution(item) for item in selected]
        if self.normalize:
            contributions = _normalize(contributions)
        return AttributionResult(
            context=context.execution.context,
            subject_id=(context.decision.id if context.decision else context.execution.id),
            method="evidence",
            contributions=contributions,
            normalized=self.normalize,
            confidence=_confidence(contributions),
            metadata={"evidence_count": len(evidence)},
        )

    @staticmethod
    def _contribution(item: Evidence) -> AttributionContribution:
        score = (item.confidence if item.confidence is not None else 1.0) * (
            item.quality if item.quality is not None else 1.0
        )
        return AttributionContribution(
            factor_id=item.id,
            factor_type=str(item.evidence_type),
            score=score,
            label=item.summary or item.content_reference,
            evidence_ids=[item.id],
            rationale="Evidence confidence multiplied by evidence quality.",
        )


class HybridAttribution:
    """Combine rule and evidence scores deterministically."""

    def __init__(
        self,
        rule_based: RuleBasedAttribution | None = None,
        evidence: EvidenceAttribution | None = None,
        *,
        rule_weight: float = 0.5,
        evidence_weight: float = 0.5,
        normalize: bool = True,
    ) -> None:
        if rule_weight < 0 or evidence_weight < 0 or rule_weight + evidence_weight == 0:
            raise ValueError("attribution weights must be non-negative and not both zero")
        self.rule_based = rule_based or RuleBasedAttribution(normalize=False)
        self.evidence = evidence or EvidenceAttribution(normalize=False)
        self.rule_weight = rule_weight
        self.evidence_weight = evidence_weight
        self.normalize = normalize

    async def attribute(self, context: ExplanationContext) -> AttributionResult:
        rules = await self.rule_based.attribute(context)
        evidence = await self.evidence.attribute(context)
        contributions = [
            item.model_copy(update={"score": item.score * self.rule_weight})
            for item in rules.contributions
        ] + [
            item.model_copy(update={"score": item.score * self.evidence_weight})
            for item in evidence.contributions
        ]
        contributions.sort(key=lambda item: (_sort_key(item.factor_id), item.factor_type))
        if self.normalize:
            contributions = _normalize(contributions)
        return AttributionResult(
            context=context.execution.context,
            subject_id=(context.decision.id if context.decision else context.execution.id),
            method="hybrid",
            contributions=contributions,
            normalized=self.normalize,
            confidence=_confidence(contributions),
            metadata={
                "rule_weight": self.rule_weight,
                "evidence_weight": self.evidence_weight,
            },
        )
