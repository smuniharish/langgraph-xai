# Configuration

Every setting belongs to one `XAIRuntime`. Nothing is process-global, and the
core never reads environment variables, so two runtimes in one process (one per
tenant, or one per test) cannot affect each other.

```python
from langgraph_xai import CaptureMode, FailureMode, XAIConfig, XAIRuntime

xai = XAIRuntime(
    XAIConfig(
        capture_state=CaptureMode.DELTA,
        failure_mode=FailureMode.FAIL_OPEN,
        max_concurrency=32,
        operation_timeout_seconds=10.0,
    ),
    application_id="payments",
    tenant_id="acme-bank",
    graph_id="fraud-review",
)
```

`XAIConfig` is immutable. To change a setting, build a new config and a new
runtime.

## Settings

| Setting | Default | Meaning |
| --- | --- | --- |
| `capture_state` | `DELTA` | How much of each node's state change is recorded; see [State capture](#state-capture). |
| `capture_fields` | empty | State keys recorded in `SELECTIVE` mode. |
| `capture_checkpoints` | `True` | For a graph with a checkpointer and a `thread_id`, read the thread's state to record checkpoints, static breakpoints, and `continuation_of`. See [how runs are linked](../how-to/interrupts.md#how-runs-are-linked). |
| `failure_mode` | `FAIL_OPEN` | What an instrumentation failure does; see [Failure modes](#failure-modes). |
| `llm_explanation_enabled` | `False` | Allows an LLM-backed explanation engine to run. See [LLM-phrased explanations](../how-to/llm-explanations.md). |
| `max_concurrency` | `32` | Instrumentation operations (writes, emits, policy checks, plugin calls) in flight at once, across all threads and event loops. |
| `operation_timeout_seconds` | `10.0` | Upper bound for one operation, including the wait for a concurrency slot. |

## Identity of a run

Each run is stamped with an `ExecutionContext`. The runtime's `application_id`,
`tenant_id`, and `graph_id` are the defaults. A LangChain config can override
them per call and adds thread and trace identifiers:

```python
await graph.ainvoke(
    payload,
    {
        "metadata": {"xai_tenant_id": "globex", "trace_id": "req-8841"},
        "configurable": {"thread_id": "review-42"},
    },
)
```

| Source | Becomes |
| --- | --- |
| `metadata["xai_application_id"]`, `["xai_tenant_id"]`, `["xai_graph_id"]` | The run's application, tenant, and graph IDs |
| `metadata["xai_run_id"]` (a UUID) | The run ID, to reuse an ID from your own system. Otherwise a random UUID. |
| `metadata["trace_id"]` | `trace_id`, for correlation with tracing tools |
| `configurable["thread_id"]`, `["checkpoint_id"]` | `thread_id` and `checkpoint_id` |
| Other metadata keys | `ExecutionContext.metadata`, after [redaction](../concepts/policies.md#redaction) |

Instrumented calls add the run ID to the metadata the graph receives, under
`RUN_ID_METADATA_KEY` (`"langgraph_xai_run_id"`), so nodes can read it and
LangGraph stores it with each checkpoint. It is not copied into
`ExecutionContext.metadata`.

## State capture

Instrumented graphs record each node's state change as a `StateTransition`. The
capture mode decides which keys are recorded. Below, one transition is recorded
in every mode: `risk_score` changes, `api_key` changes, and `amount` and
`segment` do not.

```python
before = {"amount": 9200.0, "risk_score": None, "api_key": "sk-live-1", "segment": "retail"}
after = {"amount": 9200.0, "risk_score": 0.91, "api_key": "sk-live-2", "segment": "retail"}
```

| Mode | Configuration | Recorded `(path, before, after)` |
| --- | --- | --- |
| `DELTA` | default | `('risk_score', None, 0.91)` |
| `FULL` | | `('amount', 9200.0, 9200.0)`, `('risk_score', None, 0.91)`, `('api_key', '[not captured]', '[not captured]')`, `('segment', 'retail', 'retail')` |
| `SELECTIVE` | `capture_fields={"segment", "risk_score"}` | `('risk_score', None, 0.91)` |
| `CUSTOM` | `custom_state_capture=risk_band` | `('risk_band', None, 'high')` |
| `NONE` | | nothing |

- `DELTA` records only changed keys.
- `FULL` records every key, changed or not.
- `SELECTIVE` records the changed keys among `capture_fields`.
- `CUSTOM` records the mapping returned by the callable you pass to
  `XAIRuntime(custom_state_capture=...)`. It receives the state before and after
  the node. Here `risk_band` returned `{"risk_band": "high"}`.
- `NONE` turns state capture off.

Credential-named keys such as `api_key`, `password`, `authorization`, or
`session_token` never have their values recorded. `FULL` lists them as
`[not captured]`, and the other modes leave them out. Values are converted to
JSON-safe form before storage; see [Redaction](../concepts/policies.md#redaction).

## Providers

Every capability is a small protocol with a working default. Replace any of
them with `xai.register(Protocol, provider)`:

| Capability | Default | Alternatives |
| --- | --- | --- |
| `ProvenanceStore` | `InMemoryProvenanceStore` | Your subclass of `ProvenanceStore`, such as the [PostgreSQL store example](../examples/postgres-store.md) |
| `ObservabilityProvider` | `NoOpObservability` | [LangSmith](../integrations/langsmith.md), [Langfuse](../integrations/langfuse.md), [OpenTelemetry](../integrations/opentelemetry.md) |
| `CapturePolicy` | `DefaultCapturePolicy` (allows every event) | Your own, to drop events |
| `PolicyProvider` | `DefaultPolicyProvider` | Your own, to [scope disclosure](../how-to/disclosure-policies.md) |
| `AttributionEngine` | `HybridAttribution` | `EvidenceAttribution`, `RuleBasedAttribution`, your own |
| `ExplanationEngine` | `StructuredExplanationEngine` | [`LLMExplanationEngine`](../how-to/llm-explanations.md), your own |

`XAIPlugin` instances, passed as `XAIRuntime(plugins=(...))`, receive every
evidence, decision, and memory record as it is created. See
[Extensibility](../architecture/plugins.md).

## Failure modes

An instrumentation operation can fail: a store write raises, an exporter times
out, a policy provider errors. `failure_mode` decides what that means for your
graph:

| Mode | Behavior |
| --- | --- |
| `FAIL_OPEN` | The error is kept in `xai.errors` (the last 100) and the graph continues. |
| `FAIL_CLOSED` | The error is raised as `XAIInstrumentationError`, including from inside a graph call. |
| `STRICT` | Like `FAIL_CLOSED`, and records may not be dropped silently. Evidence and decisions need at least one plugin, and execution records need a store or observability provider. |

A call that cannot be recorded, such as one using LangGraph's experimental v3
streaming protocol, counts as a failed operation too; see
[Supported calls](../integrations/langgraph.md#supported-calls).

Explanations are the exception. `explain` and `explain_decision` raise
`XAIInstrumentationError` in every mode when the policy, attribution, or engine
fails, because a partial or unfiltered explanation is never returned. See
[Configure failure modes](../how-to/failure-modes.md) for real output.

## Credentials

Provider SDKs read their own environment variables: `LANGSMITH_API_KEY`,
`LANGFUSE_PUBLIC_KEY`/`LANGFUSE_SECRET_KEY`, `OTEL_EXPORTER_OTLP_ENDPOINT`, or
the database URL your application passes to its store.
`langgraph-xai` never copies these values into records. Their presence does not
enable anything by itself: a provider is active only after you register it.
