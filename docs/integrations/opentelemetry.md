# OpenTelemetry

`OpenTelemetryObservability` turns each `langgraph-xai` event into an
OpenTelemetry span. Any OTLP-compatible backend can then store and query the
explainability record next to your other telemetry: Jaeger, Grafana Tempo,
Honeycomb, Datadog, or an OpenTelemetry Collector.

```bash
pip install "langgraph-xai[otel]" opentelemetry-exporter-otlp-proto-http
```

The `otel` extra installs the OpenTelemetry API and SDK. Install the exporter
for your backend separately.

```python
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from langgraph_xai import ObservabilityProvider, OpenTelemetryObservability

provider = TracerProvider()
provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))  # OTEL_EXPORTER_OTLP_ENDPOINT
xai.register(
    ObservabilityProvider,
    OpenTelemetryObservability(tracer_provider=provider, owns_provider=True),
)
```

## What is exported

Each event is a zero-duration span named after its event type and stamped with
the event's own timestamp. Its parent is whatever span is current when the event
is recorded, so the events nest inside your application's existing traces.
Creating the span never changes the current span.

Real output from one instrumented call, captured with the SDK's in-memory
exporter:

```text
['execution.started', 'state.transition', 'node.execution', 'execution.completed']
```

Attributes of the `node.execution` span:

```json
{
  "xai.event_id": "a490eded-7b34-45c3-a39b-974d175d4d86",
  "xai.event_type": "node.execution",
  "xai.application_id": "payments",
  "xai.tenant_id": "acme-bank",
  "xai.graph_id": "fraud-review",
  "xai.run_id": "59e70028-a463-4688-ad68-a23c9fcae8ca",
  "xai.trace_id": "req-8841"
}
```

`xai.event_id` is the event's `id`. In addition, `xai.payload` holds the
complete canonical event as JSON. Its keys are `context`, `event_type`, `id`,
`node`, `schema_version`, `sequence`, and `timestamp`. `xai.thread_id` and
`xai.checkpoint_id` are added when the run has them.

## Provider ownership

| Constructor | Tracer from | `flush()` | `close()` |
| --- | --- | --- | --- |
| `OpenTelemetryObservability()` | The global tracer provider | No-op | No-op |
| `OpenTelemetryObservability(tracer_provider=p)` | `p` | Flushes `p` | No-op |
| `OpenTelemetryObservability(tracer_provider=p, owns_provider=True)` | `p` | Flushes `p` | Shuts `p` down |
| `OpenTelemetryObservability(tracer)` | The given tracer | No-op | No-op |

Call `await xai.close()` at shutdown, so batched spans are exported before the
process exits.
