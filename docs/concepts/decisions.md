# Decisions

A `Decision` records what your application chose and on what basis: the
selected action, the alternatives it considered, the factors that drove the
choice, and the evidence behind them. It is recorded explicitly, in the node
where the choice is made:

```python
decision = await xai.record_decision(
    "HUMAN_REVIEW",
    decision_type=DecisionType.ROUTING,
    candidate_actions=["AUTO_APPROVE", "HUMAN_REVIEW", "AUTO_DECLINE"],
    evidence_ids=[score.id, threshold.id],
    factors=[
        DecisionFactor(name="fraud_risk_score", value=0.91, weight=0.8, evidence_ids=[score.id]),
        DecisionFactor(name="review_threshold", value=0.8, weight=0.2, evidence_ids=[threshold.id]),
    ],
    confidence=0.91,
)
```

## Fields

| Field | Meaning |
| --- | --- |
| `selected_action` | The action that was taken. |
| `decision_type` | `routing`, `classification`, `tool_selection`, `approval`, `rejection`, `escalation`, `hitl`, `final_response`, `custom` (the default), or your own string. |
| `candidate_actions` | Every action that was considered, including the selected one. |
| `factors` | Named inputs to the choice. Each `DecisionFactor` has a `name`, a JSON-safe `value`, an optional `weight`, and optional `evidence_ids`. |
| `evidence_ids` | The [evidence](evidence.md) the decision relied on. |
| `provenance_ids` | IDs of related [provenance links](provenance.md). |
| `policy_references` | Identifiers of business rules or policies that were applied. |
| `confidence`, `uncertainty` | Optional values from 0 to 1. |
| `metadata` | Any additional JSON-safe fields. Credentials are redacted. |

## Recorded decision

From the [canonical model gallery](https://github.com/smuniharish/langgraph-xai/blob/master/examples/canonical_model_gallery.py)
(context omitted):

```json
{
  "schema_version": "2.0.0",
  "id": "572816a2-2af3-4dd8-a35f-59c83e698333",
  "timestamp": "2026-10-04T13:36:40.776079Z",
  "decision_type": "routing",
  "selected_action": "HUMAN_REVIEW",
  "candidate_actions": ["AUTO_APPROVE", "HUMAN_REVIEW", "AUTO_DECLINE"],
  "evidence_ids": [
    "a454462d-9b9c-4154-813c-ca46f2bd7a27",
    "15425043-3857-4c55-8849-fd05c868c246"
  ],
  "provenance_ids": [],
  "factors": [
    {
      "schema_version": "2.0.0",
      "name": "fraud_risk_score",
      "value": 0.91,
      "evidence_ids": ["a454462d-9b9c-4154-813c-ca46f2bd7a27"],
      "weight": 0.8,
      "metadata": {}
    },
    {
      "schema_version": "2.0.0",
      "name": "review_threshold",
      "value": 0.8,
      "evidence_ids": ["15425043-3857-4c55-8849-fd05c868c246"],
      "weight": 0.2,
      "metadata": {}
    }
  ],
  "policy_references": [],
  "confidence": 0.91,
  "uncertainty": null,
  "metadata": {}
}
```

## Explaining a decision

Every recorded decision is kept on its run (`run.decisions`) and delivered to
registered plugins. To explain one after the graph call returns, keep the run
with `collect_runs` and pass both to `explain_decision`:

```python
with xai.collect_runs() as runs:
    await graph.ainvoke(payload)
(run,) = runs
explanation = await xai.explain_decision(run.decisions[-1], audience=Audience.AUDITOR, run=run)
```

`explain_decision` gathers the evidence the decision and its factors reference
(or all of the run's evidence, if the decision references none),
[attributes](attribution.md) the decision, applies the exposure
[policy](policies.md), and renders the [explanation](explanations.md).

## Guidance

- **Record the decision where it is made**, with the alternatives that were
  really available. An explanation can only mention what was recorded.
- **Give factors weights when they reflect policy.** The default attribution
  engine uses a factor's `weight` as its score, and treats a factor without a
  weight as 1.0.
- **Keep factor values free of personal data an audience must not see.**
  Factor values appear in explanation reasons. A policy that withholds
  `contributing_factors` removes them, but values that are never recorded never
  need withholding.
- **Agents with model-chosen actions** (for example `create_agent`) can record
  the decision in a middleware or tool after the model responds; see the
  [create_agent example](../examples/create-agent.md).
