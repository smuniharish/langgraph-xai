# Observability

An `ObservabilityProvider` receives every canonical event the runtime emits
(`ExecutionStartedEvent`, `ToolExecutionEvent`, `StateTransitionEvent`, …) and
forwards it to a telemetry backend. xgraph does not replace Langfuse,
OpenTelemetry, or LangSmith — it adds a semantic layer on top of whichever
one you already use.

## `NoOpObservability` (default)

Registered automatically. Discards every event — the correct choice when
you only need provenance/evidence/decision records, not a telemetry export.

## `LangfuseObservability`

```python
from langfuse import Langfuse
from langgraph_xai.observability import LangfuseObservability
from langgraph_xai.core.protocols import ObservabilityProvider

runtime.register(ObservabilityProvider, LangfuseObservability(Langfuse()))
```

Emits each event as a Langfuse span (`start_as_current_observation`) when
available, falling back to `create_event(...)` for older SDKs — correlation
fields (`run_id`, `trace_id`, `application_id`, `tenant_id`) are attached as
span metadata, and the canonical payload is attached as `input`.

## `OpenTelemetryObservability`

```python
from opentelemetry import trace
from langgraph_xai.observability import OpenTelemetryObservability

runtime.register(
    ObservabilityProvider,
    OpenTelemetryObservability(trace.get_tracer("my-service")),
)
```

Emits each event as an OTel span (`start_as_current_span`), with
correlation fields and the canonical payload set as span attributes —
works with any configured OTel exporter (console, OTLP, Jaeger, …), since
the adapter only depends on the `Tracer`/`Span` API surface.

## `LangSmithObservability`

```python
from langsmith import Client
from langgraph_xai.observability import LangSmithObservability

runtime.register(ObservabilityProvider, LangSmithObservability(Client()))
```

Emits each event as a LangSmith run (`client.create_run(...)`), with
`trace_id`/`parent_run_id` carried over from the canonical event's context so
xgraph's records correlate with LangSmith's own tracing tree. See
[LangSmith comparison](../integrations/langsmith-vs-langgraph-xai.md) for
how this differs from LangSmith's own tracing.

## Reference

::: langgraph_xai.observability.NoOpObservability

::: langgraph_xai.observability.LangfuseObservability

::: langgraph_xai.observability.OpenTelemetryObservability

::: langgraph_xai.observability.LangSmithObservability
