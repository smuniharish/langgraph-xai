# Generate LLM-phrased explanations

The default `StructuredExplanationEngine` produces precise but formulaic text.
`LLMExplanationEngine` asks a chat model to phrase the summary and reasons in
natural language for the audience. The model only *phrases* facts that were
recorded and that the policy allows. It cannot add evidence, see withheld
sections, or change attribution.

## Enable it

LLM explanations need two explicit opt-ins: the engine is constructed with
`enabled=True`, and the runtime is configured with `llm_explanation_enabled=True`.
Credentials in the environment never enable anything on their own.

```bash
pip install "langgraph-xai[llm-openai]"
```

```python
from langchain_openai import ChatOpenAI

from langgraph_xai import ExplanationEngine, LLMExplanationEngine, XAIConfig, XAIRuntime

model = ChatOpenAI(model="gpt-4o-mini", temperature=0)
xai = XAIRuntime(XAIConfig(llm_explanation_enabled=True, operation_timeout_seconds=60))
xai.register(ExplanationEngine, LLMExplanationEngine(model, enabled=True, timeout=45))
```

Any LangChain chat model works, including OpenAI-compatible gateways via
`ChatOpenAI(base_url=...)`, Anthropic, or a local model. The model is injected:
the engine never creates one.

Two time limits apply. `timeout` bounds the model call, and the runtime's
`operation_timeout_seconds` (10 seconds by default) bounds the whole
explanation step. Raise both to suit your model's latency.

## Example

With the customer-safe policy from [Policies](../concepts/policies.md#exposure-policy),
the same decision explained to two audiences. This is real output from a live
model:

```json
{
  "audience": "auditor",
  "summary": "Route the transaction to human review.",
  "reasons": ["The fraud model scored the transaction 0.91."],
  "disclosure": [],
  "metadata": {"engine": "llm", "validated": true}
}
```

```json
{
  "audience": "end_user",
  "summary": "This case has been routed for human review.",
  "reasons": ["The selected action is HUMAN_REVIEW."],
  "disclosure": [
    "Contributing factors are withheld by policy.",
    "Supporting evidence is withheld by policy.",
    "Customers receive the outcome and reasons only."
  ],
  "metadata": {"engine": "llm", "validated": true}
}
```

The end-user prompt contained neither the fraud score nor the evidence, so the
model could not reveal them.

## What the model receives

A single JSON prompt containing:

- the audience, the decision type, and the selected action;
- the candidate actions and factor values, unless `reasons` or
  `contributing_factors` is withheld;
- evidence summaries and confidence, unless `supporting_evidence` is withheld;
- the names of withheld sections, with an instruction never to mention, guess,
  or deny them;
- the required output schema and an instruction to use only the supplied facts
  and never to provide hidden reasoning.

Raw content, content references, private memory, state values, and tool
payloads are never included.

## What is kept from the model's reply

The reply must be a JSON object with exactly `summary`, `reasons`, and
`disclosure`. A JSON code fence is accepted, and so is a single string where a
list is expected. Any other shape is rejected. From the reply:

- `summary` replaces the structured summary;
- `reasons` replace the structured reasons, unless reasons are withheld, in
  which case they stay empty whatever the model returns;
- `disclosure` notes are appended to the policy's notes.

`contributing_factors` and `supporting_evidence` always come from the
structured engine. The model cannot alter them.

## When the model fails

A timeout, a provider error, or an invalid reply raises
`XAIInstrumentationError` from `explain` and `explain_decision`, in every
failure mode. The cause is kept in `xai.errors`. To fall back to the
deterministic text, explain again with a runtime that shares the policy and
attribution providers but keeps the default structured engine:

```python
try:
    explanation = await xai.explain_decision(decision, audience=audience, run=run)
except XAIInstrumentationError:
    fallback = XAIRuntime()
    fallback.register(PolicyProvider, xai.registry.require(PolicyProvider))
    fallback.register(AttributionEngine, xai.registry.require(AttributionEngine))
    explanation = await fallback.explain_decision(decision, audience=audience, run=run)
```

The fallback has its own registry, so the primary runtime keeps its LLM engine.

## Verify it across audiences

The [disclosure matrix example](../examples/disclosure-matrix.md) explains one
decision with both engines, two policies, and all four audiences, and asserts
the policy on every row. Against a live model, all 16 combinations pass:

```text
audience   policy           engine     factors evidence  summary
business   audience-scoped  structured       0        0  The routing decision selected 'MANUAL_REVIEW'.  [0.00s]
business   audience-scoped  llm              0        0  Route to manual review.  [3.11s]
end_user   permissive       llm              4        2  Your application has been routed for manual review.  [2.74s]
end_user   audience-scoped  llm              0        0  Manual review  [2.03s]
```

(Four of the 16 rows shown.)
