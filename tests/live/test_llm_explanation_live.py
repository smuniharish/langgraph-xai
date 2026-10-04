"""Opt-in smoke test for an OpenAI-compatible explanation model.

Set ``XAI_TEST_LLM_API_KEY`` (and optionally ``XAI_TEST_LLM_MODEL`` and
``XAI_TEST_LLM_BASE_URL``) to run it. A dedicated variable is used so that a
globally configured ``OPENAI_API_KEY`` never triggers paid calls in a normal
test run.
"""

from __future__ import annotations

import os

import pytest

from langgraph_xai import DecisionFactor, LLMExplanationEngine, XAIConfig, XAIRuntime
from langgraph_xai.core import ExplanationEngine

pytestmark = pytest.mark.live


async def test_llm_explanation_is_grounded_in_the_recorded_decision() -> None:
    api_key = os.getenv("XAI_TEST_LLM_API_KEY")
    if not api_key:
        pytest.skip("XAI_TEST_LLM_API_KEY is not configured")
    langchain_openai = pytest.importorskip("langchain_openai")
    openai = pytest.importorskip("openai")
    # A client owned by the test is closed before its event loop ends; the default
    # one is cached per process and would leave its connections open.
    async with openai.DefaultAsyncHttpxClient() as http_client:
        model = langchain_openai.ChatOpenAI(
            model=os.getenv("XAI_TEST_LLM_MODEL", "gpt-4o-mini"),
            base_url=os.getenv("XAI_TEST_LLM_BASE_URL"),
            api_key=api_key,
            http_async_client=http_client,
        )
        xai = XAIRuntime(config=XAIConfig(llm_explanation_enabled=True))
        xai.register(ExplanationEngine, LLMExplanationEngine(model, enabled=True, timeout=60))
        run = await xai.start_run()
        decision = await xai.record_decision(
            "HUMAN_REVIEW",
            decision_type="routing",
            factors=[DecisionFactor(name="fraud_risk_score", value=0.91)],
            run=run,
        )

        explanation = await xai.explain_decision(decision, audience="end_user", run=run)

    rendered = f"{explanation.summary} {' '.join(explanation.reasons)}".lower()
    assert explanation.metadata == {"engine": "llm", "validated": True}
    assert "review" in rendered
