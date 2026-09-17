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

## Build a real agent, record its decision, and explain it

Most real LangGraph applications are built with
[`langchain.agents.create_agent`](https://python.langchain.com/docs/how_to/agent_executor/)
rather than a hand-written `StateGraph` — it still compiles to an ordinary
LangGraph runnable, so `runtime.instrument(...)` needs no special-casing
for it. The one design choice worth being deliberate about is *where* to
hook in a decision: `create_agent` accepts `AgentMiddleware`, and its
`aafter_model` hook fires once per model turn — exactly where you can
distinguish "the model just chose to call a tool" from "the model produced
a final answer," which is the point at which you want to record a
`Decision` and explain it.

```python
from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware
from langchain.tools import tool
from langchain_openai import ChatOpenAI

from langgraph_xai import Decision, DecisionFactor
from langgraph_xai.core import ExplanationContext


@tool
def check_fraud_risk(transaction_id: str, amount: float) -> str:
    """Look up the fraud risk score for a transaction."""
    return "0.91" if amount > 5000 else "0.12"


class DecisionRecordingMiddleware(AgentMiddleware):
    """Records the agent's final answer as a Decision and explains it.

    Runs after every model turn; skips turns where the model is still
    calling a tool, and only records/explains once it produces a final
    answer with no further tool calls.
    """

    def __init__(self, xai_runtime) -> None:
        super().__init__()
        # Store the XAIRuntime under its own name, not "runtime": LangGraph
        # injects its own Runtime context object as aafter_model's second
        # parameter, under that exact name, and would silently shadow it.
        self.xai_runtime = xai_runtime
        self.decision: Decision | None = None
        self.explanation_summary: str | None = None

    async def aafter_model(self, state: dict[str, Any], runtime: Any) -> None:
        last_message = state["messages"][-1]
        if getattr(last_message, "tool_calls", None):
            return None  # still calling a tool; not a final decision yet

        self.decision = await self.xai_runtime.record_decision(
            "FINAL_RESPONSE",
            decision_type="final_response",
            factors=[DecisionFactor(name="answer_available", value=True)],
        )
        explanation = await self.xai_runtime.explain(
            ExplanationContext(
                execution=self.xai_runtime.current_run.execution,
                decision=self.decision,
                audience="end_user",
            )
        )
        self.explanation_summary = explanation.summary
        return None


model = ChatOpenAI(base_url="...", api_key="...", model="gpt-5.6-luna")
middleware = DecisionRecordingMiddleware(runtime)
agent = create_agent(
    model,
    tools=[check_fraud_risk],
    system_prompt="You are a fraud review assistant. Use the tool, then answer briefly.",
    middleware=[middleware],
)

instrumented = runtime.instrument(agent)
result = await instrumented.ainvoke(
    {"messages": [{"role": "user", "content": "Transaction txn-8841 is $9200. Is it risky?"}]}
)
print(middleware.decision.selected_action, "|", middleware.explanation_summary)
```

`instrument(...)` wraps `invoke`/`ainvoke`/`stream`/`astream`/`batch`/
`abatch` transparently — your agent's inputs and outputs are unchanged;
every tool call the agent makes (`check_fraud_risk` here) is captured as a
`ToolExecution` alongside the `Decision` the middleware records. `runtime.current_run`
is only set *while* an instrumented call is in flight, which is exactly why
the decision and explanation are recorded from inside the middleware hook
rather than after `ainvoke` returns — see
[How-to: explain a decision after the run finishes](../how-to/explain-after-run.md)
for the pattern to use instead when a decision is only known *after* the
agent call returns (e.g. in a web handler, not inside any hook).

The full runnable version of this script, including verification
assertions, lives in
[`examples/create_agent_decision_explanation.py`](https://github.com/samamuniharish/langgraph-xai/blob/main/examples/create_agent_decision_explanation.py).
Real captured output from running it (the agent's own free-text reply is
model-generated and will vary in wording across calls; `selected_action`
and `explanation` are what xgraph itself records and reproduces exactly):

```bash
$ uv run --system-certs python examples/create_agent_decision_explanation.py
--- Final agent message ---
Yes, this transaction is high risk, with a fraud risk score of 0.91.

--- Recorded decision + explanation ---
selected_action: FINAL_RESPONSE
explanation: The end_user explanation is based on the selected action 'FINAL_RESPONSE'.

Verified: the Decision and Explanation were produced from inside
create_agent's own after-model hook, with no canonical model built by hand
in application code.
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
that wraps one. This is the exact same agent as above — the same tool,
the same middleware, the same `record_decision`/`explain` calls — with
only the runtime construction and the registered `ExplanationEngine`
changed:

```python
from langgraph_xai import XAIConfig
from langgraph_xai.core.protocols import ExplanationEngine
from langgraph_xai.explanation import LLMExplanationEngine

runtime = XAIRuntime(graph_id="fraud-review", config=XAIConfig(llm_explanation_enabled=True))
runtime.register(ExplanationEngine, LLMExplanationEngine(model, enabled=True, timeout=30.0))

# `check_fraud_risk`, `DecisionRecordingMiddleware`, `model`, and `agent`
# construction are unchanged from the section above.
middleware = DecisionRecordingMiddleware(runtime)
agent = create_agent(model, tools=[check_fraud_risk], middleware=[middleware])
instrumented = runtime.instrument(agent)
result = await instrumented.ainvoke(
    {"messages": [{"role": "user", "content": "Transaction txn-8841 is $9200. Is it risky?"}]}
)
print(middleware.decision.selected_action, "|", middleware.explanation_summary)
```

Real captured output, one real call against an OpenAI-compatible model
(`gpt-5.6-luna`), running this exact flow end to end:

```text
FINAL_RESPONSE | An answer is available.
```

This scenario's only `Decision` factor is `answer_available=True` — the
LLM engine phrases *exactly* the facts it is given, so a decision with a
richer factor set (a `fraud_risk_score` alongside a `review_threshold`)
produces a correspondingly richer sentence. The model only ever receives
already-captured, policy-filtered facts (selected action, factors,
evidence) — never a raw prompt or private model reasoning — and its
output is parsed against a strict schema that rejects any field it wasn't
asked for. For that richer, `HUMAN_REVIEW`-outcome variant and the full,
real JSON `Explanation` this engine returns, see
[How to enable live LLM explanations](../how-to/llm-explanations.md) — it
also covers the safety-interlock details, failure handling, and a real
disclosure-policy permutation matrix run against this same model.

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
- [create_agent nested inside a StateGraph node](../examples/create-agent-nested.md)
  — the same pattern as above, one step deeper: an LLM agent built and
  invoked *inside* a plain node of a larger hand-written graph.

