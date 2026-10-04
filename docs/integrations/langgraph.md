# LangGraph

`xai.instrument(graph)` wraps any compiled LangGraph graph, or any LangChain
`Runnable`, without patching LangGraph. It attaches a callback handler to each
call and reads LangGraph's own metadata to recognize nodes, subgraphs, retries,
and interrupts.

```python
graph = xai.instrument(builder.compile(checkpointer=checkpointer))
```

Instrumenting a graph the same runtime already instruments returns it
unchanged; a graph instrumented by another runtime is re-wrapped.

## Supported calls

| Method | Recorded as |
| --- | --- |
| `invoke`, `ainvoke` | One run per call |
| `stream`, `astream` | One run per stream, for every `stream_mode`, `version`, and `subgraphs` setting. Chunks are yielded unchanged. |
| `astream_events` | One run per stream, for `version="v1"` and `"v2"`. Events are yielded unchanged. |
| `batch`, `abatch` | One run per input. `return_exceptions` and `max_concurrency` work as usual. |
| `batch_as_completed`, `abatch_as_completed` | One run per input, yielded as each one finishes |
| `transform`, `atransform` | One run for the combined input chunks |
| `with_config(...)` | Returns an instrumented graph |

Two kinds of call cannot be recorded: LangGraph's experimental v3 streaming
protocol (`stream_events` and `astream_events(version="v3")`), which runs
inside LangGraph, and LangChain's deprecated `astream_log`. They reach the
graph unchanged, and the [failure mode](../getting-started/configuration.md#failure-modes)
decides what happens: `fail_open` keeps a `NotImplementedError` in
`xai.errors`, and `fail_closed` and `strict` raise `XAIInstrumentationError`
before the graph runs.

Every other attribute, such as `get_state`, `update_state`, or `get_graph`, is
passed to the wrapped graph. Methods that build a new runnable from the graph,
such as `with_retry`, `with_fallbacks`, or `bind`, return an uninstrumented
runnable.

A call made while another instrumented call of the same runtime is running,
for example an instrumented graph invoked inside a node, joins the outer run
instead of starting a new one.

## What is recognized

- **Nodes.** A node is recognized by the same rule LangGraph uses: its run name
  matches the `langgraph_node` metadata and it is not hidden. Internal
  runnables inside a node, such as prompt templates, chat models, or parsers,
  are not mistaken for nodes.
- **State changes.** These are the node's input state merged with its output.
  Partial updates, `Command(update=...)`, lists of commands, and Pydantic or
  dataclass states are supported. For reducer channels such as `messages`,
  `after` is the value the node wrote, not the reduced channel value.
- **Subgraphs and nested agents.** Nodes in a subgraph record `parent_node_id`,
  derived from LangGraph's checkpoint namespace.
- **Retries.** Each attempt of a node with a `RetryPolicy` is a separate
  `NodeExecution` with an increasing `attempt`.
- **Fan-out and the functional API.** Each task started with `Send` is a
  separate `NodeExecution`. An `@entrypoint` workflow records the entrypoint
  and each `@task` call.
- **Cached nodes.** A node whose result comes from LangGraph's node cache does
  not run, so it is not recorded.
- **Interrupts.** Interrupts are taken from LangGraph itself, so they are
  recorded for every entry point, output version, and stream mode, including
  interrupts raised in subgraphs and parallel nodes. The run is recorded as
  `interrupted`, with one interaction per interrupt, and `Command(resume=...)`
  records the answer. A static breakpoint (`interrupt_before` or
  `interrupt_after`) is recorded as an interrupt with the pending nodes. See
  [interrupts](../how-to/interrupts.md).
- **Parent commands.** `Command(graph=Command.PARENT, ...)` from a subgraph
  completes the node instead of failing it.
- **Tools and retrievers.** Any LangChain tool or retriever called during the
  run, including through `ToolNode` and `create_agent`, is recorded.

## Checkpoints and resumed runs

When the instrumented graph has a checkpointer and the call's config has a
`thread_id`, each run records the checkpoint it continued from and the last
checkpoint it wrote. A call that continues the thread, such as a
`Command(resume=...)`, a retry after a failure, or a replay from a past
checkpoint, sets `continuation_of` to the run that wrote the checkpoint it
starts from.

To make this work across processes, the graph receives the run ID in its config
metadata under `RUN_ID_METADATA_KEY` (`"langgraph_xai_run_id"`), and LangGraph
stores it in the metadata of every checkpoint the run writes. Set
`XAIConfig(capture_checkpoints=False)` to skip the state reads this needs. See
[how runs are linked](../how-to/interrupts.md#how-runs-are-linked).

## Inside nodes

`xai.current_run` is the run of the call executing the node. Record evidence and
decisions with the async `record_*` methods, or wrap them in `xai.run_sync(...)`
inside synchronous nodes:

```python
async def route(state: Review) -> Review:
    await xai.record_decision("HUMAN_REVIEW", decision_type=DecisionType.ROUTING)
    return {"route": "HUMAN_REVIEW"}


def route_sync(state: Review) -> Review:
    xai.run_sync(xai.record_decision("HUMAN_REVIEW", decision_type=DecisionType.ROUTING))
    return {"route": "HUMAN_REVIEW"}
```

The current run is carried by context variables, so it also reaches tools,
middleware, and agents called inside the node. Code running in threads you
start yourself does not see it unless you copy the context
(`contextvars.copy_context().run(...)`) or pass `run=` explicitly.

## Prebuilt agents

`create_agent` (LangChain) and `create_deep_agent` (deepagents) return compiled
LangGraph graphs, so they are instrumented the same way. Their middleware hooks
are the natural place to record decisions; see the
[create_agent example](../examples/create-agent.md).

## Overhead

Instrumentation adds the callback handler and one record per node, state
change, tool call, and retrieval. With the in-memory store and no observability
backend, a five-node graph adds about 2 milliseconds per call on a typical
laptop, synchronous or asynchronous. A remote store or exporter adds its own
latency, which is bounded by `operation_timeout_seconds` and handled according
to the [failure mode](../getting-started/configuration.md#failure-modes).
