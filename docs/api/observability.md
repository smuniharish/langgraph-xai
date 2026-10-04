# Observability

Adapters that forward canonical events to tracing backends. Each adapter
belongs to an extra: `langsmith`, `langfuse`, or `otel`. See
[Integrations](../integrations/index.md) for setup and
[Observability architecture](../architecture/observability.md) for the
guarantees they share.

```python
from langgraph_xai import ObservabilityProvider, OpenTelemetryObservability

xai.register(ObservabilityProvider, OpenTelemetryObservability(tracer_provider=provider))
```

## Adapters

::: langgraph_xai.observability.langsmith.LangSmithObservability

::: langgraph_xai.observability.langfuse.LangfuseObservability

::: langgraph_xai.observability.otel.OpenTelemetryObservability

::: langgraph_xai.observability.noop.NoOpObservability

## Building an adapter

::: langgraph_xai.observability.base.ObservabilityAdapter

::: langgraph_xai.observability.base.correlation_fields

::: langgraph_xai.observability.base.event_payload

::: langgraph_xai.observability.langfuse.langfuse_trace_context

## Errors

::: langgraph_xai.observability.errors.ObservabilityAdapterError

::: langgraph_xai.observability.errors.AdapterClosedError

::: langgraph_xai.observability.errors.OptionalDependencyError
