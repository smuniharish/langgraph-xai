# Concepts

`langgraph-xai` describes every run with a small set of typed records. Each
answers one question:

| Record | Question it answers | Produced by |
| --- | --- | --- |
| [Execution](execution.md) | What ran, in what order, with what outcome? | Instrumentation, automatically |
| [Evidence](evidence.md) | What information supported the outcome? | `record_evidence` in your code |
| [Decision](decisions.md) | What was chosen, from which alternatives, on which factors? | `record_decision` in your code |
| [Provenance](provenance.md) | Where did a piece of information come from? | `record_provenance` in your code |
| [Attribution](attribution.md) | How much did each factor and piece of evidence contribute? | An `AttributionEngine`, on demand |
| [Explanation](explanations.md) | How should the outcome be described to this audience? | An `ExplanationEngine`, on demand |

[Policies](policies.md) apply at every step: credentials are redacted before
anything is recorded, a capture policy can drop events, and an exposure policy
decides which parts of an explanation each audience sees.

![How the canonical records reference each other](../assets/diagrams/artifact-lineage.png)

## What is captured, and what is not

Instrumentation records **observable facts**: which nodes ran and how long they
took, how the state changed, which tools and retrievers were called, and where
a human paused or resumed the run. Your code records **the basis of a
decision**: the evidence it used and the action it chose.

`langgraph-xai` never records or infers a model's private reasoning
("chain of thought"). An explanation is built only from recorded facts, so
every statement in it can be traced back to a record.

## Shared properties

Every record is a Pydantic model with the same guarantees:

- **Versioned.** Each record carries `schema_version` (currently `"2.0.0"`),
  so stored data stays readable as the schema evolves. See
  [Canonical model](../architecture/canonical-model.md#compatibility).
- **Strict.** Unknown fields are rejected, numbers must be finite, and
  timestamps must be timezone-aware (UTC by default).
- **Identified and scoped.** Records carry a UUID `id` and an
  `ExecutionContext` with the application, tenant, graph, and run IDs. Stores
  use these IDs to keep tenants and runs apart.
- **JSON-safe.** Free-form fields (`metadata`, state values, interrupt
  payloads) are converted to JSON-compatible data, with credentials redacted,
  before the record is created.

Records are referenced by ID rather than copied. A decision lists the IDs of
its evidence, and evidence points to its full content through a
`content_reference` such as a document URI. Large or sensitive payloads stay in
the systems that own them.
