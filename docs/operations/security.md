# Security

`langgraph-xai` records how decisions were made, so its records can be as
sensitive as the decisions themselves. This page lists what the library
protects by default and what a deployment must still decide.

## Built in

- **Credential redaction.** Values under credential-named keys are replaced
  with `"[not captured]"` before any record is created, including in state,
  metadata, interrupt payloads, resume answers, factor values, and source and
  document metadata. See [Redaction](../concepts/policies.md#redaction).
- **Minimal capture.** State capture records only changed keys by default, and
  tool payloads, documents, and memory are referenced, never copied.
- **No model reasoning.** Chain-of-thought is never requested, captured, or
  inferred.
- **Tenant isolation.** Every record carries application, tenant, and run IDs,
  and store queries are scoped by them.
- **Policy-filtered explanations.** Every explanation passes the exposure
  policy. If the policy fails, no explanation is returned.
- **Opt-in model calls.** LLM-phrased explanations need two explicit settings,
  and the model receives only the facts the policy allows.
- **No ambient configuration.** The core reads no environment variables.
  Provider SDKs read their own credentials, and nothing is enabled by the mere
  presence of a key.

## Your responsibilities

| Area | What to do |
| --- | --- |
| Personal data | Redaction works on key names, not values. Use `SELECTIVE` or `CUSTOM` capture, or a [capture policy](../concepts/policies.md#capture-policy), to keep personal data out of records. |
| Audience | Authenticate the caller before choosing the `audience` of an explanation. Policies trust the audience they are given. |
| Policies | Test every audience's view; see [Test disclosure policies](../how-to/disclosure-policies.md). |
| Storage | Restrict access to the store and tracing backends, encrypt at rest, and apply your retention period. A database store should run with a least-privileged role; see the [PostgreSQL store example](../examples/postgres-store.md#operating-it). |
| Model providers | LLM-phrased explanations send policy-allowed facts to the model provider. Use a provider and region your data agreements permit. |
| Failure mode | Choose `FAIL_CLOSED` where an action must not happen without its record; see [Configure failure modes](../how-to/failure-modes.md). |
| Secrets | Load provider credentials and database URLs from a secret store, never from source control. |
| Dependencies | Install only the extras you use, and pin versions in your application. |

## Reporting a vulnerability

Report vulnerabilities privately, as described in the repository's
[security policy](https://github.com/smuniharish/langgraph-xai/blob/master/SECURITY.md).
Do not open a public issue.
