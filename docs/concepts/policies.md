# Policies

Three controls decide what is recorded and who may see it:

| Control | Applies to | Default |
| --- | --- | --- |
| [Redaction](#redaction) | Every free-form value before a record is created | Always on |
| [Capture policy](#capture-policy) | Each event, before it is recorded, stored, or emitted | Records everything |
| [Exposure policy](#exposure-policy) | Each explanation, per audience | Shows decision facts; notes that raw content and private memory are never included |

![The capture pipeline](../assets/diagrams/capture-pipeline.png)

Policies decide what explanations disclose. They do not authenticate users:
your application decides who the audience is before it asks for an
explanation.

## Redaction

Free-form values (state values, `metadata`, interrupt payloads, resume answers,
decision factor values, source and document metadata, and context metadata)
pass through `sanitize_value` before a record is created. It does two things.

**It withholds credentials.** A mapping key is treated as a credential when any
dot-separated part of it, after normalization (camelCase, `-`, and spaces become
`_`; case is ignored), equals a credential name or ends with `_<name>`. The
names are `password`, `passwd`, `passphrase`, `secret`, `token`, `api_key`,
`apikey`, `auth`, `authorization`, `bearer`, `cookie`, `set_cookie`,
`credential(s)`, `private_key`, `client_secret`, `access_token`,
`refresh_token`, `auth_token`, `session_token`, `secret_key`, `jwt`, `dsn`, and
`connection_string`.

- Credentials: `Authorization`, `x-api-key`, `OPENAI_API_KEY`, `accessToken`,
  `basic_auth`, `headers.authorization`, `db_password`
- Not credentials: `token_usage`, `max_tokens`, `author`, `oauth_provider`,
  `secretary`, `keyword`

The value of a credential key is replaced with `"[not captured]"`.

**It makes values JSON-safe.** Real output for a mixed input:

```json
{
  "when": "2026-01-02T03:04:05+00:00",
  "id": "12345678-1234-5678-1234-567812345678",
  "amount": "9200.50",
  "path": "/srv/models/fraud.onnx",
  "tier": "gold",
  "blob": "<3 bytes>",
  "tags": ["a", "b"],
  "ratio": "nan",
  "limit": "inf",
  "login": {"user": "ana", "password": "[not captured]"},
  "point": {"x": 1, "token": "[not captured]"},
  "headers": {"Authorization": "[not captured]", "Accept": "json"},
  "cyclic": {"name": "loop", "self": "[circular reference]"}
}
```

Datetimes, UUIDs, decimals, and paths become strings. Enums become their value,
and bytes become their length. Sets are sorted. Pydantic models and dataclasses
become mappings, redacted the same way. Non-finite floats become `"nan"` or
`"inf"`, reference cycles are cut, and nesting deeper than 32 levels becomes
`"[max depth exceeded]"`.

Redaction catches *obvious* credentials by name. It cannot recognize a secret
stored under an innocent key, or personal data such as an email address. Use
the [capture mode](../getting-started/configuration.md#state-capture) and a
capture policy to keep such data out of the records.

## Capture policy

A `CapturePolicy` sees every event before it is recorded and returns a
`PolicyDecision` whose `allowed` flag decides whether the event is kept. A
dropped event is kept nowhere: not in the store, not in the observability
backend, and not in the run's `Execution`.

```python
from langgraph_xai import CapturePolicy, PolicyAction, PolicyDecision


class NoStateValuesForEU:
    """EU tenants: record which nodes ran, but not the state values they changed."""

    async def evaluate(self, event) -> PolicyDecision:
        drop = event.event_type == "state.transition" and event.context.tenant_id.startswith("eu-")
        return PolicyDecision(
            context=event.context,
            policy_id="eu-data-minimization",
            action=PolicyAction.CAPTURE,
            allowed=not drop,
        )


xai.register(CapturePolicy, NoStateValuesForEU())
```

Running the same one-node graph for two tenants:

```text
us-bank: nodes=['classify'] state_transitions=1
eu-bank: nodes=['classify'] state_transitions=0
```

If the capture policy itself raises or times out, the event is **not**
captured, and the error is handled according to the
[failure mode](../getting-started/configuration.md#failure-modes).

## Exposure policy

When an explanation is requested, the registered `PolicyProvider` evaluates
`PolicyAction.EXPOSE` for the audience and returns a `PolicyDecision`. The
explanation engines withhold a section (`reasons`, `contributing_factors`, or
`supporting_evidence`) when:

- `allowed` is `False`. Every section is withheld.
- the section is in `denied_fields`.
- `allowed_fields` is not empty and does not name the section, so the field
  works as an allowlist.

Each withheld section adds a note to the explanation's `disclosure`, and the
policy's `reason`, if set, is added too.

The default `DefaultPolicyProvider` allows every section and records that raw
content and private memory are never exposed. Real output for an end user:

```json
{
  "policy_id": "default-exposure",
  "action": "expose",
  "allowed": true,
  "audience": "end_user",
  "reason": "Private memory and raw content are withheld by default.",
  "allowed_fields": [],
  "denied_fields": ["content_reference", "private_memory", "raw_content"],
  "metadata": {}
}
```

The built-in engines never read raw content or private memory, so these denied
fields document that guarantee. To scope disclosure per audience, register your
own provider:

```python
class CustomerSafePolicy:
    """End users see the outcome and reasons; other audiences see everything."""

    async def evaluate(self, context: ExplanationContext, action: PolicyAction) -> PolicyDecision:
        end_user = context.audience == Audience.END_USER
        return PolicyDecision(
            context=context.execution.context,
            policy_id="customer-safe",
            action=action,
            allowed=True,
            audience=context.audience,
            denied_fields={"contributing_factors", "supporting_evidence"} if end_user else set(),
            reason="Customers receive the outcome and reasons only." if end_user else None,
        )


xai.register(PolicyProvider, CustomerSafePolicy())
```

The [Explanations](explanations.md#example-two-audiences-one-decision) page
shows what this policy produces for an auditor and for a customer. To verify a
policy across every audience, see
[Test disclosure policies](../how-to/disclosure-policies.md).
