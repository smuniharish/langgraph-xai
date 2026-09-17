# Explain a decision after the run finishes

[Quickstart](../getting-started/quickstart.md) records the decision and
explains it *from inside the graph node that made it*, because
`runtime.current_run` is only set while an
[instrumented](../integrations/langgraph.md) call is in flight — it is
`None` again the moment `ainvoke(...)` returns.

Many real applications need the opposite shape: run the graph, return
control to a web handler or CLI command, and only then decide whether to
build and show an explanation (e.g. only for a `HUMAN_REVIEW` outcome).
For that, keep your own handle on the `Run` instead of relying on
`instrument(...)`:

```python
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from langgraph_xai import DecisionFactor, XAIRuntime
from langgraph_xai.core import ExplanationContext


class State(TypedDict, total=False):
    query: str
    answer: str


runtime = XAIRuntime(graph_id="fraud-review")


def answer(state: dict) -> dict:
    return {"answer": f"Echo: {state['query']}"}


builder = StateGraph(State)
builder.add_node("answer", answer)
builder.add_edge(START, "answer")
builder.add_edge("answer", END)
graph = builder.compile()

# Start the run yourself instead of using runtime.instrument(...), so
# run.execution survives past the graph call.
run = await runtime.start_run()
result = await graph.ainvoke({"query": "Why?"})

decision = await runtime.record_decision(
    "FINAL_RESPONSE",
    decision_type="routing",
    factors=[DecisionFactor(name="answer_available", value=True)],
    run=run,
)
await runtime.finish_run(run)

explanation = await runtime.explain(
    ExplanationContext(execution=run.execution, decision=decision, audience="end_user")
)
print(result["answer"], "|", explanation.summary)
```

Real captured output, running this exact flow:

```text
Echo: Why? | The end_user explanation is based on the selected action 'FINAL_RESPONSE'.
```

## What you trade away

Calling the raw `graph.ainvoke(...)` here — instead of
`runtime.instrument(graph).ainvoke(...)` — means node-level tool calls and
state transitions are **not** captured automatically for this run; only
the top-level `Execution` and whatever you explicitly record (via
`record_decision`, `record_evidence`, `record_tool`, …) are. `instrument(...)`
and this manual `start_run`/`finish_run` pattern are not composable for
the *same* call: passing an already-active `Run` into an instrumented
`ainvoke(...)` causes it to detect the surrounding run and skip attaching
its own capture callback, to avoid double-recording a call that is nested
inside a larger instrumented one (e.g. a subgraph invoked by a node).

If you need both full per-node capture *and* a post-hoc decision, record
the decision and evidence from inside the node that owns them (as in
[Quickstart](../getting-started/quickstart.md)) — that is the pattern
`runtime.instrument(...)` is designed around — and reserve this manual
pattern for graphs, or parts of your pipeline, where you are not relying
on automatic per-node capture in the first place.

## No canonical model is hand-built here either

Note what this page does *not* do: it never constructs `Execution`,
`Decision`, or `ProvenanceLink` directly. `record_decision(...)` builds and
persists the `Decision`; `run.execution` is the real, live `Execution` the
runtime already created in `start_run(...)`. The only object assembled by
hand is `ExplanationContext` — a reference to already-recorded objects
plus an audience, not a re-derivation of data recorded elsewhere.
