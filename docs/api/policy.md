# Policies

The default capture and exposure policies, and the redaction helpers applied to
every free-form value. See [Policies](../concepts/policies.md) for how they fit
together and how to write your own.

```python
from langgraph_xai.policy import REDACTED, is_sensitive_key, sanitize_value

assert is_sensitive_key("x-api-key")
assert sanitize_value({"Authorization": "Bearer abc"}) == {"Authorization": REDACTED}
```

## Default policies

::: langgraph_xai.policy.defaults.DefaultCapturePolicy

::: langgraph_xai.policy.defaults.DefaultPolicyProvider

## Redaction

::: langgraph_xai.policy.defaults.sanitize_value

::: langgraph_xai.policy.defaults.sanitize_mapping

::: langgraph_xai.policy.defaults.is_sensitive_key

::: langgraph_xai.policy.defaults.REDACTED
