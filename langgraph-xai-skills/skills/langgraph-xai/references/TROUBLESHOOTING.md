# langgraph-xai troubleshooting

Start with `xai.errors`. In the default `FAIL_OPEN` mode every instrumentation
failure is kept there, the last 100, while the graph keeps running:

```python
for error in xai.errors:
    print(repr(error))
```

## Contents

- [`RuntimeError: no active run`](#runtimeerror-no-active-run)
- [No run is recorded](#no-run-is-recorded)
- [Runs are recorded but incomplete](#runs-are-recorded-but-incomplete)
- [No checkpoints or `continuation_of`](#no-checkpoints-or-continuation_of)
- [Explanations raise `XAIInstrumentationError`](#explanations-raise-xaiinstrumentationerror)
- [An explanation shows too much or too little](#an-explanation-shows-too-much-or-too-little)
- [A value shows `"[not captured]"`](#a-value-shows-not-captured)
- [Evidence and decisions are not in the store](#evidence-and-decisions-are-not-in-the-store)
- [Timeouts](#timeouts)
- [Nothing reaches LangSmith, Langfuse, or OpenTelemetry](#nothing-reaches-langsmith-langfuse-or-opentelemetry)
- [Custom store errors](#custom-store-errors)

## `RuntimeError: no active run`

A `record_*` method had no `run=` and no current run.

| Cause | Fix |
| --- | --- |
| The graph was called directly, not through `xai.instrument(graph)` | Call the instrumented wrapper. |
| The call came after the instrumented call returned | Keep the run with `collect_runs()` and pass `run=`. |
| The code runs in a thread you started | Pass `run=`, or use `contextvars.copy_context().run(...)`. |
| The code runs outside any graph | Use `start_run()` and `finish_run()`, passing `run=` to each call. |
| A different `XAIRuntime` instance recorded than the one that instrumented the graph | Use one runtime per application boundary; `current_run` only returns the runs of its own runtime. |

## No run is recorded

- The call went to the original compiled graph, not to the wrapper returned by
  `xai.instrument(...)`.
- The entry point is not recorded: `stream_events`,
  `astream_events(version="v3")`, and `astream_log`. `xai.errors` holds a
  `NotImplementedError` for each. Use `stream`, `astream`, or `astream_events`
  with `version="v2"`.
- The runnable was built from the wrapper, as in `graph.with_retry()` or
  `graph.bind(...)`. Only `with_config(...)` keeps the instrumentation.
- The call ran inside another instrumented call of the same runtime. It joined
  the outer run instead of starting its own; this is intended.

## Runs are recorded but incomplete

| Missing | Cause |
| --- | --- |
| State changes | `CaptureMode.NONE`, or `SELECTIVE` with the key missing from `capture_fields`. `DELTA` records only keys whose value changed. |
| Some events | A `CapturePolicy` denied them, or failed. Failed policies drop the event. |
| A node | It was served from LangGraph's node cache and did not run. |
| Evidence or decisions | They are on `run.evidence` and `run.decisions`, not on `run.execution`. |
| Everything after an error | Look in `xai.errors` for store or exporter failures. |

## No checkpoints or `continuation_of`

All of these are required:

- the graph is compiled with a checkpointer;
- the call's config has `configurable["thread_id"]`;
- `XAIConfig.capture_checkpoints` is `True`, the default;
- the call continues the thread: its input is `None` or a `Command`. A call
  with new input starts a new run on the thread, without `continuation_of`.

The link is read from checkpoint metadata, so runs written before the runtime
was instrumented, or by an uninstrumented graph, cannot be linked.

## Explanations raise `XAIInstrumentationError`

Explanations fail closed in every mode. The message names the step:

| Message | Fix |
| --- | --- |
| `LLM explanation engine is registered but disabled in XAIConfig` | Set `XAIConfig(llm_explanation_enabled=True)`, or register the structured engine. |
| `exposure policy evaluation failed; see XAIRuntime.errors` | The `PolicyProvider` raised or timed out; the cause is `xai.errors[-1]`. |
| `attribution failed; see XAIRuntime.errors` | The `AttributionEngine` raised, or a rule returned a non-finite score. |
| `explanation failed; see XAIRuntime.errors` | The engine raised, or an LLM reply was invalid or late. Raise `operation_timeout_seconds` for slow models. |

`ValueError: decision does not belong to the given run` means
`explain_decision` received a decision and a run that do not match.

## An explanation shows too much or too little

- A section is withheld when the policy decision has `allowed=False`, lists
  the section in `denied_fields`, or has a non-empty `allowed_fields` that
  does not name it. Every withheld section is listed in `disclosure`.
- Withholding `contributing_factors` also removes factor values from
  `reasons`.
- An empty `supporting_evidence` with no disclosure note means the decision
  referenced no evidence: pass `evidence_ids` to `record_decision`.
- Never fix a test by weakening the policy. Fix the policy or the expectation.

## A value shows `"[not captured]"`

The key looks like a credential, such as `token`, `api_key`, `password`,
`authorization`, or `session_token`. This is intended: values under such keys
are never recorded, at any depth of state, metadata, or factor values. If the
value is not a credential, rename the key, for example `token_count` instead
of `token`.

## Evidence and decisions are not in the store

The `ProvenanceStore` holds executions, events, and provenance links.
Evidence, decisions, and memory references are delivered to plugins. Register
an `XAIPlugin` that persists them.

## Timeouts

`TimeoutError` in `xai.errors` means an operation exceeded
`operation_timeout_seconds`. `timed out waiting for an instrumentation slot`
means `max_concurrency` operations were already in flight. Check the backend's
latency, then raise the timeout or the limit.

## Nothing reaches LangSmith, Langfuse, or OpenTelemetry

- Call `await xai.flush()` before a short script exits, and `await xai.close()`
  at shutdown.
- `OptionalDependencyError` names the extra to install, such as
  `pip install "langgraph-xai[otel]"`.
- Check the SDK's own environment variables, for example
  `OTEL_EXPORTER_OTLP_ENDPOINT` and an exporter on the tracer provider.

## Custom store errors

- `TypeError: ... does not implement ProvenanceStore`: the store must subclass
  `ProvenanceStore`.
- `TypeError: Can't instantiate abstract class`: one of `write`, `get`,
  `query`, `parents`, or `children` is missing.
- With an async database driver, use the graph's async entry points. On
  Windows, psycopg's async mode needs
  `asyncio.run(main(), loop_factory=asyncio.SelectorEventLoop)`.
