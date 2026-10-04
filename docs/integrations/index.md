# Integrations

`langgraph-xai` instruments LangGraph and plugs into the storage and tracing
systems you already run. Every integration is optional and is installed as an
extra.

| Integration | Role | Extra | Class |
| --- | --- | --- | --- |
| [LangGraph](langgraph.md) | The graphs being explained | (core) | `XAIRuntime.instrument` |
| [LangSmith](langsmith.md) | Canonical events as a LangSmith trace | `langsmith` | `LangSmithObservability` |
| [Langfuse](langfuse.md) | Canonical events as Langfuse observations | `langfuse` | `LangfuseObservability` |
| [OpenTelemetry](opentelemetry.md) | Canonical events as spans, for any OTLP backend | `otel` | `OpenTelemetryObservability` |

Records are stored in memory by default. To store them in a database, subclass
`ProvenanceStore`; the [PostgreSQL store example](../examples/postgres-store.md)
is a complete implementation to start from.

![How canonical events reach each tracing backend](../assets/diagrams/observability-boundary.png)

One `ObservabilityProvider` is active per runtime. Each event reaches it once,
even if delivery is retried. Every backend receives the same `xai.*`
correlation attributes, so records can be joined across systems.

New to tracing tools? Start with
[LangSmith and langgraph-xai](langsmith-vs-langgraph-xai.md), which explains
how tracing and explainability complement each other.
