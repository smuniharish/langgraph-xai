# Handle human-in-the-loop interrupts

LangGraph pauses a graph with `interrupt()` and continues it with
`Command(resume=...)`. Instrumented graphs record both automatically and, when
the graph has a checkpointer, link each run to its checkpoints and to the run
it continues. This guide shows what is captured, how runs are linked, and how to
record approvals made outside the graph.

## What is captured automatically

```python
def human_review(state: WireTransfer) -> WireTransfer:
    approved = interrupt(
        {"question": f"Approve a ${state['amount']:,.0f} wire transfer?", "amount": state["amount"]}
    )
    return {"approved": bool(approved)}


graph = xai.instrument(builder.compile(checkpointer=InMemorySaver()))
thread = {"configurable": {"thread_id": "wire-42"}}

paused = await graph.ainvoke({"amount": 9000.0}, thread)  # pauses at interrupt()
resumed = await graph.ainvoke(Command(resume=True), thread)  # continues with the answer
```

The two calls are two runs on the same thread:

| Run | Status | Interactions | Checkpoints |
| --- | --- | --- | --- |
| The pausing call | `interrupted`; the node is `interrupted` too | `interrupt`, with the payload in `metadata["value"]` and the interrupt ID as `request_reference` | The checkpoint it paused at |
| The resuming call | `completed`, with `continuation_of` set to the paused run's `run_id` | `resume`, with the answer in `metadata["value"]`, and the interrupt ID when one interrupt was pending | The checkpoint it resumed from, with `restored: true`, then the last checkpoint it wrote |

A resume that answers several interrupts by ID, such as
`Command(resume={interrupt_id: answer})`, is recorded as that mapping.
Payloads and answers are [redacted](../concepts/policies.md#redaction) like
any other value, so a credential in an answer is never stored.

Interrupts are recorded however the graph is called: every entry point,
`version="v1"` or `"v2"` output, any stream mode, and interrupts raised inside
subgraphs or by parallel nodes. The
[human-in-the-loop example](../examples/interrupt-hitl.md) shows the complete
records of both runs.

## How runs are linked

Each instrumented call passes its run ID to the graph in config metadata, under
`RUN_ID_METADATA_KEY` (`"langgraph_xai_run_id"`). LangGraph copies it into the
metadata of every checkpoint the run writes. When a call continues a thread,
the runtime reads the checkpoint it starts from and sets `continuation_of` to
the run that wrote it. Because the link lives in the checkpoint, it holds across
processes and runtimes that share a durable checkpointer.

A call continues a thread when its input is `None` or a `Command`:

| Call | `continuation_of` | Also recorded |
| --- | --- | --- |
| `Command(resume=...)` after an `interrupt()` | The run that paused | A `resume` interaction with the answer |
| `invoke(None, thread)` after a static breakpoint | The run that stopped at the breakpoint | A `resume` interaction listing `pending_nodes` |
| `invoke(None, thread)` after a failure | The run that failed | The restored checkpoint only |
| `invoke(None, config)` with a `checkpoint_id` from the history | The run that wrote that checkpoint | The restored checkpoint only |

State edits made with `update_state` between the pause and the resume are
followed back to the run that paused. A call with new input starts a new,
unlinked run on the same thread.

## Static breakpoints

A graph compiled or called with `interrupt_before` or `interrupt_after` stops
without calling `interrupt()`. The run that stops is recorded as `interrupted`,
with one `interrupt` interaction whose metadata lists the `pending_nodes`. The
call that continues it with `None` records a `resume` interaction with the same
`pending_nodes`.

## Inspect the state the reviewer saw

Every checkpoint ID on a run can be loaded from the graph:

```python
paused_at = paused_run.execution.checkpoints[0]
replay = {"configurable": {"thread_id": "wire-42", "checkpoint_id": paused_at.checkpoint_id}}
state = await graph.aget_state(replay)
```

## Turn checkpoint capture off

Linking reads the graph's state once after each call on a checkpointed thread,
and once more before a call that continues a thread, plus once per state edit
it follows back. To skip the reads, set `capture_checkpoints=False`:

```python
xai = XAIRuntime(XAIConfig(capture_checkpoints=False))
```

Interrupts raised with `interrupt()` and answers passed to `Command(resume=...)`
are still recorded. Checkpoint records, `continuation_of`, and static
breakpoints need the state reads: without them, a run that stops at a
breakpoint is recorded as `completed`. To link checkpoints yourself, for example
from a system that is not a LangGraph checkpointer, call
`xai.record_checkpoint(checkpoint_id, parent_checkpoint_id=..., restored=..., run=run)`.

## Record approvals made outside the graph

When a decision is approved in another system, such as a case-management tool,
record it on the run it belongs to:

```python
await xai.record_human_interaction(
    HumanInteractionType.APPROVAL,
    actor_reference="reviewer:ana.lopez",
    response_reference="case-tool://cases/8841/approval",
    run=run,
)
```

Interaction types are `interrupt`, `approval`, `rejection`, `edit`, and
`resume`. Recording into a finished run updates the stored `Execution` too, so
the store and the in-memory run stay identical.

## Guidance

- **Use a durable checkpointer in production**, such as LangGraph's PostgreSQL
  or SQLite savers. `InMemorySaver` loses checkpoints when the process exits,
  and with them the ability to replay and to link runs across processes.
- **Reference people, don't copy them.** Put a reviewer ID in
  `actor_reference`, not a name and email address.
- **Explain after the human step.** A decision recorded after the resume can
  cite the approval as evidence, so the explanation shows the human's role.
