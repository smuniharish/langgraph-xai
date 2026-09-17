# LangGraph

## Kid-level view

LangGraph runs the graph. The explainability runtime watches agreed-upon
boundaries and adds labeled notes around it.

## Production view

Keep graph definitions, state transitions, checkpoints, and execution control
in LangGraph. Supply explicit application evidence and decision events to the
explainability layer; do not assume every internal state field is safe or
available.

## Instrument a compiled graph

`XAIRuntime.instrument(...)` wraps a compiled `StateGraph` (or any
`Runnable`) transparently — it forwards every LangGraph method
(`invoke`/`ainvoke`/`stream`/`astream`/`batch`/`abatch`) to the original
graph and captures execution/tool/state records around each call, with no
change to your graph's inputs or outputs:

```python
from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph_xai import DecisionFactor, XAIRuntime


class State(TypedDict, total=False):
    query: str
    answer: str


def answer(state: dict) -> dict:
    return {"answer": f"Echo: {state['query']}"}


builder = StateGraph(State)
builder.add_node("answer", answer)
builder.add_edge(START, "answer")
builder.add_edge("answer", END)
graph = builder.compile()

runtime = XAIRuntime(graph_id="minimal")
instrumented = runtime.instrument(graph)

result = await instrumented.ainvoke({"query": "Why?"})
```

Real captured output, running this exact script
([`examples/minimal_langgraph.py`](https://github.com/samamuniharish/langgraph-xai/blob/main/examples/minimal_langgraph.py)):

```bash
$ uv run python examples/minimal_langgraph.py
{'query': 'Why?', 'answer': 'Echo: Why?'}
The end_user explanation is based on the selected action 'FINAL_RESPONSE'.
```

## Correlate a decision with its execution

Instrumentation captures *what ran*. Your application still owns *why* a
decision was made — record it explicitly, referencing the same execution
context so both artifacts join under one `run_id`:

```python
context = runtime.context_from_config()
decision = Decision(
    context=context,
    decision_type="routing",
    selected_action="FINAL_RESPONSE",
    factors=[DecisionFactor(name="answer_available", value=True)],
)
explanation = await runtime.explain(
    ExplanationContext(execution=execution, decision=decision, audience="end_user")
)
```

## Human-in-the-loop interrupts

LangGraph's `interrupt()`/`Command(resume=...)` cycle is captured
automatically as a `HumanInteraction` record (type `interrupt`, then
`resume`) — no special-casing required on your part. See
[Human-in-the-loop interrupts](../examples/interrupt-hitl.md) for the full,
real interrupt/resume trace, and
[How to handle interrupts](../how-to/interrupts.md) for the integration
steps.

## Mistakes to avoid

Correlate a node completion with a runtime execution ID and record a
policy-approved decision reference. Do not replace graph control flow with an
explanation adapter or infer private reasoning from a trace.


