# Explanations

## Kid-level view

An explanation is a readable summary assembled from approved records and
honest about what is unknown.

## Production view

Explanation assembly consumes canonical artifacts, applies disclosure policy,
preserves uncertainty and attribution limitations, and identifies its schema
and renderer version. An optional LLM may phrase approved material only; it
must not become an implicit recorder of private reasoning.

## Why and architecture

Separating assembly from capture supports deterministic tests, multiple
audiences, and safe redaction at the final boundary.

## Real example: input and output

```python
explanation = await runtime.explain(
    ExplanationContext(
        execution=execution,
        decision=decision,
        evidence=[fraud_score_evidence, threshold_evidence],
        provenance=links,
        attribution=attribution,
        audience="auditor",
    )
)
```

Real captured output, produced by
[`examples/canonical_model_gallery.py`](https://github.com/samamuniharish/langgraph-xai/blob/main/examples/canonical_model_gallery.py)
(fields trimmed to the ones unique to this concept — see
[the full, untrimmed payload](../examples/full-explanation.md) for every
field):

```json
{
  "audience": "auditor",
  "summary": "The auditor explanation is based on the selected action 'HUMAN_REVIEW'.",
  "reasons": [
    "Selected action: HUMAN_REVIEW.",
    "Factor fraud_risk_score was 0.91.",
    "Factor review_threshold was 0.8."
  ],
  "supporting_evidence": [
    { "evidence_id": "e42ff48a-9ecb-41e9-ba82-4a3d8cda4064", "relationship": "supported_by" },
    { "evidence_id": "1e74b6d9-dc1e-4be2-8d75-9b5395b680f3", "relationship": "supported_by" }
  ],
  "contributing_factors": ["... same shape as Attribution.contributions, sorted by score ..."],
  "disclosure": ["Private memory and raw content are withheld by default."],
  "metadata": { "engine": "structured" }
}
```

Compare this to the `end_user` policy decision on the
[Policies](policies.md) page: the same underlying `Decision`/`Evidence`
produces a **different** `Explanation` per audience, because
`runtime.explain(...)` re-applies the registered `PolicyProvider` every call
— see the [disclosure-policy matrix](../examples/disclosure-matrix.md) for
all 16 real audience x policy x engine combinations side by side.

## Mistakes to avoid

Render “manual review was selected under rule R using sources A and B.” Avoid
inventing rationale, exposing raw prompts, or treating fluent prose as evidence.


