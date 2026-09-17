# Provenance

## Kid-level view

Provenance is the “where did this come from?” label on every important fact.

```text
Bank API -> Transaction Record -> Fraud Detector -> Risk Score -> Decision
```

## Production view

Provenance links an artifact to execution IDs, source references, versions,
timestamps, and capture method. References are preferred over duplicated
payloads and must retain enough context to be resolved or reported missing.

## Why and architecture

The canonical layer carries provenance; storage and exporters preserve it.
Adapters must not invent source certainty when an upstream system provides
only correlation.

## Real example: input and output

Every `ProvenanceLink` is a `(source_id, target_id, relation)` triple plus
its own execution context. Relations are open strings, not a fixed enum —
`PRODUCED_BY`, `DERIVED_FROM`, and `SUPPORTED_BY` below are conventions, not
special-cased keywords:

```python
links = [
    ProvenanceLink(
        context=context,
        source_id="bank-api://acct/4471/txn/8841",
        target_id="transaction-record://8841",
        relation="PRODUCED_BY",
    ),
    ProvenanceLink(
        context=context,
        source_id="transaction-record://8841",
        target_id=str(fraud_score_evidence.id),
        relation="DERIVED_FROM",
    ),
    ProvenanceLink(
        context=context,
        source_id=str(fraud_score_evidence.id),
        target_id=str(decision.id),
        relation="SUPPORTED_BY",
    ),
]
for link in links:
    await store.write(link)

lineage = await store.lineage(str(decision.id), context=context)
```

Real captured result of `store.lineage(...)` — a real, ordered walk backward
from the decision to the original bank API call, produced by
[`examples/canonical_model_gallery.py`](https://github.com/samamuniharish/langgraph-xai/blob/main/examples/canonical_model_gallery.py):

```json
[
  {
    "source_id": "e42ff48a-9ecb-41e9-ba82-4a3d8cda4064",
    "target_id": "31406623-8b6d-4148-8d54-e2ab93a8a39f",
    "relation": "SUPPORTED_BY"
  },
  {
    "source_id": "transaction-record://8841",
    "target_id": "e42ff48a-9ecb-41e9-ba82-4a3d8cda4064",
    "relation": "DERIVED_FROM"
  },
  {
    "source_id": "bank-api://acct/4471/txn/8841",
    "target_id": "transaction-record://8841",
    "relation": "PRODUCED_BY"
  }
]
```

`provenance.parents(entity_id)` and `provenance.children(entity_id)` return
the same shape, scoped to one hop instead of a full walk — see
[`Provenance`](../architecture/provenance.md) for the query service.

## Mistakes to avoid

Reference a retrieval document ID and index version, not an unbounded document
copy. Do not omit source version, confuse correlation with causation, or lose
provenance during redaction.


