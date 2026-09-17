# Evidence

## Kid-level view

Evidence is the small set of approved facts used to support a choice.

## Production view

Evidence records identify approved inputs such as retrieved material, rules,
measurements, or application assertions, with source references, selection
reason, confidence or uncertainty where meaningful, and disclosure status.

## Why and architecture

Applications own domain correctness. The runtime records supplied evidence;
policy filters it before storage, export, or rendering. Evidence is not a
promise that a model was correct.

## Real example: input and output

```python
fraud_score_evidence = Evidence(
    context=context,
    evidence_type=EvidenceType.TOOL_RESULT,
    summary="Fraud detector scored the transaction 0.91 (high risk).",
    content_reference="fraud-detector://run/8841/score",
    confidence=0.97,
    quality=0.9,
)
```

Real captured output, produced by
[`examples/canonical_model_gallery.py`](https://github.com/samamuniharish/langgraph-xai/blob/main/examples/canonical_model_gallery.py):

```json
{
  "schema_version": "1.0.0",
  "id": "e42ff48a-9ecb-41e9-ba82-4a3d8cda4064",
  "evidence_type": "tool_result",
  "context": {
    "application_id": "application",
    "tenant_id": "default",
    "graph_id": "fraud-review",
    "run_id": "4aadf569-21b8-4d7a-a911-b0d71e7fbb0f"
  },
  "summary": "Fraud detector scored the transaction 0.91 (high risk).",
  "content_reference": "fraud-detector://run/8841/score",
  "source": null,
  "confidence": 0.97,
  "quality": 0.9,
  "metadata": {}
}
```

Note the fields it deliberately does **not** carry: no raw model prompt, no
full retrieved document body, no chain-of-thought — only a summary, a
resolvable reference, and a numeric confidence/quality pair. That is the
whole contract: evidence is a pointer plus a rationale, never a payload dump.

## Mistakes to avoid

Store a document ID, quoted approved span, and retrieval timestamp. Avoid
dumping all retrieved text, treating an absent citation as proof, or labeling
model output as independent evidence.


