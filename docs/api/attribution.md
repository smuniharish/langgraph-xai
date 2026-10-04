# Attribution engines

Deterministic engines that score how much each decision factor and piece of
evidence contributed to a decision. `HybridAttribution` is the default. See
[Attribution](../concepts/attribution.md) for a worked example.

```python
from langgraph_xai import AttributionEngine, HybridAttribution, RuleBasedAttribution

xai.register(
    AttributionEngine,
    HybridAttribution(
        rule_based=RuleBasedAttribution(rules={"customer_tenure_years": -0.3}),
        rule_weight=0.7,
        evidence_weight=0.3,
    ),
)
```

::: langgraph_xai.attribution.engines.HybridAttribution

::: langgraph_xai.attribution.engines.RuleBasedAttribution

::: langgraph_xai.attribution.engines.EvidenceAttribution
