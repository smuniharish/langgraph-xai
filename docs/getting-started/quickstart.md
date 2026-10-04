# Quickstart

This guide instruments a two-node fraud-review graph, records the evidence and
decision it produces, and explains that decision to an auditor. It takes about
five minutes and needs no external services.

## Requirements

- Python 3.12 or newer
- LangGraph 1.x, 1.2.12 or newer, and LangChain Core 1.x, 1.6.6 or newer,
  installed automatically as dependencies

## Install

=== "pip"

    ```bash
    pip install langgraph-xai
    ```

=== "uv"

    ```bash
    uv add langgraph-xai
    ```

Optional integrations are installed as extras, for example
`pip install "langgraph-xai[langsmith,otel]"`:

| Extra | Adds | Used by |
| --- | --- | --- |
| `langsmith` | `langsmith` | [`LangSmithObservability`](../integrations/langsmith.md) |
| `langfuse` | `langfuse` | [`LangfuseObservability`](../integrations/langfuse.md) |
| `otel` | `opentelemetry-api`, `opentelemetry-sdk` | [`OpenTelemetryObservability`](../integrations/opentelemetry.md) |
| `llm-openai` | `langchain-openai` | [LLM-phrased explanations](../how-to/llm-explanations.md) |
| `all` | Every integration above | |

Storage needs no extra. Records are kept in memory by default, and a database
is used by subclassing `ProvenanceStore`, as in the
[PostgreSQL store example](../examples/postgres-store.md).

## 1. Create a runtime

An `XAIRuntime` owns the configuration and providers for one application. It
works with zero configuration: records go to an in-memory store, and
explanations are built deterministically without a model.

```python
from langgraph_xai import XAIRuntime

xai = XAIRuntime(application_id="payments", tenant_id="acme-bank", graph_id="fraud-review")
```

The three identifiers are stamped on every record, so runs from different
applications, tenants, and graphs never mix.

## 2. Record evidence and decisions in your nodes

Instrumentation captures *what ran*. Your nodes record *why*: the evidence they
relied on and the decision they made. `xai.current_run` is the run of the
instrumented call that is executing the node.

```python
from typing import TypedDict

from langgraph_xai import DecisionType, EvidenceType


class Review(TypedDict, total=False):
    amount: float
    risk_score: float
    route: str


async def score_risk(state: Review) -> Review:
    risk_score = 0.91 if state["amount"] > 5000 else 0.12
    await xai.record_evidence(
        EvidenceType.TOOL_RESULT,
        summary=f"Fraud model scored the transaction {risk_score:.2f}.",
        confidence=0.97,
    )
    return {"risk_score": risk_score}


async def route(state: Review) -> Review:
    run = xai.current_run  # the run of the instrumented call executing this node
    assert run is not None
    selected = "HUMAN_REVIEW" if state["risk_score"] >= 0.8 else "AUTO_APPROVE"
    await xai.record_decision(
        selected,
        decision_type=DecisionType.ROUTING,
        candidate_actions=["AUTO_APPROVE", "HUMAN_REVIEW"],
        evidence_ids=[item.id for item in run.evidence],
        confidence=0.93,
    )
    return {"route": selected}
```

## 3. Instrument the graph

Build and compile the graph as usual, then wrap it. The wrapper behaves exactly
like the compiled graph.

```python
from langgraph.graph import END, START, StateGraph

builder = StateGraph(Review)
builder.add_node("score_risk", score_risk)
builder.add_node("route", route)
builder.add_edge(START, "score_risk")
builder.add_edge("score_risk", "route")
builder.add_edge("route", END)
graph = xai.instrument(builder.compile())
```

## 4. Run the graph and explain the decision

`collect_runs()` hands you the run started by the call, so you can explain it
after the call returns.

```python
import asyncio

from langgraph_xai import Audience


async def main() -> None:
    with xai.collect_runs() as runs:
        result = await graph.ainvoke({"amount": 9200.0})
    (run,) = runs

    print(result)
    print([f"{node.node_id}: {node.status}" for node in run.execution.nodes])

    explanation = await xai.explain_decision(run.decisions[0], audience=Audience.AUDITOR, run=run)
    print(explanation.summary)
    print(explanation.reasons)


asyncio.run(main())
```

Output:

```text
{'amount': 9200.0, 'risk_score': 0.91, 'route': 'HUMAN_REVIEW'}
['score_risk: completed', 'route: completed']
The routing decision selected 'HUMAN_REVIEW'.
['Selected action: HUMAN_REVIEW.', 'Alternatives considered: AUTO_APPROVE.', 'Decision confidence: 0.93.']
```

The graph's output is unchanged. Alongside it, the run recorded an `Execution`
with both nodes and their state changes, the evidence, and the decision. The
explanation also carries attribution scores and evidence references; the
[fraud review example](../examples/full-explanation.md) prints the complete
object for two audiences.

## Synchronous graphs

`invoke`, `stream`, and `batch` are instrumented the same way. Recording
methods are coroutines, so a synchronous node runs them with `xai.run_sync`:

```python
def score_risk(state: Review) -> Review:
    risk_score = 0.91 if state["amount"] > 5000 else 0.12
    xai.run_sync(xai.record_evidence(EvidenceType.TOOL_RESULT, summary=f"Scored {risk_score:.2f}."))
    return {"risk_score": risk_score}
```

`run_sync` reuses one event loop per thread and carries the caller's context,
so the evidence lands in the run of the graph call that executes the node.

## Next steps

- Withhold internal scores from end users with a
  [disclosure policy](../how-to/disclosure-policies.md).
- Keep records in your database by subclassing `ProvenanceStore`, as in the
  [PostgreSQL store example](../examples/postgres-store.md), or forward them
  to [LangSmith](../integrations/langsmith.md),
  [Langfuse](../integrations/langfuse.md), or
  [OpenTelemetry](../integrations/opentelemetry.md).
- Choose how much state to capture and how failures behave in
  [Configuration](configuration.md).
- Learn the data model in [Concepts](../concepts/index.md).
