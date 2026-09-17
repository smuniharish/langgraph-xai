# Disclosure-policy permutation matrix (real, multi-audience, multi-engine)

xgraph does not hard-code disclosure rules into the runtime. `PolicyProvider`
and `ExplanationEngine` are both swappable capabilities
([ADR-009](../architecture/decisions.md), [ADR-011](../architecture/decisions.md)).
This page is the real, reproducible proof: the same `XAIRuntime`, with zero
code changes, was run through **16 real permutations** —

- 2 policy providers: a **permissive** one (full disclosure to everyone) and
  an **audience-scoped** one (withholds attribution factors and supporting
  evidence from `business`/`end_user` audiences, discloses everything to
  `developer`/`auditor`)
- 4 audiences: `developer`, `auditor`, `business`, `end_user`
- 2 explanation engines: the deterministic `StructuredExplanationEngine` and
  the real, LLM-backed `LLMExplanationEngine` (model `gpt-5.6-luna` via an
  OpenAI-compatible endpoint)

Source: [`examples/explanation_disclosure_matrix.py`](https://github.com/samamuniharish/langgraph-xai/blob/main/examples/explanation_disclosure_matrix.py).

```bash
export EXPLABS_API_KEY=...
uv run --system-certs python examples/explanation_disclosure_matrix.py
```

## The two policy providers

```python
class AudienceScopedPolicyProvider:
    _RESTRICTED_AUDIENCES = frozenset({Audience.BUSINESS, Audience.END_USER})

    async def evaluate(self, context: ExplanationContext, action: PolicyAction) -> PolicyDecision:
        restricted = context.audience in self._RESTRICTED_AUDIENCES
        denied = {"contributing_factors", "supporting_evidence"} if restricted else set()
        return PolicyDecision(
            context=context.execution.context,
            policy_id="audience-scoped-disclosure",
            action=action,
            allowed=True,
            audience=context.audience,
            denied_fields=denied,
            reason=(
                "Business/end-user audiences receive outcome and reasons only "
                "(attribution and raw evidence withheld)."
                if restricted
                else "Developer/auditor audiences receive full disclosure."
            ),
        )
```

Swapping providers is one call: `runtime.register(PolicyProvider, policy)`.
No runtime, engine, or model code changes between permutations.

## Real captured results (excerpt)

Developer audience, audience-scoped policy, LLM engine — full disclosure:

```json
{
  "audience": "developer",
  "policy": "audience-scoped",
  "engine": "llm",
  "latency_ms": 5848.2,
  "summary": "Manual review required.",
  "reason_count": 1,
  "factor_count": 4,
  "evidence_count": 2,
  "disclosure": [
    "Developer/auditor audiences receive full disclosure."
  ]
}
```

End-user audience, the *same* audience-scoped policy, the *same* LLM engine —
attribution and evidence withheld:

```json
{
  "audience": "end_user",
  "policy": "audience-scoped",
  "engine": "llm",
  "latency_ms": 2458.4,
  "summary": "Manual review is required.",
  "reason_count": 1,
  "factor_count": 0,
  "evidence_count": 0,
  "disclosure": [
    "Attribution factors are withheld by policy.",
    "Supporting evidence is withheld by policy.",
    "Business/end-user audiences receive outcome and reasons only (attribution and raw evidence withheld)."
  ]
}
```

The permissive policy, same audience, same LLM engine — everything disclosed:

```json
{
  "audience": "end_user",
  "policy": "permissive",
  "engine": "llm",
  "latency_ms": 1741.6,
  "summary": "Your application requires manual review.",
  "reason_count": 2,
  "factor_count": 4,
  "evidence_count": 2,
  "disclosure": [
    "Permissive policy: full disclosure to all audiences."
  ]
}
```

## Summary across all 16 permutations (real run)

```text
Total permutations run: 16
LLM permutations succeeded: 8/8
LLM latency (ms): min=1741.6 max=8190.5 avg=4190.2

Verified: the same runtime, with zero code changes, enforces two different
real disclosure policies across four audiences and two explanation engines --
16/16 permutations produced the policy-correct disclosure outcome.
```

The script asserts, not just prints, the policy-correctness of every row:
every `business`/`end_user` + `audience-scoped` row has
`factor_count == 0` and `evidence_count == 0`; every `permissive` row
discloses all captured evidence regardless of audience. A failing assertion
would fail the script (and CI, if wired in), not just look wrong in a log.

## Why the LLM engine needed a real fix

The first run of this matrix **failed 8/8** on the LLM engine with:

```text
ValidationError: 1 validation error for ExplanationDraft
disclosure
  Input should be a valid list [type=list_type, input_value='This output uses only th...ovide hidden reasoning.', input_type=str]
```

`gpt-5.6-luna` returned a single sentence for `disclosure` instead of a JSON
array — a common real-world model formatting slip. This was fixed two ways,
both in `LLMExplanationEngine`, and both are exercised in
`tests/explanation/test_engines.py`:

1. The prompt now spells out an explicit `output_schema` with per-field types
   and states "MUST be a JSON array of strings, never a single string".
2. The engine's response-validation step now normalizes a scalar string into
   a one-element list for the `reasons`/`disclosure` fields — a pure
   formatting fix, not a schema relaxation: unknown/extra fields (e.g. a
   model trying to smuggle a `hidden_reasoning` field) are still rejected
   outright (see [ADR-013](../architecture/decisions.md)).

This is exactly the kind of real, provider-facing rough edge you should
expect to hit and plan for when wiring an LLM explanation engine to a live
model, and it is why the matrix above is worth re-running against any new
model you plan to use for explanations.
