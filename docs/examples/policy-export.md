# Policy-filtered export

An export adapter — a UI, a report generator, an observability sink, or an
API response — should only ever receive the *already policy-filtered*
`Explanation`, never the raw `ExplanationContext`. The `PolicyProvider`
decision (`denied_fields`, `redactions`) is applied inside
`runtime.explain(...)` before the result is returned, so a caller cannot
accidentally bypass it just because it has access to a broader schema
upstream (the full `Decision`/`Evidence` graph in the store):

| Input | Policy result | What an exporter receives |
| --- | --- | --- |
| Approved decision, `Audience.DEVELOPER` | allow | full `contributing_factors` and `supporting_evidence` |
| Same decision, `Audience.END_USER` | restrict | `denied_fields` removed from the `Explanation`; `summary` and `disclosure` still present |
| Attribution weights, `Audience.REGULATOR` | allow with rationale | full factors plus policy `rationale` string retained for audit |

This is not a hypothetical table — it is exactly what
[the disclosure-policy permutation matrix](disclosure-matrix.md) verifies
for real, across 16 real `(policy, audience, engine)` combinations, asserting
the exact field-level shape for each. Read that page for the real code and
real captured `Explanation` JSON per audience.

## The rule enforced by this boundary

Test the same fixture at capture, storage, export, and rendering boundaries.
An exporter must not bypass the policy because it has a broader schema — this
is why `ExplanationContext.policies` is populated by the runtime itself
(via `PolicyProvider.evaluate(...)`) rather than left for each call site to
apply independently. See
[ADR-009](../architecture/decisions.md#adr-009-policy-applies-across-capture-retention-processing-and-exposure).

