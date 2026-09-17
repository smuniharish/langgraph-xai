# Canonical model

## Kid-level view

The canonical model is a shared set of labeled cards so every output means the
same thing.

## Production view

Typed execution, provenance, evidence, decision, attribution, and explanation
records should carry schema identity/version, stable IDs, references, policy
outcomes, and uncertainty. Serialized shapes are versioned deliberately.

## Why and example

A canonical decision can feed a local renderer, a store, and an exporter
without each adapter inventing semantics. Prefer references and bounded
summaries over copied payloads.

## Common mistakes

Avoid provider-specific fields in the core, unversioned breaking changes, and
using a prose string as the only representation of a decision.

