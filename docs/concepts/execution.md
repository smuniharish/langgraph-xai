# Execution

An `Execution` is the record of one instrumented call, such as one `invoke`,
`stream`, or `astream_events`, or one input of a `batch`. Instrumentation builds
it automatically while the graph runs. You never construct it yourself.

## Lifecycle

When a call starts, the runtime records an `Execution` with status `running`.
When it ends, the status becomes one of:

| Status | When |
| --- | --- |
| `completed` | The graph returned normally. |
| `failed` | The graph raised. The exception type and message are added to `exceptions`. |
| `cancelled` | The task was cancelled, the caller pressed Ctrl+C, or a stream was closed before it finished. |
| `interrupted` | A node called LangGraph's `interrupt()`, or the graph stopped at a static breakpoint (`interrupt_before` or `interrupt_after`). The pause is added to `human_interactions`, with the interrupt's payload or the pending nodes. |

Resuming an interrupted thread with `Command(resume=...)` is a new call, so it
produces a new `Execution`. That run records a `resume` interaction carrying the
answer, and both runs share the thread's `thread_id`. When the graph has a
checkpointer, the resumed run's `continuation_of` is the `run_id` of the run
that paused. See [Human-in-the-loop](../how-to/interrupts.md).

## What is captured

| Field | Contains | Recorded |
| --- | --- | --- |
| `context` | Application, tenant, graph, run, thread, trace, and checkpoint IDs | At start |
| `continuation_of` | The `run_id` of the run this call resumed, retried, or replayed | At start, for a graph with a checkpointer |
| `nodes` | One `NodeExecution` per node run: status, start and end time, retry `attempt`, `parent_node_id` for subgraph nodes, and the LangGraph step | Automatically |
| `state_transitions` | One `StateTransition` per node that changed state, filtered by the [capture mode](../getting-started/configuration.md#state-capture) | Automatically |
| `tools` | One `ToolExecution` per tool call: name, `tool_call_id`, status (`succeeded`, `failed`, `timed_out`, `cancelled`), and latency | Automatically |
| `retrievals` | One `RetrievalExecution` per retriever call, with ranked documents (ID, score, source) | Automatically |
| `human_interactions` | Interrupts, with their payload, and resumes, with the answer | Automatically; use `record_human_interaction` for approvals made outside the graph |
| `exceptions` | The error that failed or cancelled the run | Automatically |
| `memory` | Reads and writes of long-term memory, by reference | `record_memory` |
| `checkpoints` | The checkpoint the run continued from (`restored`) and the last checkpoint it wrote | Automatically for a graph with a checkpointer; `record_checkpoint` otherwise |

Payloads stay out of the record. Tool inputs and outputs, document text, and
memory contents are referenced by ID or URI, never copied.

## Example

The [fraud review example](../examples/full-explanation.md) runs three nodes.
Its captured execution, summarized:

```json
{
  "nodes": [
    "fetch_transaction: completed",
    "score_risk: completed",
    "route: completed"
  ],
  "state_changes": [
    "fetch_transaction: amount None -> 9200.0",
    "score_risk: risk_score None -> 0.91",
    "route: route None -> 'HUMAN_REVIEW'"
  ]
}
```

Retrievers and tools are captured without any code in the nodes. From the
[retrieval and tools example](../examples/retrieval-and-tools.md), which uses a
LangChain retriever and LangGraph's `ToolNode`:

```json
{
  "retriever": "policy-index",
  "documents": [
    {"document_id": "refund-policy#3", "rank": 1, "score": 0.92, "content_reference": "kb://policies/refunds#3"},
    {"document_id": "shipping-policy#1", "rank": 2, "score": 0.41, "content_reference": "kb://policies/shipping#1"}
  ]
}
```

```json
{
  "tool_name": "order_status",
  "tool_call_id": "call_7Qk2",
  "status": "succeeded",
  "latency_ms": 1.2904999894089997
}
```

`tool_call_id` is the ID the model assigned to the call, so a tool execution can
be matched to the message that requested it.

## Events

Every captured fact is also emitted as an event, in order, to the store and the
observability provider:

| Event type | Emitted when |
| --- | --- |
| `execution.started` | A run starts |
| `node.execution` | A node finishes, fails, or is interrupted |
| `state.transition` | A node's state change is recorded |
| `tool.execution` | A tool call finishes |
| `retrieval.execution` | A retriever call finishes |
| `interrupt` | A human interaction (interrupt, resume, approval, ...) is recorded |
| `checkpoint` | A checkpoint is linked to the run |
| `execution.completed` / `execution.failed` | A run completes, or fails or is cancelled |

Each event carries the run's `ExecutionContext` and a `sequence` number that
orders events within the run. A [capture policy](policies.md#capture-policy)
can drop events before they are stored or emitted.

## Nested graphs and agents

Subgraphs, `create_agent` agents called inside a node, and `deepagents` run in
the same call, so their nodes, tools, and retrievers land in the same
`Execution`. Nodes of a subgraph have `parent_node_id` set to the node that
called it. Internal LangChain runnables that are not graph nodes, such as the
chat model inside an agent's model node, are not recorded as nodes.

An instrumented graph called from inside another instrumented graph of the same
runtime is recorded as part of the outer run, not as a second run.
