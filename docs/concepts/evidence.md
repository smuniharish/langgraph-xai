# Evidence

`Evidence` is a piece of information your application relied on: a model score,
a retrieved passage, a tool result, a business rule. It is recorded explicitly,
at the point where the information is used:

```python
score = await xai.record_evidence(
    EvidenceType.TOOL_RESULT,
    summary="Fraud detector scored the transaction 0.91 (high risk).",
    content_reference="fraud-detector://scores/txn-8841",
    confidence=0.97,
    quality=0.9,
)
```

`record_evidence` returns the record, whose `id` you pass to a
[decision](decisions.md). Inside an instrumented call it is added to the current
run. Elsewhere, pass `run=` explicitly.

## Fields

| Field | Meaning |
| --- | --- |
| `evidence_type` | What kind of information this is: `state`, `tool_result`, `retrieval_document`, `memory`, `rule`, `policy`, `model_output`, `custom`, or your own string. |
| `summary` | A short, human-readable statement of what the evidence shows. It appears in explanations. |
| `content_reference` | Where the full content lives (a URI or document ID), so the content itself is never copied. |
| `source` | A `SourceReference` (`source_id`, `source_type`, optional `uri`) naming the system it came from. |
| `confidence` | How certain the information is, from 0 to 1, if the source provides it. |
| `quality` | How reliable the source is, from 0 to 1. |
| `metadata` | Any additional JSON-safe fields. Credentials are redacted. |

## Recorded evidence

From the [canonical model gallery](https://github.com/smuniharish/langgraph-xai/blob/master/examples/canonical_model_gallery.py)
(context omitted):

```json
{
  "schema_version": "2.0.0",
  "id": "a454462d-9b9c-4154-813c-ca46f2bd7a27",
  "timestamp": "2026-10-04T13:36:40.775807Z",
  "evidence_type": "tool_result",
  "summary": "Fraud detector scored the transaction 0.91 (high risk).",
  "content_reference": "fraud-detector://scores/txn-8841",
  "source": null,
  "confidence": 0.97,
  "quality": 0.9,
  "metadata": {}
}
```

## How evidence is used

- A decision lists the evidence it relied on in `evidence_ids`, and each
  decision factor can name its own evidence.
- [Attribution](attribution.md) scores each referenced piece of evidence as
  `confidence × quality`, with a missing value counting as 1.0.
- An [explanation](explanations.md) references the decision's evidence in
  `supporting_evidence`, unless the audience's policy withholds it.

## Where evidence is kept

Evidence is kept on the run (`run.evidence`) and delivered to every registered
[plugin](../architecture/plugins.md) as it is recorded. It is not written to the
`ProvenanceStore`, which holds executions, events, and provenance links. To
persist evidence, register a plugin that writes it to your system of record.

## Guidance

- **Record facts, not reasoning.** "Fraud model scored 0.91" is evidence.
  A model's internal deliberation is not.
- **Reference, don't embed.** Put the document URI in `content_reference` and a
  one-sentence description in `summary`. Raw documents, prompts, and payloads
  stay in the systems that own them.
- **Use `retrieval_document` per passage.** When a decision relies on retrieved
  passages, record one evidence item per passage you used, with the retriever's
  score as `confidence`. The
  [retrieval and tools example](../examples/retrieval-and-tools.md) does exactly
  this with captured retrievals.
- **Connect evidence to its origin** with [provenance](provenance.md) when the
  path from raw data to evidence matters for an audit.
