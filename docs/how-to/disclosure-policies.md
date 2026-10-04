# Test disclosure policies

A disclosure policy is a security control, so test it like one: for every
audience, assert what the explanation contains and what it must never contain.
This guide shows a focused pytest suite and the bundled matrix example.

## A test per audience

The test below records one decision and explains it to every built-in audience.
End users must see neither the attribution, nor the evidence, nor the fraud
score anywhere in the serialized explanation:

```python
import pytest

from langgraph_xai import Audience, DecisionFactor, PolicyProvider, XAIRuntime


@pytest.fixture
async def recorded():
    xai = XAIRuntime()
    xai.register(PolicyProvider, CustomerSafePolicy())
    run = await xai.start_run()
    score = await xai.record_evidence("tool_result", summary="Fraud score 0.91.", run=run)
    decision = await xai.record_decision(
        "HUMAN_REVIEW",
        evidence_ids=[score.id],
        factors=[DecisionFactor(name="fraud_risk_score", value=0.91, evidence_ids=[score.id])],
        run=run,
    )
    await xai.finish_run(run)
    return xai, run, decision


@pytest.mark.parametrize("audience", list(Audience))
async def test_only_internal_audiences_see_the_score(recorded, audience) -> None:
    xai, run, decision = recorded

    explanation = await xai.explain_decision(decision, audience=audience, run=run)

    if audience == Audience.END_USER:
        assert explanation.contributing_factors == explanation.supporting_evidence == []
        assert "0.91" not in explanation.model_dump_json(exclude={"timestamp"})
        assert "Customers receive the outcome and reasons only." in explanation.disclosure
    else:
        assert explanation.contributing_factors
        assert explanation.supporting_evidence
```

`CustomerSafePolicy` is the provider from
[Policies](../concepts/policies.md#exposure-policy). With `pytest-asyncio` in
auto mode:

```text
....                                                                     [100%]
4 passed in 0.98s
```

Checking the *serialized* explanation catches leaks through any field, not only
the ones you thought of. Here the score could appear in `reasons` as a factor
value; withholding `contributing_factors` removes it from there too. The
generated `timestamp` is excluded, because its fractional seconds can contain
any digits.

## Check the whole matrix

The [disclosure matrix example](../examples/disclosure-matrix.md) explains one
decision for every combination of two policies, four audiences, and both
engines, and asserts the policy on each row. Without an API key, it checks the
eight structured rows:

```text
audience   policy           engine     factors evidence  summary
developer  permissive       structured       4        2  The routing decision selected 'MANUAL_REVIEW'.  [0.00s]
developer  audience-scoped  structured       4        2  The routing decision selected 'MANUAL_REVIEW'.  [0.00s]
auditor    permissive       structured       4        2  The routing decision selected 'MANUAL_REVIEW'.  [0.00s]
auditor    audience-scoped  structured       4        2  The routing decision selected 'MANUAL_REVIEW'.  [0.00s]
business   permissive       structured       4        2  The routing decision selected 'MANUAL_REVIEW'.  [0.00s]
business   audience-scoped  structured       0        0  The routing decision selected 'MANUAL_REVIEW'.  [0.00s]
end_user   permissive       structured       4        2  The routing decision selected 'MANUAL_REVIEW'.  [0.00s]
end_user   audience-scoped  structured       0        0  The routing decision selected 'MANUAL_REVIEW'.  [0.00s]

8 combinations checked; every row matched its disclosure policy.
```

With `OPENAI_API_KEY` set, it adds the eight LLM-engine rows. Run it in CI to
catch a policy regression before it reaches users.

## What to assert

- **Withheld sections are empty** for each restricted audience.
- **Sensitive values never appear** in `model_dump_json()`. Check identifiers,
  scores, and names, not only section lengths.
- **Withholding is announced.** `disclosure` explains every withheld section,
  so a reader knows the explanation is partial.
- **A failing policy fails closed.** Register a provider that raises, and
  assert that `explain_decision` raises `XAIInstrumentationError` instead of
  returning an unfiltered explanation.
- **Allowlists stay tight.** If your policy uses `allowed_fields`, assert that a
  newly added section is withheld until you allow it explicitly.
