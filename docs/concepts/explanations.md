# Explanations

An `Explanation` describes one decision to one audience. It is built from
recorded facts only, filtered by the audience's exposure policy, and it says
what it withheld.

```python
explanation = await xai.explain_decision(decision, audience=Audience.AUDITOR, run=run)
```

## Fields

| Field | Contains |
| --- | --- |
| `audience` | Who it is for: `developer` (default), `auditor`, `business`, `end_user`, or your own string. |
| `summary` | One sentence naming the decision and the selected action. |
| `reasons` | The selected action, the alternatives considered, factor values, and the decision's confidence. |
| `contributing_factors` | The [attribution](attribution.md) contributions, ranked by absolute score. |
| `supporting_evidence` | References to the decision's [evidence](evidence.md). |
| `disclosure` | Why sections were withheld, plus the policy's own reason, if any. |
| `metadata` | The engine that produced it, e.g. `{"engine": "structured"}`. |

## How an explanation is built

![How explain_decision builds an explanation](../assets/diagrams/explanation-flow.png)

1. `explain_decision` gathers the decision's run and the evidence it references
   into an `ExplanationContext`. Use `explain(context)` to build the context
   yourself.
2. If the registered engine needs an LLM, the runtime checks that
   `XAIConfig.llm_explanation_enabled` is set *before* any other work.
3. The registered `PolicyProvider` evaluates exposure (`PolicyAction.EXPOSE`)
   for the audience.
4. The `AttributionEngine` scores the decision, unless the context already
   carries an attribution.
5. The `ExplanationEngine` renders the explanation and empties every section
   the policy withholds.

If the policy, the attribution, or the engine fails, `XAIInstrumentationError`
is raised in **every** failure mode. A partial or unfiltered explanation is
never returned.

## Example: two audiences, one decision

The [fraud review example](../examples/full-explanation.md) registers a policy
that shows auditors everything and withholds attribution and evidence from end
users. The auditor sees the full picture (trimmed for readability: schema
versions, metadata, and each contribution's evidence IDs and rationale are
omitted):

```json
{
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
    {"evidence_id": "c5524467-78fa-4128-ade6-b6cf9944a995", "relationship": "supported_by"},
    {"evidence_id": "f3b1e032-a3c5-45a4-b125-81ef94d4f877", "relationship": "supported_by"}
  ],
  "contributing_factors": [
    {"factor_id": "fraud_risk_score", "factor_type": "decision_factor", "score": 0.4, "label": "fraud_risk_score"},
    {"factor_id": "c5524467-78fa-4128-ade6-b6cf9944a995", "factor_type": "policy", "score": 0.2669514148424987, "label": "Policy FR-7 requires human review above a 0.80 risk score."},
    {"factor_id": "f3b1e032-a3c5-45a4-b125-81ef94d4f877", "factor_type": "tool_result", "score": 0.23304858515750135, "label": "Fraud model scored the transaction 0.91."},
    {"factor_id": "review_threshold", "factor_type": "decision_factor", "score": 0.1, "label": "review_threshold"}
  ],
  "disclosure": [],
  "metadata": {"engine": "structured"}
}
```

The customer sees the outcome without internal scores, and is told what was
withheld:

```json
{
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
  "metadata": {"engine": "structured"}
}
```

Withholding `contributing_factors` also removes factor values from `reasons`,
so a score withheld from one section cannot reappear in another.

## Engines

| Engine | Behavior |
| --- | --- |
| `StructuredExplanationEngine` (default) | Deterministic. Builds every section from recorded fields and never calls a model. The same records always produce the same explanation. |
| `LLMExplanationEngine` | Rephrases the summary and reasons in natural language with a LangChain chat model you inject. The model receives only facts the policy allows, and its reply must match a strict JSON schema. Requires `enabled=True` and `XAIConfig(llm_explanation_enabled=True)`. See [LLM-phrased explanations](../how-to/llm-explanations.md). |

To render explanations differently, for example in another language or as
HTML, implement the `ExplanationEngine` protocol: a `requires_llm` attribute
and one `async def explain(context)`. Use the policy decisions in
`context.policies` to decide what to show.
