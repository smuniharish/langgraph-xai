"""Deterministic, provider-neutral attribution engines.

Scores are signed contributions to the selected decision: positive values
support it and negative values oppose it. Normalized results have an
absolute-score sum of one (or zero when every score is zero). Every engine is
deterministic: the same context always yields the same contributions in the
same order.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from statistics import fmean
from typing import TYPE_CHECKING

from ..core.models import (
    AttributionContribution,
    AttributionResult,
    DecisionFactor,
    Evidence,
    ExplanationContext,
)

if TYPE_CHECKING:
    from uuid import UUID

type Rule = Callable[[DecisionFactor, ExplanationContext], float]


def _normalize(contributions: list[AttributionContribution]) -> list[AttributionContribution]:
    total = math.fsum(abs(item.score) for item in contributions)
    if not total:
        return contributions
    return [item.model_copy(update={"score": item.score / total}) for item in contributions]


def _subject(context: ExplanationContext) -> UUID:
    return context.decision.id if context.decision else context.execution.id


class RuleBasedAttribution:
    """Attribute a decision from its explicit `DecisionFactor`s.

    Each factor is scored, in order of precedence, by a callable rule
    ``(factor, context) -> float``, a constant rule, the factor's own
    ``weight``, or ``1.0``. Rule-based scores carry no statistical confidence,
    so ``AttributionResult.confidence`` is ``None``.
    """

    def __init__(
        self,
        rules: Mapping[str, float | Rule] | None = None,
        *,
        normalize: bool = True,
    ) -> None:
        self.rules = dict(rules or {})
        self.normalize = normalize

    async def attribute(self, context: ExplanationContext) -> AttributionResult:
        """Score every factor of ``context.decision``, sorted by factor name."""
        factors = sorted(
            context.decision.factors if context.decision else [],
            key=lambda factor: factor.name,
        )
        contributions = [self._contribution(factor, context) for factor in factors]
        if self.normalize:
            contributions = _normalize(contributions)
        return AttributionResult(
            context=context.execution.context,
            subject_id=_subject(context),
            method="rule_based",
            contributions=contributions,
            normalized=self.normalize,
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
        score = float(score)
        if not math.isfinite(score):
            raise ValueError(f"attribution rule for factor {factor.name!r} returned {score}")
        return AttributionContribution(
            factor_id=factor.name,
            factor_type="decision_factor",
            score=score,
            label=factor.name,
            evidence_ids=sorted(factor.evidence_ids, key=str),
            rationale=f"Rule score for factor '{factor.name}'.",
        )


class EvidenceAttribution:
    """Attribute a decision from the strength of its supporting evidence.

    Each evidence item scores ``confidence * quality`` (a missing value counts
    as ``1.0``). Only evidence referenced by the decision or its factors is
    considered; when the decision references none, all evidence in the context
    is. ``AttributionResult.confidence`` is the mean evidence strength, or
    ``None`` when no evidence was considered.
    """

    def __init__(self, *, normalize: bool = True) -> None:
        self.normalize = normalize

    async def attribute(self, context: ExplanationContext) -> AttributionResult:
        """Score the evidence supporting ``context.decision``, sorted by evidence ID."""
        referenced: set[UUID] = set()
        if context.decision is not None:
            referenced.update(context.decision.evidence_ids)
            for factor in context.decision.factors:
                referenced.update(factor.evidence_ids)
        unique = {item.id: item for item in context.evidence}
        considered = sorted(
            (item for item in unique.values() if not referenced or item.id in referenced),
            key=lambda item: str(item.id),
        )
        contributions = [self._contribution(item) for item in considered]
        confidence = fmean(item.score for item in contributions) if contributions else None
        if self.normalize:
            contributions = _normalize(contributions)
        return AttributionResult(
            context=context.execution.context,
            subject_id=_subject(context),
            method="evidence",
            contributions=contributions,
            normalized=self.normalize,
            confidence=confidence,
            metadata={"evidence_count": len(considered)},
        )

    @staticmethod
    def _contribution(item: Evidence) -> AttributionContribution:
        confidence = 1.0 if item.confidence is None else item.confidence
        quality = 1.0 if item.quality is None else item.quality
        return AttributionContribution(
            factor_id=item.id,
            factor_type=str(item.evidence_type),
            score=confidence * quality,
            label=item.summary or item.content_reference,
            evidence_ids=[item.id],
            rationale="Evidence confidence multiplied by evidence quality.",
        )


class HybridAttribution:
    """Combine decision factors and evidence, each with a fixed share (the default engine).

    Each family's scores are first normalized to an absolute sum of one, then
    multiplied by ``rule_weight`` (decision factors) or ``evidence_weight``
    (evidence), merged, sorted by ``(factor_id, factor_type)``, and normalized
    again. When both families are present, the weights are therefore the shares
    of attribution they receive, however many factors or evidence items each
    has; when one is empty, the other receives everything.
    ``AttributionResult.confidence`` is the evidence engine's mean evidence
    strength.
    """

    def __init__(
        self,
        rule_based: RuleBasedAttribution | None = None,
        evidence: EvidenceAttribution | None = None,
        *,
        rule_weight: float = 0.5,
        evidence_weight: float = 0.5,
        normalize: bool = True,
    ) -> None:
        weights = (rule_weight, evidence_weight)
        if not all(math.isfinite(weight) and weight >= 0 for weight in weights) or not any(weights):
            raise ValueError("attribution weights must be finite, non-negative, and not both zero")
        self.rule_based = rule_based or RuleBasedAttribution(normalize=False)
        self.evidence = evidence or EvidenceAttribution(normalize=False)
        self.rule_weight = rule_weight
        self.evidence_weight = evidence_weight
        self.normalize = normalize

    async def attribute(self, context: ExplanationContext) -> AttributionResult:
        """Return the weighted combination of rule and evidence contributions."""
        rules = await self.rule_based.attribute(context)
        evidence = await self.evidence.attribute(context)
        contributions = [
            item.model_copy(update={"score": item.score * self.rule_weight})
            for item in _normalize(rules.contributions)
        ] + [
            item.model_copy(update={"score": item.score * self.evidence_weight})
            for item in _normalize(evidence.contributions)
        ]
        contributions.sort(key=lambda item: (str(item.factor_id), item.factor_type))
        if self.normalize:
            contributions = _normalize(contributions)
        return AttributionResult(
            context=context.execution.context,
            subject_id=_subject(context),
            method="hybrid",
            contributions=contributions,
            normalized=self.normalize,
            confidence=evidence.confidence,
            metadata={
                "rule_weight": self.rule_weight,
                "evidence_weight": self.evidence_weight,
            },
        )
