from datetime import UTC, datetime

import pytest

from langgraph_xai.core import (
    Execution,
    ExecutionContext,
    ExecutionStatus,
    ExplanationContext,
    PolicyAction,
)
from langgraph_xai.policy import DefaultPolicyProvider, sanitize_mapping


def test_obvious_credentials_are_not_captured() -> None:
    captured = sanitize_mapping(
        {
            "authorization": "Bearer private",
            "nested": {"api_key": "private", "safe": "visible"},
        }
    )

    assert captured["authorization"] == "[not captured]"
    assert captured["nested"] == {"api_key": "[not captured]", "safe": "visible"}


@pytest.mark.asyncio
async def test_default_exposure_withholds_private_memory_and_raw_content() -> None:
    context = ExecutionContext(application_id="app", tenant_id="tenant", graph_id="graph")
    execution = Execution(
        context=context,
        status=ExecutionStatus.COMPLETED,
        started_at=datetime.now(UTC),
    )

    decision = await DefaultPolicyProvider().evaluate(
        ExplanationContext(execution=execution),
        PolicyAction.EXPOSE,
    )

    assert decision.allowed
    assert {"private_memory", "raw_content"}.issubset(decision.denied_fields)
