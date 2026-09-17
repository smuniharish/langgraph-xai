import asyncio
import json
from datetime import UTC, datetime

import pytest
from langchain_core.runnables import RunnableLambda

from langgraph_xai.core import (
    Decision,
    DecisionFactor,
    Execution,
    ExecutionContext,
    ExecutionStatus,
    ExplanationContext,
    PolicyAction,
    PolicyDecision,
)
from langgraph_xai.explanation import LLMExplanationEngine, StructuredExplanationEngine


def explanation_context(*, deny_reasons: bool = False) -> ExplanationContext:
    context = ExecutionContext(application_id="app", tenant_id="tenant", graph_id="graph")
    execution = Execution(
        context=context,
        status=ExecutionStatus.COMPLETED,
        started_at=datetime.now(UTC),
    )
    decision = Decision(
        context=context,
        decision_type="routing",
        selected_action="human_review",
        factors=[DecisionFactor(name="risk_score", value=0.91)],
    )
    policies = []
    if deny_reasons:
        policies.append(
            PolicyDecision(
                context=context,
                policy_id="customer",
                action=PolicyAction.EXPOSE,
                allowed=True,
                denied_fields={"reasons"},
            )
        )
    return ExplanationContext(
        execution=execution,
        decision=decision,
        policies=policies,
        audience="end_user",
    )


@pytest.mark.asyncio
async def test_structured_explanation_applies_exposure_policy() -> None:
    result = await StructuredExplanationEngine().explain(explanation_context(deny_reasons=True))

    assert result.reasons == ["No decision details were captured."]
    assert "Decision reasons are withheld by policy." in result.disclosure


@pytest.mark.asyncio
async def test_llm_explanation_is_disabled_by_default() -> None:
    engine = LLMExplanationEngine(RunnableLambda(lambda _: "{}"))

    with pytest.raises(RuntimeError, match="disabled"):
        await engine.explain(explanation_context())


@pytest.mark.asyncio
async def test_llm_explanation_accepts_only_structured_output() -> None:
    payload = json.dumps(
        {
            "summary": "The risk threshold was exceeded.",
            "reasons": ["The captured risk score was above the review threshold."],
            "disclosure": ["Customer-safe fields only."],
        }
    )
    engine = LLMExplanationEngine(
        RunnableLambda(lambda _: payload),
        enabled=True,
    )

    result = await engine.explain(explanation_context())

    assert result.summary == "The risk threshold was exceeded."
    assert result.metadata["validated"] is True


@pytest.mark.asyncio
async def test_llm_explanation_normalizes_scalar_list_fields() -> None:
    """Some providers return a single sentence instead of a JSON array for
    list-typed fields. xgraph should tolerate that formatting slip without
    weakening the underlying schema (unknown fields are still rejected)."""
    payload = json.dumps(
        {
            "summary": "The risk threshold was exceeded.",
            "reasons": "The captured risk score was above the review threshold.",
            "disclosure": "Customer-safe fields only.",
        }
    )
    engine = LLMExplanationEngine(
        RunnableLambda(lambda _: payload),
        enabled=True,
    )

    result = await engine.explain(explanation_context())

    assert result.reasons == ["The captured risk score was above the review threshold."]
    assert "Customer-safe fields only." in result.disclosure


@pytest.mark.asyncio
async def test_llm_explanation_still_rejects_unknown_fields() -> None:
    payload = json.dumps(
        {
            "summary": "The risk threshold was exceeded.",
            "reasons": ["ok"],
            "disclosure": [],
            "hidden_reasoning": "this must never be accepted",
        }
    )
    engine = LLMExplanationEngine(
        RunnableLambda(lambda _: payload),
        enabled=True,
    )

    with pytest.raises(ValueError, match="schema validation"):
        await engine.explain(explanation_context())


@pytest.mark.asyncio
async def test_llm_explanation_timeout_is_visible() -> None:
    async def delayed(_: str) -> str:
        await asyncio.sleep(0.05)
        return "{}"

    engine = LLMExplanationEngine(
        RunnableLambda(delayed),
        enabled=True,
        timeout=0.001,
    )

    with pytest.raises(TimeoutError):
        await engine.explain(explanation_context())
