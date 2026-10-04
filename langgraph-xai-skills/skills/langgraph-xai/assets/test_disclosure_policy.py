"""Disclosure-policy tests to copy into your project's test suite.

Replace ``CustomerSafePolicy`` with your application's ``PolicyProvider``, and
adjust the expectations to what each audience may see. The tests record one
decision, explain it to each audience, and check both what an explanation
contains and what it must never contain.

The tests run with plain pytest; no async plugin is needed.
"""

from __future__ import annotations

import asyncio

import pytest

from langgraph_xai import (
    Audience,
    DecisionFactor,
    DecisionType,
    EvidenceType,
    Explanation,
    ExplanationContext,
    PolicyAction,
    PolicyDecision,
    PolicyProvider,
    XAIInstrumentationError,
    XAIRuntime,
)

# A value that must never reach an end user. Pick one that cannot appear by accident.
SECRET_SCORE = 0.9173


class CustomerSafePolicy:
    """End users see the outcome and reasons; other audiences see everything."""

    async def evaluate(self, context: ExplanationContext, action: PolicyAction) -> PolicyDecision:
        end_user = context.audience == Audience.END_USER
        return PolicyDecision(
            context=context.execution.context,
            policy_id="customer-safe",
            action=action,
            allowed=True,
            audience=context.audience,
            denied_fields={"contributing_factors", "supporting_evidence"} if end_user else set(),
            reason="Customers receive the outcome and reasons only." if end_user else None,
        )


class UnavailablePolicy:
    """A policy service that is down."""

    async def evaluate(self, context: ExplanationContext, action: PolicyAction) -> PolicyDecision:
        raise ConnectionError("policy service unavailable")


def explain(audience: Audience | str, policy: PolicyProvider) -> Explanation:
    """Record one decision with evidence and a scored factor, then explain it."""

    async def scenario() -> Explanation:
        xai = XAIRuntime()
        xai.register(PolicyProvider, policy)
        run = await xai.start_run()
        evidence = await xai.record_evidence(
            EvidenceType.TOOL_RESULT,
            summary=f"Fraud model scored the transaction {SECRET_SCORE}.",
            confidence=0.97,
            run=run,
        )
        decision = await xai.record_decision(
            "HUMAN_REVIEW",
            decision_type=DecisionType.ROUTING,
            candidate_actions=["AUTO_APPROVE", "HUMAN_REVIEW"],
            evidence_ids=[evidence.id],
            factors=[
                DecisionFactor(
                    name="fraud_risk_score", value=SECRET_SCORE, evidence_ids=[evidence.id]
                )
            ],
            run=run,
        )
        await xai.finish_run(run)
        try:
            return await xai.explain_decision(decision, audience=audience, run=run)
        finally:
            await xai.close()

    return asyncio.run(scenario())


@pytest.mark.parametrize("audience", [Audience.DEVELOPER, Audience.AUDITOR, Audience.BUSINESS])
def test_internal_audiences_see_the_basis_of_the_decision(audience: Audience) -> None:
    explanation = explain(audience, CustomerSafePolicy())

    assert explanation.contributing_factors
    assert explanation.supporting_evidence
    assert explanation.disclosure == []


def test_end_users_see_the_outcome_but_never_the_score() -> None:
    explanation = explain(Audience.END_USER, CustomerSafePolicy())

    assert explanation.summary
    assert explanation.contributing_factors == []
    assert explanation.supporting_evidence == []
    # Search the whole serialized explanation, so a leak through any field is caught.
    # The generated timestamp is excluded: its fractional seconds can hold any digits.
    assert str(SECRET_SCORE) not in explanation.model_dump_json(exclude={"timestamp"})
    assert "Contributing factors are withheld by policy." in explanation.disclosure
    assert "Supporting evidence is withheld by policy." in explanation.disclosure


def test_a_failing_policy_never_yields_an_unfiltered_explanation() -> None:
    with pytest.raises(XAIInstrumentationError, match="exposure policy evaluation failed"):
        explain(Audience.END_USER, UnavailablePolicy())
