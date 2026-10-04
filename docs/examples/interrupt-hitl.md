# Human-in-the-loop

A wire-transfer graph pauses for approval with LangGraph's `interrupt()` and
continues with `Command(resume=...)`. Because the graph has a checkpointer, both
runs are linked to LangGraph checkpoints automatically, and the resumed run
points back to the run that paused. An approval recorded after the run finished
still reaches the stored record. Source:
[`examples/human_in_the_loop.py`](https://github.com/smuniharish/langgraph-xai/blob/master/examples/human_in_the_loop.py).

```bash
uv run python examples/human_in_the_loop.py
```

## The graph

```python
def human_review(state: WireTransfer) -> WireTransfer:
    approved = interrupt(
        {"question": f"Approve a ${state['amount']:,.0f} wire transfer?", "amount": state["amount"]}
    )
    return {"approved": bool(approved)}
```

LangGraph needs a checkpointer for interrupts. The example pauses, resumes with
the reviewer's answer, and then records the reviewer's approval on the resumed
run. No code links runs or checkpoints:

```python
xai = XAIRuntime(graph_id="wire-transfer")
graph = xai.instrument(builder.compile(checkpointer=InMemorySaver()))
thread = {"configurable": {"thread_id": "wire-42"}}

with xai.collect_runs() as runs:
    paused = await graph.ainvoke({"amount": 9000.0}, thread)
    (question,) = paused["__interrupt__"]
    print(f"Paused on: {question.value['question']}")
    resumed = await graph.ainvoke(Command(resume=True), thread)
    print(f"Resumed: {resumed}")
paused_run, resumed_run = runs

# Recorded after the run finished, and still added to the stored record.
await xai.record_human_interaction(
    HumanInteractionType.APPROVAL, actor_reference="reviewer:ana", run=resumed_run
)
```

The script prints a summary of each run, where `payload` is the interaction's
`metadata["value"]`, and the interaction types of the resumed run as stored.

## Output

```text
Paused on: Approve a $9,000 wire transfer?
Resumed: {'amount': 9000.0, 'approved': True}

--- Paused run ---
{
  "run_id": "f8e880ea-4099-4611-99e3-fd01d2aca544",
  "status": "interrupted",
  "continuation_of": null,
  "nodes": [
    "human_review: interrupted"
  ],
  "human_interactions": [
    {
      "type": "interrupt",
      "interrupt_id": "2fae2447ab28076775b6028f8ddd7f89",
      "actor": null,
      "payload": {
        "question": "Approve a $9,000 wire transfer?",
        "amount": 9000.0
      }
    }
  ],
  "checkpoints": [
    {
      "checkpoint_id": "1f1bff8a-53e1-654b-8000-9edd65398324",
      "restored": false
    }
  ]
}

--- Resumed run ---
{
  "run_id": "90beeb3f-783e-442d-ba15-402f96a38951",
  "status": "completed",
  "continuation_of": "f8e880ea-4099-4611-99e3-fd01d2aca544",
  "nodes": [
    "human_review: completed"
  ],
  "human_interactions": [
    {
      "type": "resume",
      "interrupt_id": "2fae2447ab28076775b6028f8ddd7f89",
      "actor": null,
      "payload": true
    },
    {
      "type": "approval",
      "interrupt_id": null,
      "actor": "reviewer:ana",
      "payload": null
    }
  ],
  "checkpoints": [
    {
      "checkpoint_id": "1f1bff8a-53e1-654b-8000-9edd65398324",
      "restored": true
    },
    {
      "checkpoint_id": "1f1bff8a-53f0-63b3-8001-bd0c90a2e877",
      "restored": false
    }
  ]
}

--- Stored record of the resumed run ---
{
  "human_interactions": [
    "resume",
    "approval"
  ]
}
```

## What to notice

- **A pause is not a failure.** The paused run ends `interrupted`, with the
  question and amount the reviewer saw recorded as the interrupt payload.
- **Question and answer are joined.** The `resume` interaction carries the
  reviewer's answer (`true`) and the same interrupt ID as the `interrupt`
  interaction.
- **The runs are linked.** The resumed run's `continuation_of` is the paused
  run's `run_id`. LangGraph stores the run ID in each checkpoint's metadata,
  so the link also holds across processes with a durable checkpointer.
- **Checkpoints are captured without code.** The paused run records the
  checkpoint it stopped at. The resumed run records the same checkpoint as
  `restored`, then the checkpoint it finished at. An auditor can load either
  one to see the exact state.
- **Late records are stored.** The approval was recorded after the run
  finished, and the stored `Execution` includes it.

See [Handle human-in-the-loop interrupts](../how-to/interrupts.md) for static
breakpoints, retries, and replays.
