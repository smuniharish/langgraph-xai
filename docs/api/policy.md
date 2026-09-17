# Policy providers

## `DefaultCapturePolicy`

Registered automatically. Allows every canonical event to be captured after
`sanitize_mapping`/`sanitize_value` have replaced obvious credential-shaped
keys (`api_key`, `password`, `token`, `secret`, `authorization`, `cookie`,
…) with `"[not captured]"`. This is a minimal safety net against accidental
secret capture, **not** a PII-detection or general redaction engine — see
[Concepts: Policies](../concepts/policies.md) for that boundary.

## `DefaultPolicyProvider`

Registered automatically. On `evaluate(context, PolicyAction.EXPOSE)`,
denies `private_memory`, `raw_content`, and `content_reference` for every
audience — see the real, captured decision on
[Concepts: Policies](../concepts/policies.md) and the full
audience x policy matrix on
[the disclosure-matrix example](../examples/disclosure-matrix.md).

## Writing your own

```python
from langgraph_xai.core.models import PolicyAction, PolicyDecision
from langgraph_xai.core.protocols import PolicyProvider


class AuditorFullDisclosurePolicy:
    async def evaluate(self, context, action):
        denied = set() if context.audience == "auditor" else {"raw_content"}
        return PolicyDecision(
            context=context.execution.context,
            policy_id="auditor-full-disclosure",
            action=action,
            allowed=True,
            audience=context.audience,
            denied_fields=denied,
            reason="Auditors receive full disclosure; other audiences do not.",
        )


runtime.register(PolicyProvider, AuditorFullDisclosurePolicy())
```

## Reference

::: langgraph_xai.policy.DefaultCapturePolicy

::: langgraph_xai.policy.DefaultPolicyProvider

::: langgraph_xai.policy.sanitize_value

::: langgraph_xai.policy.sanitize_mapping
