# langgraph-xai

`langgraph-xai` is a provider-neutral **explainability** layer for LangGraph
applications. It turns observable graph execution and application-supplied
context into structured execution, provenance, evidence, decision,
attribution, and explanation artifacts.

It is not a LangGraph replacement, a general observability platform, a
security middleware framework, or a recorder of private model reasoning.

## "Isn't this just LangSmith?" — no, and here's the precise boundary

This is the single most common misunderstanding, so it gets answered first,
not buried in an integrations page.

**LangSmith, Langfuse, and OpenTelemetry answer "what happened, and how do I
debug/monitor it?"** They are tracing, evaluation, and observability
platforms: run trees, spans, latencies, token counts, evaluation scores,
dashboards.

**`langgraph-xai` answers "why did the agent decide this, what evidence
supports it, and what am I allowed to disclose to whom?"** It is a
semantic model — `Execution → Provenance → Evidence → Decision →
Attribution → Explanation` — with an explicit, audience-aware disclosure
policy layer. It is not a trace viewer and does not compete with one.

| | LangSmith / Langfuse / OpenTelemetry | `langgraph-xai` |
| --- | --- | --- |
| Primary question | "What happened, and how fast?" | "Why, on what evidence, and who may see it?" |
| Core unit | Trace / span / run | `Evidence`, `Decision`, `Attribution`, `Explanation` |
| Disclosure control | Provider-level retention/access config | Per-audience `PolicyProvider`, enforced at capture *and* exposure |
| Requires a hosted service | Usually (LangSmith/Langfuse) or a collector (OTel) | No — in-process by default, storage is pluggable |
| Relationship to xgraph | **Consumed by xgraph** as an optional `ObservabilityProvider` adapter | Sits alongside, not instead of |

They compose, deliberately: xgraph can *forward* correlation IDs and
canonical events to whichever of these you already run (see
[Observability](architecture/observability.md)), while remaining the only
layer that produces a structured, policy-filtered `Explanation` object. Full
side-by-side detail: [LangSmith comparison](integrations/langsmith-vs-langgraph-xai.md).

## Start here

- [Quickstart](getting-started/quickstart.md)
- [Concepts](concepts/index.md)
- [Agent Skills](agent-skills.md)
- [Architecture overview](architecture/overview.md)
- [Architecture decisions (ADRs)](architecture/decisions.md)
- [Disclosure policy](architecture/disclosure-policy.md)
- [How-to guides](how-to/index.md)
- [Examples](examples/index.md)
- [LangSmith / Langfuse / OpenTelemetry comparison](integrations/langsmith-vs-langgraph-xai.md)
- [API overview](api/index.md)
- [Security guidance](operations/security.md)

## Current status

The core runtime, canonical data model, provider protocols, and the built-in
memory/PostgreSQL storage, OpenTelemetry/Langfuse observability, and
attribution/explanation engines are implemented and covered by an automated
test suite, including live integration tests run against real PostgreSQL,
OpenTelemetry Collector, and Langfuse deployments, real MCP tool servers, a
real `deepagents` deep agent, and a real LLM-backed explanation engine (see
[Testing](development/testing.md) and the [examples](examples/index.md), all
of which embed the actual captured output from those real runs). The
documentation distinguishes implemented behavior from planned capabilities
throughout.
