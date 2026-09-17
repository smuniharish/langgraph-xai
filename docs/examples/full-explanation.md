# Full explanation output

This page shows the **exact, real** JSON produced by
[`examples/full_explanation_output.py`](https://github.com/samamuniharish/langgraph-xai/blob/main/examples/full_explanation_output.py)
— nothing here is hand-written or simplified for presentation. It builds a
real banking decision (a fraud score routed to `HUMAN_REVIEW`), attaches two
pieces of real `Evidence`, and calls `runtime.explain(...)` using the default
`StructuredExplanationEngine` and `HybridAttribution`.

```python
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

decision = Decision(
    context=context,
    decision_type="routing",
    selected_action="HUMAN_REVIEW",
    candidate_actions=["AUTO_APPROVE", "HUMAN_REVIEW", "AUTO_DECLINE"],
    evidence_ids=[fraud_score_evidence.id, threshold_evidence.id],
    factors=[
        DecisionFactor(
            name="fraud_risk_score", value=0.91, weight=0.8, evidence_ids=[fraud_score_evidence.id]
        ),
        DecisionFactor(
            name="review_threshold", value=0.8, weight=0.2, evidence_ids=[threshold_evidence.id]
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
```

Run it yourself:

```bash
uv run python examples/full_explanation_output.py
```

## Real captured output

```json
{
  "schema_version": "1.0.0",
  "timestamp": "2026-09-17T09:46:40.412712Z",
  "context": {
    "schema_version": "1.0.0",
    "application_id": "application",
    "tenant_id": "default",
    "graph_id": "banking-review",
    "run_id": "e4b11162-4104-4a55-af97-e4edf2ac4e69",
    "thread_id": null,
    "trace_id": null,
    "span_id": null,
    "parent_id": null,
    "checkpoint_id": null,
    "metadata": {}
  },
  "audience": "end_user",
  "summary": "The end_user explanation is based on the selected action 'HUMAN_REVIEW'.",
  "reasons": [
    "Selected action: HUMAN_REVIEW.",
    "Factor fraud_risk_score was 0.91.",
    "Factor review_threshold was 0.8."
  ],
  "supporting_evidence": [
    { "schema_version": "1.0.0", "evidence_id": "b72519b6-2cb5-44c0-9647-0e52110a053f", "relationship": "supported_by" },
    { "schema_version": "1.0.0", "evidence_id": "d73f893f-6182-44a3-b1d4-19e05871650d", "relationship": "supported_by" }
  ],
  "contributing_factors": [
    {
      "factor_id": "d73f893f-6182-44a3-b1d4-19e05871650d",
      "factor_type": "policy",
      "score": 0.33670033670033667,
      "label": "Bank policy requires human review above a 0.80 risk threshold.",
      "rationale": "Evidence confidence multiplied by evidence quality."
    },
    {
      "factor_id": "b72519b6-2cb5-44c0-9647-0e52110a053f",
      "factor_type": "tool_result",
      "score": 0.32659932659932656,
      "label": "Fraud detector scored the transaction 0.91 (high risk).",
      "rationale": "Evidence confidence multiplied by evidence quality."
    },
    {
      "factor_id": "fraud_risk_score",
      "factor_type": "decision_factor",
      "score": 0.26936026936026936,
      "label": "fraud_risk_score",
      "rationale": "Rule score for factor 'fraud_risk_score'."
    },
    {
      "factor_id": "review_threshold",
      "factor_type": "decision_factor",
      "score": 0.06734006734006734,
      "label": "review_threshold",
      "rationale": "Rule score for factor 'review_threshold'."
    }
  ],
  "disclosure": [
    "Private memory and raw content are withheld by default."
  ],
  "metadata": { "engine": "structured" }
}
```

## What to notice

- **Every nested object carries `schema_version`** (see [ADR-016](../architecture/decisions.md#adr-016-canonical-serialized-contracts-carry-a-schema-version)) —
  a consumer can detect drift without guessing.
- **`contributing_factors` mixes two attribution sources** — the evidence
  -confidence-based factors (`tool_result`, `policy`) from `HybridAttribution`
  and the decision-level factors you supplied (`decision_factor`) — sorted by
  score, not insertion order.
- **`disclosure`** already carries a default policy note
  (`DefaultPolicyProvider` withholds private memory/raw content by default)
  even though this example never touched policy configuration explicitly.
- The whole payload was produced with **no LLM call** — `StructuredExplanationEngine`
  is fully deterministic, which is why it is the runtime default.

For the same fixture pattern exercised across audiences, policies, and both
explanation engines (including a real LLM), see the
[disclosure-policy matrix](disclosure-matrix.md).
