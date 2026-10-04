# Retrieval and tools

A support graph retrieves policy passages with a LangChain retriever, runs the
tool call the model requested through LangGraph's `ToolNode`, and decides on a
refund. Retrievals and tool calls are captured without any explainability code.
The deciding node turns them into evidence. Model output is simulated, so the
example runs offline. Source:
[`examples/retrieval_and_tools.py`](https://github.com/smuniharish/langgraph-xai/blob/master/examples/retrieval_and_tools.py).

```bash
uv run python examples/retrieval_and_tools.py
```

## Captured automatically

The retriever is an ordinary LangChain retriever, named with `run_name`:

```python
retriever = PolicyRetriever().with_config(run_name="policy-index")


async def retrieve(state: Support) -> Support:
    await retriever.ainvoke(state["question"])
    return {}
```

The `tools` node is LangGraph's prebuilt `ToolNode([order_status])`, executing
a tool call with ID `call_7Qk2`. Neither needs instrumentation code. Every
document's ID, rank, score, and source, and every tool call's ID, status, and
latency, are recorded in the run.

## Captured facts become evidence

The `decide` node reads what was captured from `xai.current_run` and records it
as evidence for the decision:

```python
async def decide(state: Support) -> Support:
    run = xai.current_run
    assert run is not None
    (retrieval,) = run.execution.retrievals
    evidence = [
        await xai.record_evidence(
            EvidenceType.RETRIEVAL_DOCUMENT,
            summary=f"Policy passage {document.document_id} (rank {document.rank}).",
            content_reference=document.content_reference,
            source=SourceReference(source_id=retrieval.retriever_id, source_type="retriever"),
            confidence=document.score,
        )
        for document in retrieval.documents
    ]
    (lookup,) = run.execution.tools
    delivery = await xai.record_evidence(
        EvidenceType.TOOL_RESULT,
        summary="Order A-1042 was delivered 12 days ago.",
        content_reference=f"tool-call://{lookup.tool_call_id}",
        confidence=1.0,
    )
    await xai.record_decision(
        "APPROVE_REFUND",
        decision_type=DecisionType.APPROVAL,
        candidate_actions=["APPROVE_REFUND", "DENY_REFUND", "ESCALATE"],
        evidence_ids=[evidence[0].id, delivery.id],
        factors=[
            DecisionFactor(name="days_since_delivery", value=12, evidence_ids=[delivery.id]),
            DecisionFactor(name="refund_window_days", value=30, evidence_ids=[evidence[0].id]),
        ],
    )
    return {"decision": "APPROVE_REFUND"}
```

## Output

```text
Decision: APPROVE_REFUND

--- Captured retrieval ---
{
  "retriever": "policy-index",
  "documents": [
    {
      "document_id": "refund-policy#3",
      "rank": 1,
      "score": 0.92,
      "content_reference": "kb://policies/refunds#3"
    },
    {
      "document_id": "shipping-policy#1",
      "rank": 2,
      "score": 0.41,
      "content_reference": "kb://policies/shipping#1"
    }
  ]
}

--- Captured tool call ---
{
  "tool_name": "order_status",
  "tool_call_id": "call_7Qk2",
  "status": "succeeded",
  "latency_ms": 1.2904999894089997
}

--- Explanation ---
{
  "summary": "The approval decision selected 'APPROVE_REFUND'.",
  "reasons": [
    "Selected action: APPROVE_REFUND.",
    "Alternatives considered: DENY_REFUND, ESCALATE.",
    "Factor days_since_delivery was 12.",
    "Factor refund_window_days was 30."
  ],
  "disclosure": [
    "Private memory and raw content are withheld by default."
  ]
}
```

## What to notice

- **Documents are referenced, not copied.** The record holds each passage's ID,
  rank, score, and source URI, but not its text.
- **`tool_call_id` is the model's ID** for the call, so the tool execution can be
  matched to the assistant message that requested it.
- **Only the passage that mattered is cited.** The decision references the
  refund policy passage, not the shipping passage that ranked second.
