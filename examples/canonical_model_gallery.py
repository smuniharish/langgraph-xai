"""Print a real JSON example of every canonical model, all from one recorded run.

The concept pages of the documentation quote this script's output: an `Execution`,
`Evidence`, a `Decision`, a provenance lineage, an `AttributionResult`, a
`PolicyDecision`, and an `Explanation`. Everything is produced through the public
recording API rather than built by hand.

Run with:

    uv run python examples/canonical_model_gallery.py
"""

import asyncio

from langgraph_xai import (
    Audience,
    DecisionFactor,
    DecisionType,
    EvidenceType,
    ExplanationContext,
    PolicyAction,
    PolicyProvider,
    ProvenanceStore,
    ToolStatus,
    XAIRuntime,
)

CONTEXT_FIELDS = {"context"}


def banner(title: str) -> None:
    print(f"\n========== {title} ==========")


async def main() -> None:
    xai = XAIRuntime(application_id="payments", tenant_id="acme-bank", graph_id="fraud-review")
    run = await xai.start_run({"metadata": {"trace_id": "trace-8841"}})

    await xai.record_state_delta(
        "score_transaction", {"risk_score": 0.0}, {"risk_score": 0.91}, run=run
    )
    await xai.record_tool(
        "fraud_detector",
        status=ToolStatus.SUCCEEDED,
        latency_ms=42.5,
        output_reference="fraud-detector://scores/txn-8841",
        run=run,
    )
    score = await xai.record_evidence(
        EvidenceType.TOOL_RESULT,
        summary="Fraud detector scored the transaction 0.91 (high risk).",
        content_reference="fraud-detector://scores/txn-8841",
        confidence=0.97,
        quality=0.9,
        run=run,
    )
    threshold = await xai.record_evidence(
        EvidenceType.POLICY,
        summary="Bank policy requires human review above a 0.80 risk score.",
        content_reference="policy://fraud/review-threshold",
        confidence=1.0,
        run=run,
    )
    decision = await xai.record_decision(
        "HUMAN_REVIEW",
        decision_type=DecisionType.ROUTING,
        candidate_actions=["AUTO_APPROVE", "HUMAN_REVIEW", "AUTO_DECLINE"],
        evidence_ids=[score.id, threshold.id],
        factors=[
            DecisionFactor(
                name="fraud_risk_score", value=0.91, weight=0.8, evidence_ids=[score.id]
            ),
            DecisionFactor(
                name="review_threshold", value=0.8, weight=0.2, evidence_ids=[threshold.id]
            ),
        ],
        confidence=0.91,
        run=run,
    )
    await xai.record_provenance(
        "bank-api://accounts/4471/transactions/8841", "transaction://8841", "PRODUCED_BY", run=run
    )
    await xai.record_provenance("transaction://8841", score.id, "DERIVED_FROM", run=run)
    await xai.record_provenance(score.id, decision.id, "SUPPORTED_BY", run=run)
    await xai.finish_run(run)

    banner("Execution")
    print(run.execution.model_dump_json(indent=2))

    banner("Evidence")
    print(score.model_dump_json(indent=2, exclude=CONTEXT_FIELDS))

    banner("Decision")
    print(decision.model_dump_json(indent=2, exclude=CONTEXT_FIELDS))

    banner("Provenance lineage of the decision")
    store = xai.registry.require(ProvenanceStore)
    for link in await store.lineage(str(decision.id), context=run.execution.context):
        print(link.model_dump_json(indent=2, include={"source_id", "target_id", "relation"}))

    context = ExplanationContext(
        execution=run.execution,
        decision=decision,
        evidence=[score, threshold],
        audience=Audience.AUDITOR,
    )
    banner("Attribution")
    attribution = await xai.attribute(context)
    print(attribution.model_dump_json(indent=2, exclude=CONTEXT_FIELDS))

    banner("Policy decision (end user, exposure)")
    policy = xai.registry.require(PolicyProvider)
    end_user = context.model_copy(update={"audience": Audience.END_USER})
    exposure = await policy.evaluate(end_user, PolicyAction.EXPOSE)
    print(exposure.model_dump_json(indent=2, exclude=CONTEXT_FIELDS))

    banner("Explanation (auditor)")
    explanation = await xai.explain_decision(decision, audience=Audience.AUDITOR, run=run)
    print(explanation.model_dump_json(indent=2, exclude=CONTEXT_FIELDS))


if __name__ == "__main__":
    asyncio.run(main())
