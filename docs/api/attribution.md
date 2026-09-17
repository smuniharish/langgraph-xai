# Attribution engines

An `AttributionEngine` scores which factors and evidence contributed to a
decision. Every built-in engine returns *signed* contributions: positive
values support the decision, negative values oppose it; normalized results
have an absolute-score sum of one.

## `RuleBasedAttribution`

Scores each `DecisionFactor` from an explicit rule table — a constant
weight, a callable `(factor, context) -> float`, or the factor's own
`weight` field as a fallback:

```python
from langgraph_xai.attribution import RuleBasedAttribution

engine = RuleBasedAttribution(rules={"fraud_risk_score": 0.8, "review_threshold": 0.2})
```

## `EvidenceAttribution`

Scores each piece of evidence referenced by the decision as
`confidence * quality` — use this when you trust evidence metadata more
than hand-tuned rule weights.

## `HybridAttribution` (default)

Runs both engines and combines their (unnormalized) scores with configurable
weights, then normalizes the combined result — the default registered by
`XAIRuntime()`:

```python
from langgraph_xai.attribution import HybridAttribution

engine = HybridAttribution(rule_weight=0.7, evidence_weight=0.3)
runtime.register(AttributionEngine, engine)
```

See [Concepts: Attribution](../concepts/attribution.md) for a real,
complete `AttributionResult` produced by the default weights (0.5 / 0.5).

## Reference

::: langgraph_xai.attribution.RuleBasedAttribution

::: langgraph_xai.attribution.EvidenceAttribution

::: langgraph_xai.attribution.HybridAttribution
