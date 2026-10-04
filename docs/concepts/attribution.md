# Attribution

Attribution answers "how much did each input contribute to this decision?". An
`AttributionEngine` turns a decision's factors and evidence into an
`AttributionResult`: a list of signed contributions.

- A **positive** score supports the selected action; a **negative** score
  opposes it.
- Normalized results have an absolute sum of 1, so a score is a share of the
  total.
- Every built-in engine is deterministic. The same records always give the
  same scores, in the same order.

Attribution runs on demand, when you call `explain`, `explain_decision`, or
`xai.attribute(context)`. It is never computed in the hot path of a graph run.

## Built-in engines

| Engine | Scores |
| --- | --- |
| `HybridAttribution` (default) | Decision factors and evidence together. Each family is normalized, then given its share: `rule_weight` and `evidence_weight`, 0.5 each by default. |
| `RuleBasedAttribution` | Each decision factor. The score comes from a rule you supply for the factor's name (a constant or a function of the factor), else the factor's `weight`, else 1.0. |
| `EvidenceAttribution` | Each piece of referenced evidence, as `confidence × quality`, where a missing value counts as 1.0. |

`AttributionResult.confidence` is the mean evidence strength. It is `None` for
`RuleBasedAttribution`, which carries no statistical confidence.

## Example

The decision on the [Decisions](decisions.md) page has two weighted factors
(`fraud_risk_score` 0.8 and `review_threshold` 0.2) and two pieces of evidence.
The fraud score evidence has strength 0.97 × 0.9 = 0.873; the policy evidence
has 1.0. The default engine gives each family half of the total:

```json
{
  "subject_id": "d0744d50-0ef0-44fb-a44b-1535ad9a48b4",
  "method": "hybrid",
  "contributions": [
    {
      "factor_id": "1f9e20f2-12ec-4b8c-ab22-0be30b398763",
      "factor_type": "policy",
      "score": 0.2669514148424987,
      "label": "Bank policy requires human review above a 0.80 risk score.",
      "evidence_ids": ["1f9e20f2-12ec-4b8c-ab22-0be30b398763"],
      "rationale": "Evidence confidence multiplied by evidence quality."
    },
    {
      "factor_id": "87507e0f-36f4-4a70-b81c-cf810ae222f3",
      "factor_type": "tool_result",
      "score": 0.23304858515750135,
      "label": "Fraud detector scored the transaction 0.91 (high risk).",
      "evidence_ids": ["87507e0f-36f4-4a70-b81c-cf810ae222f3"],
      "rationale": "Evidence confidence multiplied by evidence quality."
    },
    {
      "factor_id": "fraud_risk_score",
      "factor_type": "decision_factor",
      "score": 0.4,
      "label": "fraud_risk_score",
      "evidence_ids": ["87507e0f-36f4-4a70-b81c-cf810ae222f3"],
      "rationale": "Rule score for factor 'fraud_risk_score'."
    },
    {
      "factor_id": "review_threshold",
      "factor_type": "decision_factor",
      "score": 0.1,
      "label": "review_threshold",
      "evidence_ids": ["1f9e20f2-12ec-4b8c-ab22-0be30b398763"],
      "rationale": "Rule score for factor 'review_threshold'."
    }
  ],
  "normalized": true,
  "confidence": 0.9365,
  "metadata": {"rule_weight": 0.5, "evidence_weight": 0.5}
}
```

(Real output from the
[canonical model gallery](https://github.com/smuniharish/langgraph-xai/blob/master/examples/canonical_model_gallery.py);
`schema_version`, `id`, `timestamp`, `context`, and empty `metadata` omitted.)

Reading it:

- Factors share 0.5: `fraud_risk_score` = 0.5 × 0.8 = 0.40 and
  `review_threshold` = 0.5 × 0.2 = 0.10.
- Evidence shares 0.5 in proportion to strength: 0.5 × 1.0 / 1.873 = 0.267 for
  the policy, and 0.5 × 0.873 / 1.873 = 0.233 for the fraud score.
- `confidence` is the mean evidence strength: (1.0 + 0.873) / 2 = 0.9365.

## Custom rules and weights

Give individual factors their own scoring rule, including negative scores for
factors that argue against the selected action, and change the balance between
factors and evidence:

```python
from langgraph_xai import AttributionEngine, HybridAttribution, RuleBasedAttribution

xai.register(
    AttributionEngine,
    HybridAttribution(
        rule_based=RuleBasedAttribution(
            rules={
                "fraud_risk_score": lambda factor, context: float(factor.value),
                "customer_tenure_years": -0.3,
            }
        ),
        rule_weight=0.7,
        evidence_weight=0.3,
    ),
)
```

For a decision with those two factors and one piece of evidence, the
explanation's contributing factors are:

```text
fraud_risk_score         +0.526
Fraud score 0.91.        +0.300
customer_tenure_years    -0.174
```

The factors' absolute scores sum to the 0.7 share, the evidence receives 0.3,
and the long customer tenure counts against escalation.

To use a different method entirely (for example scores from your own model),
implement the `AttributionEngine` protocol: one `async def attribute(context)`
returning an `AttributionResult`. See [Extensibility](../architecture/plugins.md).

## What attribution claims, and what it does not

Built-in attribution distributes credit according to the **weights and evidence
strengths you recorded**. It makes those weights explicit, comparable, and
auditable. It does not measure causal influence or model sensitivity the way
SHAP or counterfactual methods do. If you need such measures, compute them in
your own engine and return them as an `AttributionResult`. Explanations will
present them the same way.
