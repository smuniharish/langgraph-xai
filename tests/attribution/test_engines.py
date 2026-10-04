import math
from typing import cast

import pytest
from hypothesis import given
from hypothesis import strategies as st

from langgraph_xai import (
    Decision,
    DecisionFactor,
    Evidence,
    EvidenceAttribution,
    ExplanationContext,
    HybridAttribution,
    RuleBasedAttribution,
)
from tests.helpers import context, execution, explanation_context


async def test_rule_scores_follow_callable_constant_weight_then_default_precedence() -> None:
    ctx = context()
    decision = Decision(
        context=ctx,
        decision_type="routing",
        selected_action="review",
        factors=[
            DecisionFactor(name="by_callable", value=2),
            DecisionFactor(name="by_constant", weight=9),
            DecisionFactor(name="by_weight", weight=-0.5),
            DecisionFactor(name="by_default"),
        ],
    )
    engine = RuleBasedAttribution(
        {
            "by_callable": lambda factor, _: 2 * float(cast("float", factor.value)),
            "by_constant": 0.25,
        },
        normalize=False,
    )

    result = await engine.attribute(ExplanationContext(execution=execution(ctx), decision=decision))

    assert [(item.label, item.score) for item in result.contributions] == [
        ("by_callable", 4.0),
        ("by_constant", 0.25),
        ("by_default", 1.0),
        ("by_weight", -0.5),
    ]
    assert result.method == "rule_based"
    assert result.subject_id == decision.id
    assert result.confidence is None
    assert not result.normalized


async def test_rule_attribution_normalizes_and_handles_missing_decision() -> None:
    normalized = await RuleBasedAttribution().attribute(explanation_context())
    record = execution()
    empty = await RuleBasedAttribution().attribute(ExplanationContext(execution=record))

    assert math.fsum(abs(item.score) for item in normalized.contributions) == pytest.approx(1)
    assert empty.contributions == []
    assert empty.subject_id == record.id


@pytest.mark.parametrize("bad", [float("nan"), float("inf")])
async def test_non_finite_rule_scores_are_rejected(bad: float) -> None:
    engine = RuleBasedAttribution({"risk": lambda *_: bad})

    with pytest.raises(ValueError, match="factor 'risk'"):
        await engine.attribute(explanation_context())


async def test_evidence_attribution_scores_referenced_evidence_and_reports_mean_strength() -> None:
    context_ = explanation_context()

    result = await EvidenceAttribution(normalize=False).attribute(context_)

    scores = {item.label: item.score for item in result.contributions}
    assert scores == {
        "Fraud detector scored the transaction 0.91.": pytest.approx(0.45),
        "Policy requires review above 0.8.": pytest.approx(1.0),
    }
    assert result.confidence == pytest.approx(0.725)
    assert result.metadata == {"evidence_count": 2}


async def test_evidence_attribution_falls_back_to_all_evidence_and_deduplicates() -> None:
    ctx = context()
    item = Evidence(evidence_type="rule", context=ctx, summary="only")
    decision = Decision(context=ctx, decision_type="routing", selected_action="x")
    context_ = ExplanationContext(
        execution=execution(ctx), decision=decision, evidence=[item, item]
    )

    result = await EvidenceAttribution().attribute(context_)

    assert len(result.contributions) == 1
    assert result.contributions[0].score == 1.0
    assert result.confidence == 1.0


async def test_evidence_attribution_without_evidence_has_no_confidence() -> None:
    result = await EvidenceAttribution().attribute(ExplanationContext(execution=execution()))

    assert result.contributions == []
    assert result.confidence is None


async def test_hybrid_combines_weighted_sources_deterministically() -> None:
    result = await HybridAttribution(rule_weight=0.75, evidence_weight=0.25).attribute(
        explanation_context()
    )
    raw = await HybridAttribution(normalize=False).attribute(explanation_context())

    assert result.method == "hybrid"
    assert result.normalized
    assert not raw.normalized
    assert math.fsum(item.score for item in raw.contributions) == pytest.approx(0.5 + 0.5)
    assert result.metadata == {"rule_weight": 0.75, "evidence_weight": 0.25}
    assert result.confidence == pytest.approx(0.725)
    shares = {
        kind: math.fsum(
            item.score
            for item in result.contributions
            if (item.factor_type == "decision_factor") == (kind == "factors")
        )
        for kind in ("factors", "evidence")
    }
    assert shares == {"factors": pytest.approx(0.75), "evidence": pytest.approx(0.25)}
    keys = [(str(item.factor_id), item.factor_type) for item in result.contributions]
    assert keys == sorted(keys)


