"""Produce real, runnable JSON examples of every canonical xgraph model.

This script is the single source of truth for the JSON snippets quoted on
each ``docs/concepts/*.md`` page: Execution, Provenance, Evidence, Decision,
Attribution, Policy, and Explanation. Every payload below is produced by
actually constructing and (where applicable) running the real component --
none of it is hand-written for presentation.

Run with:

    uv run python examples/canonical_model_gallery.py
"""

import asyncio
from datetime import UTC, datetime

from _shared import compiled_graph

from langgraph_xai import (
    AttributionEngine,
    Decision,
    DecisionFactor,
    Evidence,
    EvidenceType,
    Execution,
    ExecutionStatus,
    ExplanationContext,
    HybridAttribution,
    PolicyProvider,
    ProvenanceLink,
    ProvenanceStore,
    XAIRuntime,
)
from langgraph_xai.core import PolicyAction
from langgraph_xai.storage import InMemoryProvenanceStore


def _banner(title: str) -> None:
    print(f"\n{'=' * 10} {title} {'=' * 10}")


async def main() -> None:
    store = InMemoryProvenanceStore()
    runtime = XAIRuntime(graph_id="fraud-review")
    runtime.register(ProvenanceStore, store)

    # --- Execution ------------------------------------------------------
    # A manually-recorded run showing a state transition and a tool call
    # nested under one Execution, exactly as automatic graph instrumentation
    # would populate it.
    run = await runtime.start_run({"metadata": {"trace_id": "trace-8841"}})
    await runtime.record_state_delta(
        "score_transaction", {"risk_score": 0.0}, {"risk_score": 0.91}, run=run
    )
    await runtime.record_tool(
        "fraud_detector",
        status="succeeded",
        latency_ms=42.5,
        output_reference="fraud-detector://run/8841/score",
        run=run,
    )
    await runtime.finish_run(run)
    _banner("Execution (real, nested tool call + state transition)")
    print(run.execution.model_dump_json(indent=2, exclude={"id", "timestamp"}))

    graph = runtime.instrument(
        compiled_graph(lambda _: {"risk_score": 0.91, "answer": "HUMAN_REVIEW"})
    )
    await graph.ainvoke({"risk_score": 0.0})
    context = runtime.context_from_config()

    # --- Evidence -----------------------------------------------------
    fraud_score_evidence = Evidence(
        context=context,
        evidence_type=EvidenceType.TOOL_RESULT,
        summary="Fraud detector scored the transaction 0.91 (high risk).",
        content_reference="fraud-detector://run/8841/score",
        confidence=0.97,
        quality=0.9,
    )
    threshold_evidence = Evidence(
        context=context,
        evidence_type=EvidenceType.POLICY,
        summary="Bank policy requires human review above a 0.80 risk threshold.",
        content_reference="policy://fraud/review-threshold",
        confidence=1.0,
    )
    _banner("Evidence")
    print(fraud_score_evidence.model_dump_json(indent=2))

    # --- Decision -------------------------------------------------------
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
        confidence=0.91,
    )
    _banner("Decision")
    print(decision.model_dump_json(indent=2))

    # --- Provenance -------------------------------------------------------
    # Bank API -> Transaction Record -> Fraud Detector -> Risk Score -> Decision
    links = [
        ProvenanceLink(
            context=context,
            source_id="bank-api://acct/4471/txn/8841",
            target_id="transaction-record://8841",
            relation="PRODUCED_BY",
        ),
        ProvenanceLink(
            context=context,
            source_id="transaction-record://8841",
            target_id=str(fraud_score_evidence.id),
            relation="DERIVED_FROM",
        ),
        ProvenanceLink(
            context=context,
            source_id=str(fraud_score_evidence.id),
            target_id=str(decision.id),
            relation="SUPPORTED_BY",
        ),
    ]
    for link in links:
        await store.write(link)
    lineage = await store.lineage(str(decision.id), context=context)
    _banner("Provenance (real lineage() query result)")
    print("\n".join(link.model_dump_json(indent=2) for link in lineage))

    # --- Attribution ------------------------------------------------------
    explanation_context = ExplanationContext(
        execution=Execution(
            context=context,
            status=ExecutionStatus.COMPLETED,
            started_at=datetime.now(UTC),
            ended_at=datetime.now(UTC),
        ),
        decision=decision,
        evidence=[fraud_score_evidence, threshold_evidence],
        provenance=list(links),
        audience="auditor",
    )
    attribution_engine: AttributionEngine = HybridAttribution()
    attribution = await attribution_engine.attribute(explanation_context)
    _banner("Attribution (real HybridAttribution.attribute() result)")
    print(attribution.model_dump_json(indent=2))

    # --- Policy -------------------------------------------------------
    policy_provider: PolicyProvider = runtime.registry.require(PolicyProvider)
    end_user_context = explanation_context.model_copy(update={"audience": "end_user"})
    policy_decision = await policy_provider.evaluate(end_user_context, PolicyAction.EXPOSE)
    _banner("Policy (real DefaultPolicyProvider.evaluate() result, end_user audience)")
    print(policy_decision.model_dump_json(indent=2))

    # --- Explanation --------------------------------------------------
    explanation_ctx = explanation_context.model_copy(update={"attribution": attribution})
    explanation = await runtime.explain(explanation_ctx)
    _banner("Explanation (real runtime.explain() result, auditor audience)")
    print(explanation.model_dump_json(indent=2, exclude={"id", "timestamp"}))

    await store.close()


if __name__ == "__main__":
    asyncio.run(main())
