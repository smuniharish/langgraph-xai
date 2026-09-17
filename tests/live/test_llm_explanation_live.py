"""Opt-in smoke test for an OpenAI-compatible explanation model."""

from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest

from langgraph_xai.core import (
    Decision,
    DecisionFactor,
    Execution,
    ExecutionContext,
    ExecutionStatus,
    ExplanationContext,
)
from langgraph_xai.explanation import LLMExplanationEngine

pytestmark = pytest.mark.live


@pytest.mark.asyncio
async def test_openai_compatible_llm_returns_grounded_explanation() -> None:
    api_key = os.getenv("EXPLABS_API_KEY")
    if not api_key:
        pytest.skip("EXPLABS_API_KEY is not configured")
    langchain_openai = pytest.importorskip("langchain_openai")
    model = langchain_openai.ChatOpenAI(
        model=os.getenv("EXPLABS_MODEL", "gpt-5.6-luna"),
        base_url=os.getenv("EXPLABS_BASE_URL", "https://api.experientiallabs.ai/v1"),
        api_key=api_key,
        temperature=0,
    )
    context = ExecutionContext(
        application_id="live-evaluation",
        tenant_id="isolated-test",
        graph_id="banking-review",
    )
    execution = Execution(
        context=context,
        status=ExecutionStatus.COMPLETED,
        started_at=datetime.now(UTC),
    )
    decision = Decision(
        context=context,
        decision_type="routing",
        selected_action="HUMAN_REVIEW",
        factors=[DecisionFactor(name="fraud_risk_score", value=0.91)],
    )
    result = await LLMExplanationEngine(
        model,
        enabled=True,
        timeout=60,
    ).explain(
        ExplanationContext(
            execution=execution,
            decision=decision,
            audience="end_user",
        )
    )

    rendered = f"{result.summary} {' '.join(result.reasons)}".lower()
    assert result.summary
    assert result.metadata["validated"] is True
    assert "review" in rendered
    assert "reasoning" not in result.metadata
