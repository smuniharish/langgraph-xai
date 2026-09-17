from datetime import UTC, datetime

import pytest
from langchain_core.runnables import RunnableLambda

from langgraph_xai import XAIRuntime
from langgraph_xai.config import XAIConfig
from langgraph_xai.core import (
    CaptureMode,
    Decision,
    Execution,
    ExecutionContext,
    ExecutionStatus,
    ExplanationContext,
    ExplanationEngine,
    FailureMode,
    ProvenanceStore,
)
from langgraph_xai.explanation import LLMExplanationEngine


def context() -> ExplanationContext:
    execution_context = ExecutionContext(
        application_id="app",
        tenant_id="tenant",
        graph_id="graph",
    )
    execution = Execution(
        context=execution_context,
        status=ExecutionStatus.COMPLETED,
        started_at=datetime.now(UTC),
    )
    decision = Decision(
        context=execution_context,
        decision_type="routing",
        selected_action="review",
    )
    return ExplanationContext(execution=execution, decision=decision)


@pytest.mark.asyncio
async def test_default_runtime_generates_structured_explanation() -> None:
    runtime = XAIRuntime()

    result = await runtime.explain(context())

    assert "review" in result.summary
    assert result.metadata["engine"] == "structured"


class FailingStore:
    async def write(self, item: object) -> None:
        raise OSError("unavailable")

    async def get(self, entity_id: str) -> None:
        return None

    async def parents(self, entity_id: str, *, context: object) -> tuple[()]:
        return ()

    async def children(self, entity_id: str, *, context: object) -> tuple[()]:
        return ()

    async def lineage(self, entity_id: str, *, context: object, max_depth: int = 100) -> tuple[()]:
        return ()

    async def close(self) -> None:
        return None

    async def query(self, query: object):
        if False:
            yield query


@pytest.mark.asyncio
async def test_fail_open_records_provider_failure_without_breaking_run() -> None:
    runtime = XAIRuntime()
    runtime.register(ProvenanceStore, FailingStore())

    run = await runtime.start_run()
    await runtime.finish_run(run)

    assert run.execution.status is ExecutionStatus.COMPLETED
    assert any(isinstance(error, OSError) for error in runtime.errors)


@pytest.mark.asyncio
async def test_fail_closed_surfaces_provider_failure() -> None:
    runtime = XAIRuntime(config=XAIConfig(failure_mode=FailureMode.FAIL_CLOSED))
    runtime.register(ProvenanceStore, FailingStore())

    with pytest.raises(RuntimeError, match="instrumentation operation failed"):
        await runtime.start_run()


@pytest.mark.asyncio
async def test_selective_state_capture_records_only_configured_fields() -> None:
    runtime = XAIRuntime(
        config=XAIConfig(
            capture_state=CaptureMode.SELECTIVE,
            capture_fields=frozenset({"safe"}),
        )
    )
    run = await runtime.start_run()

    transition = await runtime.record_state_delta(
        "node",
        {"safe": 1, "private": "before"},
        {"safe": 2, "private": "after"},
        run=run,
    )

    assert transition is not None
    assert [change.path for change in transition.changes] == ["safe"]


@pytest.mark.asyncio
async def test_registered_llm_engine_still_requires_runtime_opt_in() -> None:
    runtime = XAIRuntime()
    runtime.register(
        ExplanationEngine,
        LLMExplanationEngine(
            RunnableLambda(lambda _: '{"summary":"ok"}'),
            enabled=True,
        ),
    )

    with pytest.raises(RuntimeError, match="disabled in XAIConfig"):
        await runtime.explain(context())
