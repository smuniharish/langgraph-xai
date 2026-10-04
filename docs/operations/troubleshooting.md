# Troubleshooting

Start with `xai.errors`. In the default fail-open mode, every instrumentation
failure is kept there (the last 100), even though the graph keeps running.

```python
for error in xai.errors:
    print(repr(error))
```

## `RuntimeError: no active run`

The full message is
`no active run: call this inside an instrumented graph call or pass run=`. A
`record_*` method was called where no run is active:

- The graph was called directly instead of through `xai.instrument(graph)`.
- The call happened after the instrumented call returned. Keep the run with
  `collect_runs()` and pass `run=`; see
  [Explain a decision after the run](../how-to/explain-after-run.md).
- The code runs in a thread you started yourself, which does not inherit the
  context. Use `contextvars.copy_context().run(...)` or pass `run=`.
- The code runs outside any graph. Use `start_run()` and `finish_run()`.

## Nothing, or not everything, is recorded

- **Unrecorded call.** LangGraph's experimental v3 streaming protocol
  (`stream_events` and `astream_events(version="v3")`) and LangChain's
  deprecated `astream_log` cannot be recorded; `xai.errors` holds a
  `NotImplementedError` for each such call. Use `stream`, `astream`, or
  `astream_events` with `version="v2"`. Runnables built from the instrumented
  graph, such as `graph.with_retry()`, are not instrumented.
- **No checkpoints or `continuation_of`.** They need a graph compiled with a
  checkpointer, a `thread_id` in the call's config, and
  `capture_checkpoints=True` (the default). A call with new input starts a new
  run; only a call whose input is `None` or a `Command` continues one.
- **State capture settings.** `CaptureMode.NONE` records no state changes.
  `SELECTIVE` records only changed keys listed in `capture_fields`, and nothing
  if that is empty.
- **Capture policy.** An event your `CapturePolicy` denies, or whose policy
  raised an error, is not recorded anywhere.
- **Failures.** Look in `xai.errors` for store or exporter errors.

## A value shows `"[not captured]"`

Its key looks like a credential, for example `token`, `api_key`,
`authorization`, or `session_token`. This is intended. If the value is not a
credential, rename the key: a count stored under `token` is recorded once it is
stored under `token_count`.

## Evidence and decisions are not in the store

Evidence, decisions, and memory references are delivered to
[plugins](../architecture/plugins.md#plugins), not to the store. Register a
plugin that persists them.

## Explanations raise `XAIInstrumentationError`

Explanations fail closed in every mode. The message names the step:

| Message | Fix |
| --- | --- |
| `LLM explanation engine is registered but disabled in XAIConfig` | Set `XAIConfig(llm_explanation_enabled=True)`, or register the structured engine. |
| `exposure policy evaluation failed; see XAIRuntime.errors` | Your `PolicyProvider` raised or timed out. The cause is in `xai.errors[-1]`. |
| `attribution failed; see XAIRuntime.errors` | Your `AttributionEngine` raised, or a rule returned a non-finite score. |
| `explanation failed; see XAIRuntime.errors` | The engine raised, or an LLM reply was invalid or timed out. Raise `operation_timeout_seconds` for slow models. |

`ValueError: decision does not belong to the given run` means
`explain_decision` received a decision from a different run. Pass the run the
decision was recorded in.

## Timeouts in `xai.errors`

`TimeoutError` entries mean an operation exceeded
`operation_timeout_seconds`. `timed out waiting for an instrumentation slot`
means `max_concurrency` operations were already in flight. Check the backend's
latency, then raise the timeout or the concurrency limit.

## Nothing appears in LangSmith, Langfuse, or OpenTelemetry

- Call `await xai.flush()` before short scripts exit, and `await xai.close()`
  at shutdown, so batched data is sent.
- `OptionalDependencyError` names the extra to install, for example
  `pip install 'langgraph-xai[otel]'`.
- For OpenTelemetry, check that the tracer provider has an exporter and that
  `OTEL_EXPORTER_OTLP_ENDPOINT` points to your collector.

## Custom store errors

- `TypeError: ... does not implement ProvenanceStore` means the store does not
  subclass `ProvenanceStore`. Since stores are an abstract base class,
  inheriting from it is required.
- `TypeError: Can't instantiate abstract class` means one of the five abstract
  methods is missing.
- With an asynchronous database driver, such as the PostgreSQL example, use
  asynchronous graph calls. On Windows, psycopg's asynchronous mode needs
  `asyncio.run(main(), loop_factory=asyncio.SelectorEventLoop)`.
