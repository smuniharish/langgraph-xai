# Human-in-the-loop interrupts

LangGraph's `interrupt()` does not raise an exception and is not surfaced
through the LangChain callback system — it returns *normally* from
`ainvoke()`/`invoke()` with a `{"__interrupt__": [...]}` key merged into the
output state. Before this was handled explicitly, xgraph silently recorded
every interrupted run as `ExecutionStatus.COMPLETED`, with no
`HumanInteraction` captured at all.

`InstrumentedGraph` now detects this directly (see
[`instrumentation/graph.py`](https://github.com/samamuniharish/langgraph-xai/blob/main/src/langgraph_xai/instrumentation/graph.py))
across all six entry points (`invoke`/`ainvoke`/`stream`/`astream`/`batch`/`abatch`):

- if the output (or last streamed chunk) contains a truthy `__interrupt__`
  key, the run is finished with `ExecutionStatus.INTERRUPTED` and one
  `HumanInteraction(interaction_type=INTERRUPT, ...)` per real `Interrupt`
  object is recorded, carrying the real interrupt `id` and `value`;
- if the input is `Command(resume=...)`, a `HumanInteraction(interaction_type=RESUME, ...)`
  is recorded on the continuation run before invoking.

## Real graph

```python
class WireTransferState(TypedDict, total=False):
    amount: float
    approved: bool


def human_review(state: WireTransferState) -> WireTransferState:
    decision = interrupt(
        {"question": f"Approve a ${state['amount']:,.0f} wire transfer?", "amount": state["amount"]}
    )
    return {"approved": bool(decision)}


builder = StateGraph(WireTransferState)
builder.add_node("human_review", human_review)
builder.add_edge(START, "human_review")
builder.add_edge("human_review", END)
graph = builder.compile(checkpointer=InMemorySaver())

runtime = XAIRuntime(graph_id="wire-transfer-hitl")
instrumented = runtime.instrument(graph)
thread = {"configurable": {"thread_id": "wire-42"}}

paused = await instrumented.ainvoke({"amount": 9000.0}, thread)  # pauses
resumed = await instrumented.ainvoke(Command(resume=True), thread)  # resumes
```

Full runnable source:
[`examples/interrupt_hitl_real.py`](https://github.com/samamuniharish/langgraph-xai/blob/main/examples/interrupt_hitl_real.py).

```bash
uv run python examples/interrupt_hitl_real.py
```

## Real captured output

```json
{
  "status": "interrupted",
  "human_interactions": [
    {
      "interaction_type": "interrupt",
      "request_reference": null,
      "metadata": {}
    }
  ]
}
{
  "status": "completed",
  "human_interactions": [
    {
      "interaction_type": "resume",
      "request_reference": null,
      "metadata": {}
    }
  ]
}
```

Two distinct `Execution` records are captured for one logical wire-transfer
approval: the paused run (`status="interrupted"`, one `INTERRUPT`
interaction) and the resumed run (`status="completed"`, one `RESUME`
interaction) sharing the same `thread_id`.

## Regression coverage

This behavior is not just an example — it is asserted in the example script
itself and covered by an automated test:
`tests/langgraph/test_instrumentation.py::test_interrupt_is_captured_as_interrupted_not_completed`.

## Known simplification

`Execution.continuation_of` (linking the resumed run back to the interrupted
one by ID) is **not** populated automatically. Correlating the two runs today
relies on `thread_id`/`trace_id`, which is sufficient for most storage
backends and dashboards but is deliberately not further automated, since
computing it correctly would require a storage-backend-coupled lookup at
resume time. If your storage backend can cheaply resolve "the most recent
interrupted run for this thread", you can populate
`Execution.continuation_of` yourself via `runtime.record_human_interaction(...)`.
