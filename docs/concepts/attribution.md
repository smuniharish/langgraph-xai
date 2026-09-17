# Attribution

## Kid-level view

Attribution is a careful note about which inputs were associated with an
outcome, not a magical proof of why it happened.

## Production view

Record the attribution method, scope, inputs considered, result, uncertainty,
and limitations. Methods may be rule-based, retrieval-based, or
model/measurement-derived; their validity remains application-specific.

## Why and architecture

Keeping method metadata beside the result prevents a renderer or integration
from turning a heuristic into an unsupported causal statement.

## Real example: input and output

`HybridAttribution` combines a rule-based score (from `Decision.factors`)
and an evidence-quality score (from `Evidence.confidence * Evidence.quality`)
with configurable weights, then normalizes so the absolute scores sum to one:

```python
attribution_engine = HybridAttribution()  # default: 50% rules, 50% evidence
attribution = await attribution_engine.attribute(explanation_context)
```

Real captured output, produced by
[`examples/canonical_model_gallery.py`](https://github.com/samamuniharish/langgraph-xai/blob/main/examples/canonical_model_gallery.py):

```json
{
  "schema_version": "1.0.0",
  "subject_id": "31406623-8b6d-4148-8d54-e2ab93a8a39f",
  "method": "hybrid",
  "contributions": [
    {
      "factor_id": "e42ff48a-9ecb-41e9-ba82-4a3d8cda4064",
      "factor_type": "tool_result",
      "score": 0.3038635572572224,
      "label": "Fraud detector scored the transaction 0.91 (high risk).",
      "rationale": "Evidence confidence multiplied by evidence quality."
    },
    {
      "factor_id": "1e74b6d9-dc1e-4be2-8d75-9b5395b680f3",
      "factor_type": "policy",
      "score": 0.34806822137138876,
      "label": "Bank policy requires human review above a 0.80 risk threshold.",
      "rationale": "Evidence confidence multiplied by evidence quality."
    },
    {
      "factor_id": "fraud_risk_score",
      "factor_type": "decision_factor",
      "score": 0.278454577097111,
      "label": "fraud_risk_score",
      "rationale": "Rule score for factor 'fraud_risk_score'."
    },
    {
      "factor_id": "review_threshold",
      "factor_type": "decision_factor",
      "score": 0.06961364427427776,
      "label": "review_threshold",
      "rationale": "Rule score for factor 'review_threshold'."
    }
  ],
  "normalized": true,
  "confidence": 1.0,
  "metadata": { "rule_weight": 0.5, "evidence_weight": 0.5 }
}
```

Every `rationale` says exactly what was computed ("evidence confidence
multiplied by evidence quality", "rule score for factor X") — never "this is
why the model chose this", which `HybridAttribution` has no way to know.

## Mistakes to avoid

Say “this citation was selected by retrieval ranking” rather than “this caused
the answer.” Do not omit method/version or present correlation as proof.


