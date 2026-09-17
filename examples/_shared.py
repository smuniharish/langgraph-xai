"""Shared local helpers for executable examples."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from langgraph_xai import (
    Decision,
    DecisionFactor,
    Execution,
    ExecutionStatus,
    ExplanationContext,
    XAIRuntime,
)


class DemoState(TypedDict, total=False):
    query: str
    answer: str
    risk_score: float
    attempts: int
    approved: bool


def compiled_graph(node, *, name: str = "work"):
    builder = StateGraph(DemoState)
    builder.add_node(name, node)
    builder.add_edge(START, name)
    builder.add_edge(name, END)
    return builder.compile()


async def explain_result(
    runtime: XAIRuntime,
    action: str,
    *factors: DecisionFactor,
) -> str:
    context = runtime.context_from_config()
    execution = Execution(
        context=context,
        status=ExecutionStatus.COMPLETED,
        started_at=datetime.now(UTC),
        ended_at=datetime.now(UTC),
    )
    decision = Decision(
        context=context,
        decision_type="routing",
        selected_action=action,
        factors=list(factors),
    )
    explanation = await runtime.explain(
        ExplanationContext(
            execution=execution,
            decision=decision,
            audience="end_user",
        )
    )
    return explanation.summary
