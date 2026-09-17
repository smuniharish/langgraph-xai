# Policies

## Kid-level view

A policy is the set of rules deciding what may be kept, shared, or hidden.

## Production view

Apply policy at capture, canonicalization, storage, export, and rendering.
Represent outcomes such as allow, omit, redact, and reference-only, and make
fail-open/fail-closed behavior explicit for each boundary.

## Why and architecture

Late-only filtering leaks data into logs or stores. Early-only filtering can
make approved explanations impossible, so every boundary needs a deliberate
decision and test fixture.

## Real example: input and output

`runtime.explain(...)` calls the registered `PolicyProvider` for you; you
never call it directly in application code. This shows what it evaluates
under the hood, for the built-in `DefaultPolicyProvider`, given an
`end_user` audience:

```python
policy_provider = runtime.registry.require(PolicyProvider)
decision = await policy_provider.evaluate(end_user_context, PolicyAction.EXPOSE)
```

Real captured output, produced by
[`examples/canonical_model_gallery.py`](https://github.com/samamuniharish/langgraph-xai/blob/main/examples/canonical_model_gallery.py):

```json
{
  "schema_version": "1.0.0",
  "policy_id": "default-exposure",
  "action": "expose",
  "allowed": true,
  "audience": "end_user",
  "reason": "Private memory and raw content are withheld by default.",
  "allowed_fields": [],
  "denied_fields": ["raw_content", "private_memory", "content_reference"],
  "obligations": []
}
```

`allowed: true` plus `denied_fields` is intentional: the export as a whole is
permitted, but specific fields are stripped from the resulting `Explanation`
before it is ever returned to the caller — see
[Explanations](explanations.md) for what the caller actually receives once
this decision has been applied.

## Mistakes to avoid

Keep a document ID and redact its sensitive span. Do not treat exporter
configuration as a substitute for capture policy or silently downgrade a
policy error.


