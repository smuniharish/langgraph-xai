"""Produce a complete, real Explanation JSON payload for documentation purposes.

Run with:

    uv run python examples/full_explanation_output.py

This mirrors ``banking_transaction_review.py`` but records explicit evidence,
runs attribution, and prints the full canonical ``Explanation`` model as JSON
so its exact shape can be quoted in the documentation.
"""

import asyncio
from datetime import UTC, datetime

from _shared import compiled_graph

from langgraph_xai import (
    Decision,
    DecisionFactor,
    Evidence,
    EvidenceType,
    Execution,
    ExecutionStatus,
    ExplanationContext,
    XAIRuntime,
)


async def main() -> None:
    runtime = XAIRuntime(graph_id="banking-review")
    graph = runtime.instrument(
        compiled_graph(lambda _: {"risk_score": 0.91, "answer": "HUMAN_REVIEW"})
    )
    await graph.ainvoke({"risk_score": 0.0})

    context = runtime.context_from_config()

    fraud_score_evidence = Evidence(
        context=context,
        evidence_type=EvidenceType.TOOL_RESULT,
        summary="Fraud detector scored the transaction 0.91 (high risk).",
        content_reference="fraud-detector://run/8841/score",
        confidence=0.97,
    )
    threshold_evidence = Evidence(
        context=context,
        evidence_type=EvidenceType.POLICY,
        summary="Bank policy requires human review above a 0.80 risk threshold.",
        content_reference="policy://fraud/review-threshold",
        confidence=1.0,
    )

    execution = Execution(
        context=context,
        status=ExecutionStatus.COMPLETED,
        started_at=datetime.now(UTC),
        ended_at=datetime.now(UTC),
    )
    decision = Decision(
        context=context,
        decision_type="routing",
        selected_action="HUMAN_REVIEW",
        candidate_actions=["AUTO_APPROVE", "HUMAN_REVIEW", "AUTO_DECLINE"],
        evidence_ids=[fraud_score_evidence.id, threshold_evidence.id],
        factors=[
            DecisionFactor(
                name="fraud_risk_score",
                value=0.91,
                weight=0.8,
                evidence_ids=[fraud_score_evidence.id],
            ),
            DecisionFactor(
                name="review_threshold",
                value=0.8,
                weight=0.2,
                evidence_ids=[threshold_evidence.id],
            ),
        ],
    )

    explanation = await runtime.explain(
        ExplanationContext(
            execution=execution,
            decision=decision,
            evidence=[fraud_score_evidence, threshold_evidence],
            audience="end_user",
        )
    )

    print(explanation.model_dump_json(indent=2, exclude={"id", "created_at"}))


if __name__ == "__main__":
    asyncio.run(main())
