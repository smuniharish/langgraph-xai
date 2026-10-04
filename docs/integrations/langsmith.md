# LangSmith

`LangSmithObservability` sends `langgraph-xai` events to
[LangSmith](https://smith.langchain.com) as a trace per run, next to the traces
LangChain already produces.

```bash
pip install "langgraph-xai[langsmith]"
```

```python
from langgraph_xai import LangSmithObservability, ObservabilityProvider

xai.register(ObservabilityProvider, LangSmithObservability(project_name="fraud-review"))
```

Without a `client`, the adapter creates `langsmith.Client()`, which reads
`LANGSMITH_API_KEY` (and `LANGSMITH_ENDPOINT` for self-hosted LangSmith) from
the environment. To reuse a configured client, pass `client=`.

## What appears in LangSmith

| LangSmith run | Contents |
| --- | --- |
| Root run `langgraph-xai: <graph_id>` | One per `langgraph-xai` run. The trace ID is the `run_id`. Inputs are the application, tenant, and graph IDs. |
| One child run per event | Named after the event type (`node.execution`, `state.transition`, `tool.execution`, ...). Inputs are the canonical event JSON, and metadata holds the `xai.*` correlation fields. |

The root run ends when the run completes, fails, or is interrupted. Its outputs
record the final status, and a failure also records the error. Runs are
submitted through LangSmith's background batching, so the graph is never
blocked on the network.

## Alongside LangChain tracing

With `LANGSMITH_TRACING=true`, LangChain traces the graph itself: every node,
model call, and token count. The adapter adds a second trace for the same call
that contains the explainability records. Find it by searching the project for
metadata `xai.run_id`, or by `trace_id` if you pass one in the config. See
[LangSmith and langgraph-xai](langsmith-vs-langgraph-xai.md) for how the two
complement each other.

## Lifecycle

```python
await xai.flush()  # send buffered runs, for example at the end of a batch job
await xai.close()  # flush, then close the client the adapter created
```

A client you pass in is flushed but never closed. The adapter tracks up to
`max_open_traces` recent runs (1024 by default), so a long-running process uses
bounded memory.
