# langgraph-xai

**Explainability for LangGraph applications: what ran, why it was decided, and
what each audience may see.**

`langgraph-xai` wraps a compiled LangGraph graph and records every run as
structured, versioned artifacts. Nodes, state changes, tools, retrievers, and
human-in-the-loop interrupts are captured automatically. Your code records the
evidence it relied on and the decisions it made. From those records the
runtime builds explanations for developers, auditors, business owners, or end
users, filtered by a disclosure policy you control.

![langgraph-xai architecture](assets/diagrams/architecture-overview.png)

## What you get

- **Automatic execution capture.** `xai.instrument(graph)` returns a drop-in
  wrapper that records `invoke`, `stream`, `batch`, `astream_events`, and the
  other Runnable entry points, sync and async. Inputs, outputs, and exceptions
  are unchanged.
- **Human-in-the-loop and checkpoints.** Interrupts and resumes are recorded
  with the reviewer's answer. For a graph with a checkpointer, each run is
  linked to its checkpoints, and a resumed run points back to the run it
  continues.
- **Evidence, decisions, and provenance.** `record_evidence`,
  `record_decision`, and `record_provenance` capture the basis of a decision as
  data. Nothing is inferred from model reasoning.
- **Audience-aware explanations.** `explain_decision` attributes the decision
  to its factors and evidence. A `PolicyProvider` decides which sections each
  audience may see. Withheld sections are reported, never silently dropped.
- **Safe by default.** Credential-named fields are redacted before anything is
  stored, LLM-phrased explanations require two explicit opt-ins, and
  instrumentation failures never break your graph unless you ask them to.
- **Provider-neutral.** Records are kept in memory by default; subclass
  `ProvenanceStore` to keep them in your database (a complete PostgreSQL store
  is included as an example). Forward events to LangSmith, Langfuse, or any
  OpenTelemetry backend. Extend everything through small, typed contracts.

## Thirty seconds

```python
from langgraph_xai import Audience, XAIRuntime

xai = XAIRuntime(application_id="payments", tenant_id="acme-bank")
graph = xai.instrument(builder.compile())

with xai.collect_runs() as runs:
    result = await graph.ainvoke({"amount": 9200.0})

(run,) = runs
explanation = await xai.explain_decision(run.decisions[0], audience=Audience.AUDITOR, run=run)
print(explanation.summary)  # The routing decision selected 'HUMAN_REVIEW'.
```

The [quickstart](getting-started/quickstart.md) builds this graph step by step.

## How it relates to tracing tools

LangSmith, Langfuse, and OpenTelemetry show **what ran**: run trees, spans,
latency, tokens. `langgraph-xai` records **why it was decided** and **who may
see the explanation**. The two work together: the bundled adapters send
`langgraph-xai` events to the tracing backend you already use. See
[LangSmith and langgraph-xai](integrations/langsmith-vs-langgraph-xai.md).

## Where to go next

| If you want to | Read |
| --- | --- |
| Install the package and explain your first decision | [Quickstart](getting-started/quickstart.md) |
| Understand the data model | [Concepts](concepts/index.md) |
| Solve a specific task | [How-to guides](how-to/index.md) |
| Run complete, tested programs | [Examples](examples/index.md) |
| Connect storage or a tracing backend | [Integrations](integrations/index.md) |
| See how the runtime works inside | [Architecture](architecture/overview.md) |
| Look up a class or method | [API reference](api/index.md) |
| Let a coding agent integrate it for you | [Agent Skills](agent-skills.md) |

## Status

`langgraph-xai` 1.0 is stable. The public API and the record schema follow
semantic versioning: minor releases add features without breaking your code or
your stored records.

Every release is typed and tested on Python 3.12 to 3.14, with 100% statement
and branch coverage and property-based tests. The integrations are exercised
against an OpenTelemetry Collector, an OpenAI-compatible LLM endpoint, and the
real LangSmith and Langfuse SDKs, and the PostgreSQL store example against a
real PostgreSQL server. Changes are listed in the
[changelog](https://github.com/smuniharish/langgraph-xai/blob/master/CHANGELOG.md).
