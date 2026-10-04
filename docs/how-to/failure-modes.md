# Configure failure modes

Explainability infrastructure can fail: a database is down, an exporter times
out, a custom policy has a bug. `XAIConfig.failure_mode` decides whether such a
failure may affect your graph.

```python
xai = XAIRuntime(XAIConfig(failure_mode=FailureMode.FAIL_CLOSED))
```

## The three modes, side by side

The [failure modes example](https://github.com/smuniharish/langgraph-xai/blob/master/examples/failure_modes.py)
runs the same one-node graph against a store whose backend is down:

```python
class UnavailableStore(InMemoryProvenanceStore):
    async def write(self, item: object) -> None:
        raise ConnectionError("storage backend unavailable")
```

Real output:

```text
--- failure_mode=fail_open ---
graph call returned {'value': 2}
runtime.errors holds 6 error(s); first: ConnectionError('storage backend unavailable')

--- failure_mode=fail_closed ---
graph call raised XAIInstrumentationError: instrumentation operation failed: ConnectionError: storage backend unavailable
runtime.errors holds 1 error(s); first: ConnectionError('storage backend unavailable')

--- failure_mode=strict ---
graph call raised XAIInstrumentationError: instrumentation operation failed: ConnectionError: storage backend unavailable
runtime.errors holds 1 error(s); first: ConnectionError('storage backend unavailable')
```

- **`fail_open`**: the graph returned its normal result. Each of the six failed
  writes was kept in `xai.errors`: the execution at start and at finish, and
  four events.
- **`fail_closed`**: the first failed write, the execution record at the start
  of the run, raised `XAIInstrumentationError` from the graph call. The cause
  is chained as `__cause__`.
- **`strict`**: the same as `fail_closed`. Strict mode also rejects records that
  would be dropped silently: evidence and decisions require at least one
  [plugin](../architecture/plugins.md), and execution records require a store
  or an observability provider.

## What counts as an instrumentation failure

Store writes, observability emits, capture-policy evaluation, plugin delivery,
and the custom state-capture callable. Each operation is bounded by
`operation_timeout_seconds`, including the wait for one of `max_concurrency`
slots, so a slow backend becomes a `TimeoutError` instead of a stalled graph.

Your graph's own exceptions are never affected. A node that raises fails the
call exactly as it would without instrumentation, in every mode.

## Explanations always fail closed

`explain` and `explain_decision` raise `XAIInstrumentationError` in every mode
when the exposure policy, attribution, or explanation engine fails. Returning a
partial explanation, or one no policy has checked, would defeat the purpose of
the policy.

## Choosing a mode

| Situation | Mode |
| --- | --- |
| Explainability supports the product but must never take it down | `fail_open`, and alert on `xai.errors` |
| An action may not happen without its audit record, as in regulated approvals | `fail_closed` |
| Records must never be dropped silently, as in a test suite or audit pipeline | `strict` |

Different graphs can use different modes. Create one runtime per graph or per
boundary, because configuration is per runtime.

## Monitoring fail-open

`xai.errors` holds the 100 most recent failures, oldest first, in every mode.
Export its length as a metric or log new entries after each call:

```python
errors_before = len(xai.errors)
result = await graph.ainvoke(payload)
for error in xai.errors[errors_before:]:
    logger.warning("explainability failure: %r", error)
```

Once 100 failures are held, the oldest are dropped. For exact counting,
monitor the store and exporter themselves.
