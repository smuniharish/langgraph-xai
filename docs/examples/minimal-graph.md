# Minimal graph

```python
runtime = XAIRuntime(
    config=XAIConfig(
        capture_state=CaptureMode.DELTA,
        failure_mode=FailureMode.FAIL_OPEN,
    )
)

# The graph remains owned and executed by LangGraph.
# Emit explicit, approved evidence and decision records at application
# boundaries, then assemble an explanation from those records.
```

## What to verify

The run has stable IDs, evidence has source references, the decision names
its method, and no raw prompt or private reasoning enters the artifact set.

