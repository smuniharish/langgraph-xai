# How to enable live LLM explanations

**Goal:** turn on `LLMExplanationEngine` safely — understanding exactly what
boundary protects you from a model hallucinating fields you didn't ask for.

## Steps

1. `LLMExplanationEngine` is disabled by default, and doubly so: it also
   requires `XAIConfig.llm_explanation_enabled=True` at the runtime level (a
   deliberate two-key safety interlock).

   ```python
   runtime = XAIRuntime(config=XAIConfig(llm_explanation_enabled=True))
   ```

2. Inject any LangChain chat model or `Runnable[str, str]`:

   ```python
   model = ChatOpenAI(base_url=..., api_key=..., model="gpt-5.6-luna")
   engine = LLMExplanationEngine(model=model, enabled=True, timeout=30.0)
   runtime.register(ExplanationEngine, engine)
   ```

3. Call `runtime.explain(context)` as usual — the LLM only ever receives
   already-captured, policy-filtered facts (selected action, factors,
   evidence), never a raw prompt or private model reasoning, and its output
   is parsed against a strict internal schema requiring exactly three fields:
   `summary`, `reasons`, and `disclosure`. Any extra field the model invents
   (for example a `hidden_reasoning` key) is rejected outright, not silently
   accepted.

4. Handle both realistic failure shapes:
   - `asyncio.TimeoutError` if the model doesn't respond within `timeout`
     seconds;
   - `ValueError("LLM explanation output failed schema validation")` if the
     model's JSON doesn't match `ExplanationDraft` (or isn't valid JSON at
     all).

   `runtime.explain(...)` itself applies your configured
   [failure mode](failure-modes.md) around these — a `fail_open` runtime
   returns without raising (see `runtime.errors` for the captured
   exception), while `fail_closed`/`strict` propagate an
   `XAIInstrumentationError`.

## Full worked example: wired through a real LangGraph graph

The example above is intentionally minimal; here is the full picture —
`LLMExplanationEngine` wired into a real, compiled LangGraph graph via
`runtime.instrument(...)`, with the decision recorded and explained from
inside the node that made it, exactly as [Quickstart](../getting-started/quickstart.md)
describes. Nothing here is standalone: `score_transaction` and
`route_decision` are real graph nodes, `runtime.instrument(graph).ainvoke(...)`
is the real entry point, and the JSON below is the real output of that
call.

```python
from typing import TypedDict

import langchain_openai
from langgraph.graph import END, START, StateGraph

from langgraph_xai import DecisionFactor, XAIConfig, XAIRuntime
from langgraph_xai.core import ExplanationContext
from langgraph_xai.core.protocols import ExplanationEngine
from langgraph_xai.explanation import LLMExplanationEngine


class FraudState(TypedDict, total=False):
    transaction_id: str
    amount: float
    risk_score: float
    decision: str
    explanation: str


async def score_transaction(state: FraudState) -> dict:
    # A real integration calls your actual fraud-scoring service/tool here;
    # record_tool(...) captures it as a first-class ToolExecution either way.
    risk_score = 0.91 if state["amount"] > 5000 else 0.12
    await runtime.record_tool(
        "fraud_detector",
        output_reference=f"fraud-detector://{state['transaction_id']}/score",
        latency_ms=42.5,
    )
    return {"risk_score": risk_score}


async def route_decision(state: FraudState) -> dict:
    selected = "HUMAN_REVIEW" if state["risk_score"] >= 0.8 else "AUTO_APPROVE"
    decision = await runtime.record_decision(
        selected,
        decision_type="routing",
        candidate_actions=["AUTO_APPROVE", "HUMAN_REVIEW", "AUTO_DECLINE"],
        factors=[DecisionFactor(name="fraud_risk_score", value=state["risk_score"])],
        confidence=state["risk_score"],
    )
    explanation = await runtime.explain(
        ExplanationContext(
            execution=runtime.current_run.execution,
            decision=decision,
            audience="end_user",
        )
    )
    return {"decision": selected, "explanation": explanation.summary}


model = langchain_openai.ChatOpenAI(base_url=..., api_key=..., model="gpt-5.6-luna")
runtime = XAIRuntime(graph_id="fraud-review", config=XAIConfig(llm_explanation_enabled=True))
runtime.register(ExplanationEngine, LLMExplanationEngine(model, enabled=True, timeout=30.0))

builder = StateGraph(FraudState)
builder.add_node("score_transaction", score_transaction)
builder.add_node("route_decision", route_decision)
builder.add_edge(START, "score_transaction")
builder.add_edge("score_transaction", "route_decision")
builder.add_edge("route_decision", END)
graph = builder.compile()

instrumented = runtime.instrument(graph)
result = await instrumented.ainvoke({"transaction_id": "txn-8841", "amount": 9200.0})
```

Real output, one real call against `gpt-5.6-luna`, driven entirely by
`instrumented.ainvoke(...)` above — `runtime.explain(...)` was never called
directly from application code:

```json
{
  "audience": "end_user",
  "summary": "This case has been selected for human review.",
  "reasons": ["The fraud risk score is 0.91."],
  "contributing_factors": [
    {
      "factor_id": "fraud_risk_score",
      "score": 1.0,
      "label": "fraud_risk_score",
      "rationale": "Rule score for factor 'fraud_risk_score'."
    }
  ],
  "disclosure": ["Private memory and raw content are withheld by default."],
  "metadata": {"engine": "llm", "validated": true}
}
```

```text
result["decision"] == "HUMAN_REVIEW"
result["explanation"] == "This case has been selected for human review."
```

`score_transaction` and `route_decision` are ordinary async LangGraph
nodes — nothing about them is xgraph-specific except the two `runtime.*`
calls inside `route_decision`. `runtime.instrument(graph)` is what makes
`runtime.current_run` available inside those nodes in the first place; see
[Quickstart](../getting-started/quickstart.md) for why that link breaks if
you call `graph.ainvoke(...)` directly instead of through the instrumented
wrapper, and
[Explain a decision after the run finishes](explain-after-run.md) for the
pattern to use when the decision is only known *after* the graph call
returns (e.g. in a web handler, not inside any node).

The `summary` and `reasons` text is genuinely produced by the model each
call — expect close paraphrases, not byte-identical output, across runs.

## Real evidence this boundary actually holds

- `tests/explanation/test_engines.py::test_llm_explanation_still_rejects_unknown_fields`
  — a real assertion that a smuggled extra field is rejected.
- The [disclosure-policy matrix](../examples/disclosure-matrix.md) ran the
  LLM engine through 8 real permutations against `gpt-5.6-luna`, with real
  latency between 1.7s and 8.2s per call — useful for setting your own
  `timeout`.
- A real, previously-undetected provider quirk (a scalar string instead of a
  JSON array for `disclosure`) was found and fixed this way — see the
  ["Why the LLM engine needed a real fix"](../examples/disclosure-matrix.md#why-the-llm-engine-needed-a-real-fix)
  section.
