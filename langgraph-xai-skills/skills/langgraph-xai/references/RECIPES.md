# langgraph-xai recipes

Complete patterns for common integration tasks. Each one follows a tested
example in the repository: <https://github.com/smuniharish/langgraph-xai/tree/master/examples>.

## Contents

1. [Instrument a graph and explain a decision](#1-instrument-a-graph-and-explain-a-decision)
2. [Synchronous graphs and nodes](#2-synchronous-graphs-and-nodes)
3. [Prebuilt agents](#3-prebuilt-agents)
4. [Human-in-the-loop](#4-human-in-the-loop)
5. [Different explanations per audience](#5-different-explanations-per-audience)
6. [Keep records in your database](#6-keep-records-in-your-database)
7. [Send events to a tracing backend](#7-send-events-to-a-tracing-backend)
8. [Choose a failure mode](#8-choose-a-failure-mode)
9. [LLM-phrased explanations](#9-llm-phrased-explanations)
10. [Record work outside a graph](#10-record-work-outside-a-graph)
11. [Correlate runs across agents and services](#11-correlate-runs-across-agents-and-services)

## 1. Instrument a graph and explain a decision

A complete program. Nodes record evidence and the decision; the caller keeps
the run and explains the decision to an auditor.

```python
import asyncio
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from langgraph_xai import Audience, DecisionFactor, DecisionType, EvidenceType, XAIRuntime

xai = XAIRuntime(application_id="payments", tenant_id="acme-bank", graph_id="fraud-review")


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
    run = xai.current_run
    assert run is not None
    selected = "HUMAN_REVIEW" if state["risk_score"] >= 0.8 else "AUTO_APPROVE"
    evidence_ids = [item.id for item in run.evidence]
    await xai.record_decision(
        selected,
        decision_type=DecisionType.ROUTING,
        candidate_actions=["AUTO_APPROVE", "HUMAN_REVIEW"],
        evidence_ids=evidence_ids,
        factors=[
            DecisionFactor(
                name="fraud_risk_score", value=state["risk_score"], evidence_ids=evidence_ids
            )
        ],
        confidence=0.93,
    )
    return {"route": selected}


builder = StateGraph(Review)
builder.add_node("score_risk", score_risk)
builder.add_node("route", route)
builder.add_edge(START, "score_risk")
builder.add_edge("score_risk", "route")
builder.add_edge("route", END)
graph = xai.instrument(builder.compile())


async def main() -> None:
    with xai.collect_runs() as runs:
        result = await graph.ainvoke({"amount": 9200.0})
    (run,) = runs
    explanation = await xai.explain_decision(run.decisions[-1], audience=Audience.AUDITOR, run=run)
    print(result["route"], explanation.summary, explanation.reasons)


asyncio.run(main())
```

- The graph's output is unchanged. `run.execution` holds the nodes and state
  changes; `run.evidence` and `run.decisions` hold what the nodes recorded.
- Record a decision where it is made, with its alternatives and the evidence
  it relied on. Factors with `evidence_ids` drive attribution.
- Link derived data with `record_provenance(source_id, target_id, "DERIVED_FROM")`,
  for example from a transaction URI to the evidence computed from it.

## 2. Synchronous graphs and nodes

`invoke`, `stream`, and `batch` are recorded like their async forms. Inside a
synchronous node, run a recording coroutine with `run_sync`:

```python
def score_risk(state: Review) -> Review:
    risk_score = 0.91 if state["amount"] > 5000 else 0.12
    xai.run_sync(xai.record_evidence(EvidenceType.TOOL_RESULT, summary=f"Scored {risk_score:.2f}."))
    return {"risk_score": risk_score}


with xai.collect_runs() as runs:
    result = graph.invoke({"amount": 9200.0})
explanation = xai.run_sync(xai.explain_decision(runs[0].decisions[-1], run=runs[0]))
```

The current run reaches tools, middleware, and subgraphs through context
variables. In a thread you start yourself, pass `run=` explicitly.

## 3. Prebuilt agents

`create_agent` and `create_deep_agent` return compiled graphs. Instrument the
agent; tool calls are captured automatically. Record the decision in
middleware once the model has finished:

```python
from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage


class DecisionRecorder(AgentMiddleware):
    def __init__(self, xai: XAIRuntime) -> None:
        super().__init__()
        self.xai = xai

    async def aafter_model(self, state, runtime):
        messages = state["messages"]
        if getattr(messages[-1], "tool_calls", None):
            return None  # the model asked for another tool
        results = [message for message in messages if isinstance(message, ToolMessage)]
        evidence = [
            await self.xai.record_evidence(
                EvidenceType.TOOL_RESULT,
                summary=f"{message.name} returned {message.text}.",
                content_reference=f"tool-call://{message.tool_call_id}",
            )
            for message in results
        ]
        score = max((float(message.text) for message in results), default=0.0)
        await self.xai.record_decision(
            "ESCALATE_FOR_REVIEW" if score >= 0.8 else "NO_ACTION",
            decision_type=DecisionType.ESCALATION,
            candidate_actions=["ESCALATE_FOR_REVIEW", "NO_ACTION"],
            evidence_ids=[item.id for item in evidence],
        )
        return None


agent = create_agent(model, tools=[check_fraud_risk], middleware=[DecisionRecorder(xai)])
with xai.collect_runs() as runs:
    await xai.instrument(agent).ainvoke({"messages": [{"role": "user", "content": question}]})
```

An agent called inside a node of an instrumented graph joins that graph's run.

## 4. Human-in-the-loop

Compile with a checkpointer and pass a `thread_id`. Nothing else is needed to
record interrupts, answers, checkpoints, and the link between the runs:

```python
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command, interrupt


def human_review(state: WireTransfer) -> WireTransfer:
    approved = interrupt({"question": "Approve this wire transfer?", "amount": state["amount"]})
    return {"approved": bool(approved)}


graph = xai.instrument(builder.compile(checkpointer=InMemorySaver()))
thread = {"configurable": {"thread_id": "wire-42"}}

with xai.collect_runs() as runs:
    await graph.ainvoke({"amount": 9000.0}, thread)  # run 1: interrupted
    await graph.ainvoke(Command(resume=True), thread)  # run 2: completed
paused, resumed = runs
assert resumed.execution.continuation_of == paused.run_id

await xai.record_human_interaction(
    HumanInteractionType.APPROVAL, actor_reference="reviewer:ana", run=resumed
)
```

- The paused run has an `interrupt` interaction with the payload in
  `metadata["value"]`; the resumed run has a `resume` interaction with the
  answer and the same interrupt ID in `request_reference`.
- Each run records the checkpoint it continued from (`restored=True`) and the
  last checkpoint it wrote. Load one with
  `graph.aget_state({"configurable": {"thread_id": ..., "checkpoint_id": ...}})`.
- Retries after a failure and replays from a past checkpoint are linked the
  same way. Static breakpoints are recorded as interrupts with
  `pending_nodes`.
- Use a durable checkpointer (PostgreSQL or SQLite saver) in production, so
  links survive restarts.

## 5. Different explanations per audience

A `PolicyProvider` decides which explanation sections each audience may see.
Withheld sections are announced in `explanation.disclosure`.

```python
from langgraph_xai import (
    Audience,
    ExplanationContext,
    PolicyAction,
    PolicyDecision,
    PolicyProvider,
)


class CustomerSafePolicy:
    """End users see the outcome and reasons; other audiences see everything."""

    async def evaluate(self, context: ExplanationContext, action: PolicyAction) -> PolicyDecision:
        end_user = context.audience == Audience.END_USER
        return PolicyDecision(
            context=context.execution.context,
            policy_id="customer-safe",
            action=action,
            allowed=True,
            audience=context.audience,
            denied_fields={"contributing_factors", "supporting_evidence"} if end_user else set(),
            reason="Customers receive the outcome and reasons only." if end_user else None,
        )


xai.register(PolicyProvider, CustomerSafePolicy())
```

- Withholding `contributing_factors` also removes factor values from
  `reasons`.
- `allowed_fields`, when non-empty, is an allowlist of sections.
- Test every audience, and check the serialized explanation for values that
  must never appear. Start from `assets/test_disclosure_policy.py`.

## 6. Keep records in your database

Executions, events, and provenance links go to the `ProvenanceStore`.
Subclass it and register the instance:

```python
from collections.abc import AsyncIterator, Sequence

from langgraph_xai import ExecutionContext, ProvenanceLink, ProvenanceStore
from langgraph_xai.storage import StoreQuery


class DatabaseStore(ProvenanceStore):
    async def write(self, item) -> None:
        """Upsert by record type and str(item.id); the latest write wins."""

    async def get(self, entity_id: str):
        """Return the record whose id is entity_id, or None."""

    async def query(self, query: StoreQuery) -> AsyncIterator:
        """Yield the matching records of one application and tenant, in a stable order."""
        for item in await self.select(query):  # your database access
            yield item

    async def parents(
        self, entity_id: str, *, context: ExecutionContext
    ) -> Sequence[ProvenanceLink]:
        """Return the links whose target is entity_id, within context.run_id."""

    async def children(
        self, entity_id: str, *, context: ExecutionContext
    ) -> Sequence[ProvenanceLink]:
        """Return the links whose source is entity_id, within context.run_id."""

    async def close(self) -> None:
        """Release connections."""


xai.register(ProvenanceStore, DatabaseStore())
```

- `write` must be an idempotent upsert: an `Execution` is written at start,
  at finish, and again when a record is added after it finished.
- `query` returns records of one application and tenant, in a stable order.
  `parents` and `children` return links of one run. `lineage` is inherited.
- `examples/postgres_store.py` is a complete, tested PostgreSQL
  implementation to copy.
- Evidence, decisions, and memory references are not written to the store.
  Persist them with a plugin:

```python
class DecisionArchive:
    async def record(self, artifact) -> None: ...  # Evidence, Decision, MemoryReference, ...
    async def flush(self) -> None: ...
    async def close(self) -> None: ...


xai = XAIRuntime(plugins=(DecisionArchive(),))
```

## 7. Send events to a tracing backend

One `ObservabilityProvider` receives every event. Install the extra first.

```python
from langgraph_xai import ObservabilityProvider, OpenTelemetryObservability

xai.register(
    ObservabilityProvider,
    OpenTelemetryObservability(tracer_provider=provider, owns_provider=True),
)
```

| Backend | Extra | Provider |
| --- | --- | --- |
| LangSmith | `langgraph-xai[langsmith]` | `LangSmithObservability(project_name="...")` |
| Langfuse | `langgraph-xai[langfuse]` | `LangfuseObservability()` |
| OpenTelemetry | `langgraph-xai[otel]` | `OpenTelemetryObservability(tracer_provider=...)` |

Credentials come from each SDK's own environment variables. Call
`await xai.close()` at shutdown so batched data is sent.

## 8. Choose a failure mode

```python
from langgraph_xai import FailureMode, XAIConfig, XAIRuntime

xai = XAIRuntime(XAIConfig(failure_mode=FailureMode.FAIL_CLOSED))
```

| Mode | When an instrumentation operation fails |
| --- | --- |
| `FAIL_OPEN` (default) | The error goes to `xai.errors` and the graph continues. |
| `FAIL_CLOSED` | `XAIInstrumentationError` is raised, also from inside the graph call. |
| `STRICT` | Like `FAIL_CLOSED`, and records may not be dropped: evidence and decisions need a plugin, and executions need a store or observability provider. |

Explanations fail closed in every mode. A slow backend is bounded by
`operation_timeout_seconds`.

## 9. LLM-phrased explanations

The structured engine is deterministic and needs no model. To have a model
phrase the explanation, both opt-ins are required:

```python
from langgraph_xai import ExplanationEngine, LLMExplanationEngine, XAIConfig, XAIRuntime

xai = XAIRuntime(XAIConfig(llm_explanation_enabled=True, operation_timeout_seconds=60))
xai.register(ExplanationEngine, LLMExplanationEngine(model, enabled=True, timeout=45))
```

The model receives only the policy-filtered record and is told which sections
were withheld. Its reply is validated; an invalid or late reply raises
`XAIInstrumentationError`, so keep a structured fallback for that case.

## 10. Record work outside a graph

For code that does not run through an instrumented graph, manage the run
yourself and pass it to every call:

```python
run = await xai.start_run({"metadata": {"trace_id": "job-42"}})
try:
    evidence = await xai.record_evidence("rule", summary="Limit exceeded.", run=run)
    decision = await xai.record_decision("REJECT", evidence_ids=[evidence.id], run=run)
except BaseException as error:
    await xai.finish_run(run, error)
    raise
await xai.finish_run(run)
explanation = await xai.explain_decision(decision, run=run)
```

Never combine a manual run with an instrumented call for the same work.

## 11. Correlate runs across agents and services

Pass identifiers in the LangChain config of each call:

```python
await graph.ainvoke(
    payload,
    {
        "metadata": {"trace_id": "req-8841", "xai_tenant_id": "globex"},
        "configurable": {"thread_id": "review-42"},
    },
)
```

- `trace_id` ties runs of different graphs and services to one request, and
  observability adapters attach it as `xai.trace_id`.
- `xai_application_id`, `xai_tenant_id`, `xai_graph_id`, and `xai_run_id`
  override the runtime's defaults for one call.
- Query a store with `StoreFilter(application_id=..., tenant_id=..., run_id=...)`.
