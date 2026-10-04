# Fraud review: full explanation

A three-node fraud review graph that records evidence, a routing decision, and
provenance, then explains the decision to an auditor and to a customer. Source:
[`examples/fraud_review.py`](https://github.com/smuniharish/langgraph-xai/blob/master/examples/fraud_review.py).

```bash
uv run python examples/fraud_review.py
```

## The graph

`fetch_transaction` loads the amount. `score_risk` scores it, records the score
as evidence, and links the evidence to the transaction it was derived from:

```python
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
```

`route` records the policy it applies as a second piece of evidence, then the
decision with its alternatives and weighted factors:

```python
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
```

A policy provider shows end users the outcome and reasons, and everyone else
everything:

```python
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
```

## Running and explaining

```python
xai.register(PolicyProvider, CustomerSafePolicy())
graph = xai.instrument(build_graph())

with xai.collect_runs() as runs:
    result = await graph.ainvoke({"transaction_id": "txn-8841"})
(run,) = runs

(decision,) = run.decisions
for audience in (Audience.AUDITOR, Audience.END_USER):
    explanation = await xai.explain_decision(decision, audience=audience, run=run)

store = xai.registry.require(ProvenanceStore)
lineage = await store.lineage(str(run.evidence[0].id), context=run.execution.context)
```

## Output

Complete, unedited output of one run (the script omits each explanation's `id`,
`timestamp`, and `context`):

```text
Route: HUMAN_REVIEW  (run 4fdefdf9-32f3-4990-bf06-a01fc592c9bc, status completed)

--- Captured execution ---
{
  "nodes": [
    "fetch_transaction: completed",
    "score_risk: completed",
    "route: completed"
  ],
  "state_changes": [
    "fetch_transaction: amount None -> 9200.0",
    "score_risk: risk_score None -> 0.91",
    "route: route None -> 'HUMAN_REVIEW'"
  ],
  "evidence": [
    "Fraud model scored the transaction 0.91.",
    "Policy FR-7 requires human review above a 0.80 risk score."
  ]
}

--- Explanation for auditor ---
{
  "schema_version": "2.0.0",
  "audience": "auditor",
  "summary": "The routing decision selected 'HUMAN_REVIEW'.",
  "reasons": [
    "Selected action: HUMAN_REVIEW.",
    "Alternatives considered: AUTO_APPROVE, DECLINE.",
    "Factor fraud_risk_score was 0.91.",
    "Factor review_threshold was 0.8.",
    "Decision confidence: 0.93."
  ],
  "supporting_evidence": [
    {
      "schema_version": "2.0.0",
      "evidence_id": "94c97233-6b97-4870-86ab-10ddd48e51a7",
      "relationship": "supported_by"
    },
    {
      "schema_version": "2.0.0",
      "evidence_id": "bff3013c-2026-41be-95a3-790fd11128e4",
      "relationship": "supported_by"
    }
  ],
  "contributing_factors": [
    {
      "schema_version": "2.0.0",
      "factor_id": "fraud_risk_score",
      "factor_type": "decision_factor",
      "score": 0.4,
      "label": "fraud_risk_score",
      "evidence_ids": [
        "bff3013c-2026-41be-95a3-790fd11128e4"
      ],
      "rationale": "Rule score for factor 'fraud_risk_score'.",
      "metadata": {}
    },
    {
      "schema_version": "2.0.0",
      "factor_id": "94c97233-6b97-4870-86ab-10ddd48e51a7",
      "factor_type": "policy",
      "score": 0.2669514148424987,
      "label": "Policy FR-7 requires human review above a 0.80 risk score.",
      "evidence_ids": [
        "94c97233-6b97-4870-86ab-10ddd48e51a7"
      ],
      "rationale": "Evidence confidence multiplied by evidence quality.",
      "metadata": {}
    },
    {
      "schema_version": "2.0.0",
      "factor_id": "bff3013c-2026-41be-95a3-790fd11128e4",
      "factor_type": "tool_result",
      "score": 0.23304858515750135,
      "label": "Fraud model scored the transaction 0.91.",
      "evidence_ids": [
        "bff3013c-2026-41be-95a3-790fd11128e4"
      ],
      "rationale": "Evidence confidence multiplied by evidence quality.",
      "metadata": {}
    },
    {
      "schema_version": "2.0.0",
      "factor_id": "review_threshold",
      "factor_type": "decision_factor",
      "score": 0.1,
      "label": "review_threshold",
      "evidence_ids": [
        "94c97233-6b97-4870-86ab-10ddd48e51a7"
      ],
      "rationale": "Rule score for factor 'review_threshold'.",
      "metadata": {}
    }
  ],
  "disclosure": [],
  "metadata": {
    "engine": "structured"
  }
}

--- Explanation for end_user ---
{
  "schema_version": "2.0.0",
  "audience": "end_user",
  "summary": "The routing decision selected 'HUMAN_REVIEW'.",
  "reasons": [
    "Selected action: HUMAN_REVIEW.",
    "Alternatives considered: AUTO_APPROVE, DECLINE.",
    "Decision confidence: 0.93."
  ],
  "supporting_evidence": [],
  "contributing_factors": [],
  "disclosure": [
    "Contributing factors are withheld by policy.",
    "Supporting evidence is withheld by policy.",
    "Customers receive the outcome and reasons only."
  ],
  "metadata": {
    "engine": "structured"
  }
}

--- Provenance of the fraud score ---
[
  "bff3013c-2026-41be-95a3-790fd11128e4 DERIVED_FROM transactions://txn-8841"
]
```

## What to notice

- **Three nodes, three state changes, two pieces of evidence**, all captured in
  one run without passing anything between the nodes but graph state.
- **The auditor sees why.** `fraud_risk_score` contributes 0.40 (its 0.8
  weight times the factors' 0.5 share). The two pieces of evidence share the
  other half in proportion to their strength. See
  [Attribution](../concepts/attribution.md).
- **The customer sees what, and is told what is withheld.** The fraud score
  appears nowhere in the end-user explanation, not even in `reasons`, and
  `disclosure` states which sections were withheld and why.
- **Provenance closes the loop**: the score is traceable to the transaction it
  was computed from.
