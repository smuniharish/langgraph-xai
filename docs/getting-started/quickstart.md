# Quickstart

This page runs one real, complete flow end to end: instrument a compiled
LangGraph graph, execute it, record a decision, and produce a
policy-filtered explanation — first with the free, deterministic default
engine, then optionally with a live LLM. Every code block on this page was
actually run; the output shown is the real, captured output.

## Install and construct a runtime

```python
from langgraph_xai import XAIRuntime

runtime = XAIRuntime(graph_id="fraud-review")
```

`XAIRuntime()` needs nothing else to start: every capability (storage,
observability, attribution, explanation, policy) already has a working
in-memory or no-op default. See [Configuration](../api/config.md) for every
constructor parameter and when to change it.

## Instrument, run, record a decision, and explain it

```python
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from langgraph_xai import DecisionFactor
from langgraph_xai.core import ExplanationContext


class State(TypedDict, total=False):
    query: str
    answer: str


async def answer(state: dict) -> dict:
    # Record *why*, from inside the node that made the call. No canonical
    # model is built by hand: record_decision() constructs and persists a
    # Decision for you, and runtime.current_run.execution is the live
    # Execution for the run already in progress.
    decision = await runtime.record_decision(
        "FINAL_RESPONSE",
        decision_type="routing",
        factors=[DecisionFactor(name="answer_available", value=True)],
    )
    explanation = await runtime.explain(
        ExplanationContext(
            execution=runtime.current_run.execution,
            decision=decision,
            audience="end_user",
        )
    )
    return {"answer": f"Echo: {state['query']}", "explanation": explanation.summary}


builder = StateGraph(State)
builder.add_node("answer", answer)
builder.add_edge(START, "answer")
builder.add_edge("answer", END)
graph = builder.compile()

instrumented = runtime.instrument(graph)
result = await instrumented.ainvoke({"query": "Why?"})
print(result["answer"], "|", result["explanation"])
```

`instrument(...)` wraps `invoke`/`ainvoke`/`stream`/`astream`/`batch`/
`abatch` transparently — your graph's inputs and outputs are unchanged;
execution, tool-call, and state-transition records are captured alongside.
`runtime.current_run` is only set *while* an
instrumented call is in flight, which is exactly why the decision and
explanation are recorded from inside the node rather than after
`ainvoke` returns — see
[How-to: explain a decision after the run finishes](../how-to/explain-after-run.md)
for the pattern to use instead when you need to explain a decision made
outside any node (e.g. in a web handler, after the graph call returns).

Real captured output, running this exact flow:

```text
Echo: Why? | The end_user explanation is based on the selected action 'FINAL_RESPONSE'.
```

The same pattern, wired through a real compiled graph, lives in
[`examples/minimal_langgraph.py`](https://github.com/samamuniharish/langgraph-xai/blob/main/examples/minimal_langgraph.py):

```bash
$ uv run python examples/minimal_langgraph.py
Echo: Why? | The end_user explanation is based on the selected action 'FINAL_RESPONSE'.
```

This explanation was assembled by the built-in `StructuredExplanationEngine`
— deterministic, free, and enabled by default. See
[Concepts: Explanations](../concepts/explanations.md) for the full JSON
shape and how the same decision renders differently per audience.

!!! note "Do I ever construct `Execution`, `Decision`, `Evidence`, or `ProvenanceLink` by hand?"
    Rarely, in application code. `runtime.record_decision(...)`,
    `record_evidence(...)`, and `record_provenance(...)` already build and
    persist those canonical models for you from plain arguments — and
    `runtime.current_run.execution` gives you the live `Execution` for
    free. The one object you *do* still assemble yourself is
    `ExplanationContext` — it is not a recorded artifact but the request
    "explain this decision, for this audience" — and it is a thin
    reference wrapper, not data you re-derive. The
    [canonical model gallery](https://github.com/samamuniharish/langgraph-xai/blob/main/examples/canonical_model_gallery.py)
    behind the JSON on every [Concepts](../concepts/index.md) page
    constructs every model directly and by hand instead, on purpose: it
    exists to show the exact shape of each model in isolation, not to
    demonstrate idiomatic application code.

## Optional: phrase the explanation with a live LLM

`llm_explanation_enabled` is `False` by default, so `runtime.explain(...)`
never calls a model unless you deliberately opt in and register an engine
that wraps one:

```python
import langchain_openai
from langgraph_xai import XAIConfig
from langgraph_xai.core.protocols import ExplanationEngine
from langgraph_xai.explanation import LLMExplanationEngine

model = langchain_openai.ChatOpenAI(model="gpt-5.6-luna", base_url="...", api_key="...")
runtime = XAIRuntime(graph_id="fraud-review", config=XAIConfig(llm_explanation_enabled=True))
runtime.register(ExplanationEngine, LLMExplanationEngine(model, enabled=True, timeout=30.0))

# Same call as above — swapping the registered ExplanationEngine is the
# only change; runtime.current_run.execution and decision are unchanged.
explanation = await runtime.explain(
    ExplanationContext(
        execution=runtime.current_run.execution, decision=decision, audience="end_user"
    )
)
```

Real captured output, one real call against an OpenAI-compatible model
(`gpt-5.6-luna`), for a `HUMAN_REVIEW` decision with one factor
(`fraud_risk_score=0.91`):

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

The model only ever receives already-captured, policy-filtered facts
(selected action, factors, evidence) — never a raw prompt or private model
reasoning — and its output is parsed against a strict schema that rejects
any field it wasn't asked for. See
[How to enable live LLM explanations](../how-to/llm-explanations.md) for the
full safety-interlock details, failure handling, and a real disclosure-policy
permutation matrix run against this same model.

## What this flow deliberately does not do

- It does not pass raw prompts, arbitrary graph state, or credentials as
  canonical artifacts — only explicit, structured evidence/decision events.
- It does not require an LLM call to produce an explanation — the default
  engine is deterministic.
- It does not require picking a storage/observability backend up front —
  register one later via `runtime.register(...)` without touching this code.

## Next steps

- [Concepts overview](../concepts/index.md) — the full canonical model
  (execution, provenance, evidence, decisions, attribution, explanations,
  policies), each with a real JSON example.
- [Configuration](../api/config.md) — every `XAIConfig` parameter, with a
  worked example of its effect.
- [How-to guides](../how-to/index.md) — interrupts, MCP tools, multi-agent
  correlation, disclosure policies, failure modes.

