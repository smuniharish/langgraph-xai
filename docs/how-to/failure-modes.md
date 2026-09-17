# How to configure failure modes

**Goal:** choose how xgraph's *own* instrumentation should behave when it
fails internally (a storage write times out, an observability exporter is
unreachable, an attribution/explanation engine raises) — separately from
whatever your graph itself does.

## The three modes

| `XAIConfig.failure_mode` | Behavior when an internal xgraph operation raises |
| --- | --- |
| `fail_open` (default) | The exception is recorded in `runtime.errors` and swallowed; your graph's `ainvoke`/`explain` call still returns normally. Use this when explainability must never take down the application. |
| `fail_closed` | The exception is wrapped in `XAIInstrumentationError` and re-raised from the call site that triggered it. Use this when explainability is a release/compliance gate and a silent gap is unacceptable. |
| `strict` | Same as `fail_closed`, **plus** additional configuration checks: recording an execution or provenance artifact requires at least one registered `ProvenanceStore` or `ObservabilityProvider`, and recording a semantic artifact (evidence, a decision, an attribution result, …) requires at least one registered plugin. Use this to catch a misconfigured runtime — for example, an instrumented graph with nothing registered to receive its output — as early as possible, rather than only when an operation fails at runtime. |

## Steps

```python
from langgraph_xai import XAIConfig, XAIRuntime

runtime = XAIRuntime(config=XAIConfig(failure_mode="fail_closed"))
```

Set it once per runtime, matching that application's release posture — there
is deliberately no environment-variable override (see
[ADR-019](../architecture/decisions.md#adr-019-core-configuration-is-explicit-and-per-runtime-not-environment-driven)):
construct a different `XAIConfig` explicitly wherever behavior needs to
differ (for example, a stricter mode in a staging/compliance environment than
in a quick local prototype).

## Real, observed behavior for all three modes

Run against the *same* deliberately broken `ProvenanceStore`
(`ConnectionError` on every write):

```text
--- failure_mode='fail_open' ---
ainvoke succeeded despite the broken store: {'value': 2}
runtime captured 5 suppressed error(s):
  - ConnectionError: simulated storage outage
  ...

--- failure_mode='fail_closed' ---
ainvoke raised as expected: XAIInstrumentationError: instrumentation operation failed
__cause__: ConnectionError: simulated storage outage

--- failure_mode='strict' ---
ainvoke raised as expected: XAIInstrumentationError: instrumentation operation failed
__cause__: ConnectionError: simulated storage outage
```

Source: [`examples/failure_modes_real.py`](https://github.com/samamuniharish/langgraph-xai/blob/main/examples/failure_modes_real.py).

```bash
uv run python examples/failure_modes_real.py
```

Note that `runtime.errors` (a bounded deque, most recent 100) is populated in
**every** mode — even `fail_closed`/`strict` append the error before
re-raising — so you can inspect the underlying cause without relying solely
on the raised exception's traceback.
