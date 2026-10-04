"""End-to-end fraud review: capture a LangGraph run, record its decision basis, explain it.

The graph has three nodes. ``score_risk`` records the fraud score as evidence plus a
provenance link back to the transaction; ``route`` records the routing decision with
its alternatives, weighted factors, and supporting evidence. After the call returns,
``collect_runs`` hands back the run so the decision can be explained to different
audiences. A customer-safe policy withholds attribution details from end users.

Run with:

    uv run python examples/fraud_review.py
"""

import asyncio
from typing import TypedDict

from _shared import show
from langgraph.graph import END, START, StateGraph

from langgraph_xai import (
    Audience,
    DecisionFactor,
    DecisionType,
    EvidenceType,
    ExplanationContext,
    PolicyAction,
    PolicyDecision,
    PolicyProvider,
    ProvenanceStore,
    XAIRuntime,
)

xai = XAIRuntime(application_id="payments", tenant_id="acme-bank", graph_id="fraud-review")


class Review(TypedDict, total=False):
    transaction_id: str
    amount: float
    risk_score: float
    route: str


async def fetch_transaction(state: Review) -> Review:
    return {"amount": 9200.0}


async def score_risk(state: Review) -> Review:
    risk_score = 0.91 if state["amount"] > 5000 else 0.12
    evidence = await xai.record_evidence(
        EvidenceType.TOOL_RESULT,
        summary=f"Fraud model scored the transaction {risk_score:.2f}.",
        content_reference=f"fraud-model://scores/{state['transaction_id']}",
        confidence=0.97,
        quality=0.9,
    )
    await xai.record_provenance(
        f"transactions://{state['transaction_id']}", evidence.id, "DERIVED_FROM"
    )
    return {"risk_score": risk_score}


async def route(state: Review) -> Review:
    threshold = 0.8
    run = xai.current_run
    assert run is not None
    (score,) = run.evidence
    policy = await xai.record_evidence(
        EvidenceType.POLICY,
        summary="Policy FR-7 requires human review above a 0.80 risk score.",
        content_reference="policy://fraud/FR-7",
        confidence=1.0,
    )
    selected = "HUMAN_REVIEW" if state["risk_score"] >= threshold else "AUTO_APPROVE"
    await xai.record_decision(
        selected,
        decision_type=DecisionType.ROUTING,
        candidate_actions=["AUTO_APPROVE", "HUMAN_REVIEW", "DECLINE"],
        evidence_ids=[score.id, policy.id],
        factors=[
            DecisionFactor(
                name="fraud_risk_score",
                value=state["risk_score"],
                weight=0.8,
                evidence_ids=[score.id],
            ),
            DecisionFactor(
                name="review_threshold", value=threshold, weight=0.2, evidence_ids=[policy.id]
            ),
        ],
        policy_references=["FR-7"],
        confidence=0.93,
    )
    return {"route": selected}


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


def build_graph():
    builder = StateGraph(Review)
    builder.add_node("fetch_transaction", fetch_transaction)
    builder.add_node("score_risk", score_risk)
    builder.add_node("route", route)
    builder.add_edge(START, "fetch_transaction")
    builder.add_edge("fetch_transaction", "score_risk")
    builder.add_edge("score_risk", "route")
    builder.add_edge("route", END)
    return builder.compile()


async def main() -> None:
    xai.register(PolicyProvider, CustomerSafePolicy())
    graph = xai.instrument(build_graph())

    with xai.collect_runs() as runs:
        result = await graph.ainvoke({"transaction_id": "txn-8841"})
    (run,) = runs
    execution = run.execution

    print(f"Route: {result['route']}  (run {run.run_id}, status {execution.status})")
    show(
        "Captured execution",
        {
            "nodes": [f"{node.node_id}: {node.status}" for node in execution.nodes],
            "state_changes": [
                f"{item.node_id}: "
                + ", ".join(f"{c.path} {c.before!r} -> {c.after!r}" for c in item.changes)
                for item in execution.state_transitions
            ],
            "evidence": [item.summary for item in run.evidence],
        },
    )

    (decision,) = run.decisions
    hidden = {"id", "timestamp", "context"}
    for audience in (Audience.AUDITOR, Audience.END_USER):
        explanation = await xai.explain_decision(decision, audience=audience, run=run)
        show(f"Explanation for {audience}", explanation.model_dump(mode="json", exclude=hidden))

    store = xai.registry.require(ProvenanceStore)
    lineage = await store.lineage(str(run.evidence[0].id), context=execution.context)
    show(
        "Provenance of the fraud score",
        [f"{link.target_id} {link.relation} {link.source_id}" for link in lineage],
    )


if __name__ == "__main__":
    asyncio.run(main())
