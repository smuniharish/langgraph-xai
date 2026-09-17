# Integrations

Integrations are optional adapters around a provider-neutral explainability
core. Enabling one should not be required to create local explainability
artifacts.

- [LangGraph](langgraph.md) explains the execution boundary and how
  instrumentation attaches to a compiled graph.
- [LangSmith](langsmith.md) shows how to register the `LangSmithObservability`
  adapter; [LangSmith comparison](langsmith-vs-langgraph-xai.md) explains the
  complementary responsibilities precisely.
- [Langfuse](langfuse.md) shows how to register the `LangfuseObservability`
  adapter.
- [OpenTelemetry](opentelemetry.md) shows how to register the
  `OpenTelemetryObservability` adapter with any OTel exporter.

When configuring an integration, review its credentials, network destination,
retention, and access controls independently from this project.
