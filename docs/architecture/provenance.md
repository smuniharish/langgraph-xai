# Provenance

Provenance links form a directed graph from source entities to the entities
derived from them. This page describes how that graph is stored and walked.
[Concepts: Provenance](../concepts/provenance.md) covers how to record it.

## Identity

`source_id` and `target_id` are entity IDs: the UUID of a recorded artifact,
such as evidence or a decision, or any string that identifies an external
entity, such as a URI or a database key. UUIDs and their string forms refer to
the same entity, so `store.lineage(str(decision.id), ...)` finds links recorded
with `decision.id`.

Each link is itself a record with its own `id`, timestamp, and
`ExecutionContext`. It is stored like any other record and is scoped to the run
that recorded it.

## Walking lineage

`lineage(entity_id, context=..., max_depth=100)` walks upstream breadth-first:

1. Find the links whose target is the entity (`parents`).
2. Add their sources to the next frontier, skipping entities already visited.
3. Repeat until no new sources remain or `max_depth` levels have been walked.

The result is every upstream link, nearest first. Each entity is expanded once
and each link has a single target, so every link appears exactly once and
cycles terminate. The cost is one `parents` query per visited entity.

## Scoping

Provenance queries are scoped to the application, tenant, and run of the
`context` you pass. Two consequences follow:

- **Isolation.** A tenant can never walk into another tenant's lineage, even
  when entity IDs collide.
- **Per-run lineage.** A link recorded in one run is not visible from another.
  To trace an entity across runs, record the cross-run link in the run that
  uses the entity, or query each run's context in turn.
