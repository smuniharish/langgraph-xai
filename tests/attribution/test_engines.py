from datetime import UTC, datetime

import pytest

from langgraph_xai.attribution import (
    EvidenceAttribution,
    HybridAttribution,
    RuleBasedAttribution,
)
from langgraph_xai.core import (
    Decision,
    DecisionFactor,
    Evidence,
    EvidenceType,
    Execution,
    ExecutionContext,
    ExecutionStatus,
    ExplanationContext,
)


def explanation_context() -> ExplanationContext:
    context = ExecutionContext(application_id="app", tenant_id="tenant", graph_id="graph")
    evidence = Evidence(
        context=context,
        evidence_type=EvidenceType.TOOL_RESULT,
        summary="Fraud score",
        confidence=0.8,
        quality=0.5,
    )
    execution = Execution(
        context=context,
        status=ExecutionStatus.COMPLETED,
        started_at=datetime.now(UTC),
    )
    decision = Decision(
        context=context,
        decision_type="routing",
        selected_action="review",
        evidence_ids=[evidence.id],
        factors=[
            DecisionFactor(name="risk_score", value=0.91, weight=3, evidence_ids=[evidence.id]),
            DecisionFactor(name="history", value="new", weight=1),
        ],
    )
    return ExplanationContext(execution=execution, decision=decision, evidence=[evidence])


@pytest.mark.asyncio
async def test_rule_attribution_is_deterministic_and_normalized() -> None:
    result = await RuleBasedAttribution().attribute(explanation_context())

    assert [item.label for item in result.contributions] == ["history", "risk_score"]
    assert sum(abs(item.score) for item in result.contributions) == pytest.approx(1)


@pytest.mark.asyncio
async def test_evidence_attribution_uses_confidence_and_quality() -> None:
    result = await EvidenceAttribution(normalize=False).attribute(explanation_context())

    assert result.contributions[0].score == pytest.approx(0.4)


@pytest.mark.asyncio
async def test_hybrid_requires_nonzero_weights() -> None:
    with pytest.raises(ValueError):
        HybridAttribution(rule_weight=0, evidence_weight=0)
