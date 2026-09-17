# How to test disclosure policies

**Goal:** prove, before shipping, that your `PolicyProvider` discloses
exactly what you intend to each audience — and nothing more — across every
explanation engine you use.

## Steps

1. Implement `PolicyProvider.evaluate(context, action)` to return a
   `PolicyDecision` with `denied_fields` scoped to the audience:

   ```python
   class AudienceScopedPolicyProvider:
       async def evaluate(self, context, action):
           restricted = context.audience in {Audience.BUSINESS, Audience.END_USER}
           denied = {"contributing_factors", "supporting_evidence"} if restricted else set()
           return PolicyDecision(
               context=context.execution.context,
               policy_id="...",
               action=action,
               allowed=True,
               audience=context.audience,
               denied_fields=denied,
           )
   ```

2. Register it on the runtime: `runtime.register(PolicyProvider, provider)`.

3. Build one representative `ExplanationContext` fixture (a real `Decision`
   with `Evidence` and factors) and loop over every `(audience, engine)`
   combination you plan to support, calling `runtime.explain(context)` for
   each — swap `ExplanationEngine` with `runtime.register(ExplanationEngine, ...)`
   between structured and LLM variants.

4. Assert the policy-correct shape for every permutation, don't just print
   it:

   ```python
   assert all(len(explanation.contributing_factors) == 0 for restricted_rows)
   assert all(len(explanation.supporting_evidence) == 2 for permissive_rows)
   ```

5. Re-run this matrix whenever you change your policy provider, your
   evidence/decision fixtures, or the LLM model you use for explanations —
   provider-side prompt compliance can vary (see the gotcha below).

## Full example and real captured output

See the [disclosure-policy permutation matrix](../examples/disclosure-matrix.md):
16 real permutations (2 policies x 4 audiences x 2 engines, including a real
LLM), each asserted for policy-correctness, with real latency numbers.

## Gotcha: LLM output schema compliance

The first real run of the matrix failed 8/8 on the LLM engine because the
model returned a single string instead of a JSON array for `disclosure`. This
was fixed by (1) making the prompt's schema instructions more explicit and
(2) normalizing a scalar string into a one-item list — without weakening the
validator's rejection of genuinely unknown/extra fields. See the
["Why the LLM engine needed a real fix"](../examples/disclosure-matrix.md#why-the-llm-engine-needed-a-real-fix)
section for the exact error and fix.
