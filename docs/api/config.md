# Configuration

`XAIConfig` is the single object that controls a runtime's capture,
failure-handling, explanation, and concurrency behavior. It is immutable —
build a new instance and a new `XAIRuntime` to change settings, rather than
mutating one in place.

```python
from langgraph_xai import XAIConfig
from langgraph_xai.core.models import FailureMode

config = XAIConfig(failure_mode=FailureMode.STRICT, max_concurrency=8)
runtime = XAIRuntime(config=config)
```

Every field has a working default (see the table below), so `XAIConfig()`
with no arguments is a valid, production-safe starting point — override
only the parameters you need to change.

## Parameter reference

Most applications only ever set `capture_state` (or leave it at its default)
and `failure_mode`. The rest have working defaults and exist to be tuned,
not to be understood up front.

| Parameter | Type | Default | Use it to |
| --- | --- | --- | --- |
| `capture_state` | `CaptureMode` | `CaptureMode.DELTA` | Choose how much of each node's state change is recorded |
| `failure_mode` | `FailureMode` | `FailureMode.FAIL_OPEN` | Decide whether instrumentation failures are swallowed or raised |
| `llm_explanation_enabled` | `bool` | `False` | Permit an `ExplanationEngine` that calls a live LLM |
| `max_concurrency` | `int` (`>= 1`) | `32` | Bound concurrent instrumentation operations against your backend |
| `operation_timeout_seconds` | `float` (`> 0`) | `10.0` | Bound how long one instrumentation call may block the graph |
| `event_queue_size` | `int` (`>= 1`) | `1024` | Reserved for a future queued-dispatch mode; validated but not yet consumed |

### `capture_state`

Controls how much of a node's state change `record_state_delta` records:

| Value | Behavior |
| --- | --- |
| `CaptureMode.FULL` | Records every key present before or after, even if unchanged |
| `CaptureMode.DELTA` (default) | Records only keys whose value changed — the right default for most applications |
| `CaptureMode.SELECTIVE` | Records only the *changed* keys named in `capture_fields` (see below) |
| `CaptureMode.CUSTOM` | Delegates the exact fields to the `custom_state_capture` callable passed to `XAIRuntime` |
| `CaptureMode.NONE` | Disables state-transition capture entirely |

`FULL`, `DELTA`, and `NONE` need no other configuration. Only
`SELECTIVE` (an escape hatch for state that must never leave the process —
secrets, full documents, PII) requires the extra `capture_fields` parameter
below; ignore `capture_fields` entirely for every other value.

#### `capture_fields` (only used by `CaptureMode.SELECTIVE`)

A `frozenset[str]` of state keys — defaults to `frozenset()`, meaning
`SELECTIVE` mode records nothing until you name fields. Given a node whose
state carries both a field you want recorded and fields you never want
recorded:

```python
config = XAIConfig(
    capture_state=CaptureMode.SELECTIVE,
    capture_fields=frozenset({"risk_score"}),
)
runtime = XAIRuntime(graph_id="demo", config=config)
run = await runtime.start_run()

delta = await runtime.record_state_delta(
    node_id="score_node",
    before={"risk_score": 10, "raw_document": "...", "customer_ssn": "123-45-6789"},
    after={"risk_score": 87, "raw_document": "...", "customer_ssn": "123-45-6789"},
    run=run,
)
print(delta.model_dump(mode="json")["changes"])
```

```json
[
  {
    "schema_version": "1.0.0",
    "path": "risk_score",
    "before": 10,
    "after": 87
  }
]
```

`raw_document` and `customer_ssn` changed too, but only `risk_score` is
named in `capture_fields`, so it is the only key that ever reaches a
`StateTransition` — the other two never leave the process. If you don't
need this exclusion, leave `capture_state` at its `DELTA` default and skip
`capture_fields` altogether.

### `failure_mode`

Controls what happens when an instrumentation operation itself fails (a
storage write raises, an observability call times out):

| Value | Behavior |
| --- | --- |
| `FailureMode.FAIL_OPEN` (default) | Logs the error (see `runtime.errors`), lets the wrapped graph keep running |
| `FailureMode.FAIL_CLOSED` | Re-raises the failure as `XAIInstrumentationError` |
| `FailureMode.STRICT` | Re-raises, and additionally requires a real provenance/observability sink or plugin to be registered for every artifact kind |

See [Configure failure modes](../how-to/failure-modes.md) for the complete,
per-artifact-kind behavior matrix and a worked example of each mode.

### `max_concurrency`

Bounds how many instrumentation operations (state-delta records, event
emission, plugin dispatch) may run at once via an internal semaphore. It
does not affect your graph's own concurrency — only how many *xgraph*
writes are in flight simultaneously.

The following script registers an observability provider that deliberately
takes 200ms per event (a stand-in for a real network span exporter), then
records 16 events concurrently at three different `max_concurrency` values:

```python
import asyncio
import time
from langgraph_xai import XAIConfig, XAIRuntime
from langgraph_xai.core.protocols import ObservabilityProvider


class SlowObservability:
    """A provider that takes 200ms per event, e.g. a slow span exporter."""

    async def emit(self, event):
        await asyncio.sleep(0.2)

    async def flush(self):
        return None

    async def close(self):
        return None


async def record_n_state_deltas(max_concurrency: int, n: int) -> float:
    runtime = XAIRuntime(
        graph_id="concurrency-demo", config=XAIConfig(max_concurrency=max_concurrency)
    )
    runtime.register(ObservabilityProvider, SlowObservability())
    run = await runtime.start_run()

    started = time.perf_counter()
    await asyncio.gather(
        *[
            runtime.record_state_delta(
                node_id=f"node-{i}", before={"x": 0}, after={"x": i}, run=run
            )
            for i in range(n)
        ]
    )
    elapsed = time.perf_counter() - started
    await runtime.close()
    return elapsed
```

Real captured output — 16 events, three `max_concurrency` values, same
200ms-per-event provider:

```text
max_concurrency=1   -> 16 events recorded in 3.45s
max_concurrency=4   -> 16 events recorded in 0.85s
max_concurrency=16  -> 16 events recorded in 0.21s
```

At `max_concurrency=1`, every write is fully serialized: 16 × 200ms ≈ 3.2s,
which is what the measurement shows. At `4`, four writes run in parallel at
a time, so wall-clock time drops to roughly a quarter. At `16` (all 16
writes admitted at once), total time collapses to roughly one write's
latency. Raise `max_concurrency` when your backend can sustain more
concurrent writes and you want instrumentation to add less wall-clock
latency to a graph run with many parallel branches or tool calls; lower it
to bound load against a rate-limited backend, accepting more added latency
in exchange.

## Reference

::: langgraph_xai.config.XAIConfig

::: langgraph_xai.core.models.CaptureMode

::: langgraph_xai.core.models.FailureMode
