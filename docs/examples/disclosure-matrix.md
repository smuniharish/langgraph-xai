# Disclosure matrix

One recorded underwriting decision is explained for every combination of two
exposure policies, the four built-in audiences, and both explanation engines.
Every row is checked against its policy, so a disclosure regression makes the
script fail. Source:
[`examples/explanation_disclosure_matrix.py`](https://github.com/smuniharish/langgraph-xai/blob/master/examples/explanation_disclosure_matrix.py).

```bash
uv run python examples/explanation_disclosure_matrix.py
```

## The policies

`PermissivePolicy` discloses everything to everyone. `AudienceScopedPolicy`
gives business and end-user audiences the outcome and reasons only:

```python
RESTRICTED = frozenset({Audience.BUSINESS, Audience.END_USER})


class AudienceScopedPolicy:
    async def evaluate(self, context: ExplanationContext, action: PolicyAction) -> PolicyDecision:
        restricted = context.audience in RESTRICTED
        return PolicyDecision(
            context=context.execution.context,
            policy_id="audience-scoped",
            action=action,
            allowed=True,
            audience=context.audience,
            denied_fields={"contributing_factors", "supporting_evidence"} if restricted else set(),
            reason="Outcome and reasons only." if restricted else "Full disclosure.",
        )
```

Each row registers a policy and an engine, explains the decision, and asserts
the result:

```python
withheld = policy_name == "audience-scoped" and audience in RESTRICTED
assert bool(explanation.contributing_factors) is not withheld
assert len(explanation.supporting_evidence) == (0 if withheld else 2)
```

## Output without a model

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

## Output with a live model

With `OPENAI_API_KEY` set, each combination also runs through
`LLMExplanationEngine`. Real output from a live OpenAI-compatible chat model:

```text
audience   policy           engine     factors evidence  summary
developer  permissive       structured       4        2  The routing decision selected 'MANUAL_REVIEW'.  [0.00s]
developer  permissive       llm              4        2  Manual review is required.  [3.59s]
developer  audience-scoped  structured       4        2  The routing decision selected 'MANUAL_REVIEW'.  [0.00s]
developer  audience-scoped  llm              4        2  Manual review required.  [2.84s]
auditor    permissive       structured       4        2  The routing decision selected 'MANUAL_REVIEW'.  [0.00s]
auditor    permissive       llm              4        2  Manual review is required.  [3.34s]
auditor    audience-scoped  structured       4        2  The routing decision selected 'MANUAL_REVIEW'.  [0.00s]
auditor    audience-scoped  llm              4        2  Manual review is required.  [2.15s]
business   permissive       structured       4        2  The routing decision selected 'MANUAL_REVIEW'.  [0.00s]
business   permissive       llm              4        2  Route the application to manual review.  [3.48s]
business   audience-scoped  structured       0        0  The routing decision selected 'MANUAL_REVIEW'.  [0.00s]
business   audience-scoped  llm              0        0  Route to manual review.  [3.11s]
end_user   permissive       structured       4        2  The routing decision selected 'MANUAL_REVIEW'.  [0.00s]
end_user   permissive       llm              4        2  Your application has been routed for manual review.  [2.74s]
end_user   audience-scoped  structured       0        0  The routing decision selected 'MANUAL_REVIEW'.  [0.00s]
end_user   audience-scoped  llm              0        0  Manual review  [2.03s]

16 combinations checked; every row matched its disclosure policy.
```

## What to notice

- **The policy, not the engine, decides disclosure.** The LLM rows withhold
  exactly what the structured rows withhold, because withheld sections never
  reach the model.
- **The model phrases, it does not decide.** Its summaries vary in wording, but
  attribution and evidence counts are identical to the deterministic engine's.
- **Run it in CI.** The assertions make the script a regression test for your
  policies; see [Test disclosure policies](../how-to/disclosure-policies.md).