@pytest.mark.parametrize(
    "weights",
    [(-1.0, 1.0), (1.0, -0.1), (0.0, 0.0), (float("nan"), 1.0), (1.0, float("inf"))],
)
def test_hybrid_rejects_invalid_weights(weights: tuple[float, float]) -> None:
    with pytest.raises(ValueError, match="attribution weights"):
        HybridAttribution(rule_weight=weights[0], evidence_weight=weights[1])


finite = st.floats(min_value=-1e6, max_value=1e6, allow_nan=False)
unit = st.floats(min_value=0, max_value=1)
factor_lists = st.lists(
    st.builds(
        DecisionFactor,
        name=st.text(alphabet="abcdefghij", min_size=1, max_size=6),
        weight=st.none() | finite,
    ),
    max_size=8,
    unique_by=lambda factor: factor.name,
)


def _context(factors: list[DecisionFactor], strengths: list[tuple[float, float]]):
    ctx = context()
    evidence = [
        Evidence(evidence_type="rule", context=ctx, confidence=confidence, quality=quality)
        for confidence, quality in strengths
    ]
    decision = Decision(context=ctx, decision_type="routing", selected_action="x", factors=factors)
    return ExplanationContext(execution=execution(ctx), decision=decision, evidence=evidence)


@given(factors=factor_lists, strengths=st.lists(st.tuples(unit, unit), max_size=6))
async def test_normalized_contributions_have_unit_absolute_mass(factors, strengths) -> None:
    result = await HybridAttribution().attribute(_context(factors, strengths))

    mass = math.fsum(abs(item.score) for item in result.contributions)
    assert mass == pytest.approx(1.0) or mass == 0.0
    assert all(math.isfinite(item.score) for item in result.contributions)


@given(factors=factor_lists, strengths=st.lists(st.tuples(unit, unit), max_size=6))
async def test_attribution_is_independent_of_input_order(factors, strengths) -> None:
    forward = _context(factors, strengths)
    assert forward.decision is not None
    backward = forward.model_copy(
        update={
            "evidence": list(reversed(forward.evidence)),
            "decision": forward.decision.model_copy(update={"factors": list(reversed(factors))}),
        }
    )

    first = await HybridAttribution().attribute(forward)
    second = await HybridAttribution().attribute(backward)

    assert [(c.factor_id, c.score) for c in first.contributions] == [
        (c.factor_id, c.score) for c in second.contributions
    ]


@given(
    factors=factor_lists,
    strengths=st.lists(st.tuples(unit, unit), max_size=6),
    scale=st.floats(min_value=0.01, max_value=100),
)
async def test_scaling_both_weights_does_not_change_normalized_scores(
    factors, strengths, scale
) -> None:
    ctx = _context(factors, strengths)

    base = await HybridAttribution(rule_weight=0.3, evidence_weight=0.7).attribute(ctx)
    scaled = await HybridAttribution(
        rule_weight=0.3 * scale, evidence_weight=0.7 * scale
    ).attribute(ctx)

    assert [c.score for c in scaled.contributions] == pytest.approx(
        [c.score for c in base.contributions], abs=1e-9
    )


@given(
    factors=factor_lists,
    strengths=st.lists(st.tuples(unit, unit), max_size=6),
    rule_weight=st.floats(min_value=0.01, max_value=10),
    evidence_weight=st.floats(min_value=0.01, max_value=10),
)
async def test_hybrid_weights_are_the_shares_of_each_source(
    factors, strengths, rule_weight, evidence_weight
) -> None:
    result = await HybridAttribution(
        rule_weight=rule_weight, evidence_weight=evidence_weight
    ).attribute(_context(factors, strengths))

    def mass(factor_type_is_rule: bool) -> float:
        return math.fsum(
            abs(item.score)
            for item in result.contributions
            if (item.factor_type == "decision_factor") == factor_type_is_rule
        )

    rules, evidence = mass(True), mass(False)
    if rules and evidence:
        assert rules / (rules + evidence) == pytest.approx(
            rule_weight / (rule_weight + evidence_weight)
        )
    else:
        assert rules + evidence == pytest.approx(1.0) or rules + evidence == 0.0


@given(strengths=st.lists(st.tuples(unit, unit), min_size=1, max_size=6))
async def test_attribution_confidence_is_mean_evidence_strength(strengths) -> None:
    result = await EvidenceAttribution().attribute(_context([], strengths))

    expected = math.fsum(c * q for c, q in strengths) / len(strengths)
    assert result.confidence is not None
    assert result.confidence == pytest.approx(expected)
    assert 0 <= result.confidence <= 1
