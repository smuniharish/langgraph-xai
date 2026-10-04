# Storage

A provenance store keeps the records that describe what happened: executions,
events, and provenance links. `langgraph-xai` ships one store,
`InMemoryProvenanceStore`, which every runtime uses by default. Any other
backend is a subclass of the `ProvenanceStore` abstract base class.

```python
from langgraph_xai import ProvenanceStore
```

## The base class

`ProvenanceStore` declares five abstract methods and implements two:

| Method | Kind | Behavior |
| --- | --- | --- |
| `write(item)` | abstract | Insert or replace an `Execution`, `ProvenanceLink`, or event. The latest write wins. |
| `get(entity_id)` | abstract | One record by its `id`, or `None` |
| `query(query)` | abstract | Records matching a `StoreFilter`, or your own `StoreQuery` subclass, in a stable order |
| `parents(entity_id, context=...)` | abstract | Links whose target is the entity, within one run |
| `children(entity_id, context=...)` | abstract | Links whose source is the entity, within one run |
| `lineage(entity_id, context=..., max_depth=100)` | inherited | Every upstream link, breadth-first and nearest first, visiting each entity once. Override it only for a faster native query. |
| `close()` | inherited | Does nothing. Override it to release connections. |

Every store must keep three promises:

- **Idempotent writes.** An `Execution` is written when its run starts, when it
  finishes, and again when a record is added after it finished. The store must
  upsert by record type and ID.
- **Isolation.** `query` returns records of one application and tenant only,
  and `parents` and `children` return links of one run only.
- **Stable order.** Results come back in the same order every time, by
  timestamp, then event sequence, then ID.

Because the lineage walk lives in the base class, every store returns lineage
with the same semantics.

## The default in-memory store

`InMemoryProvenanceStore` needs no setup. It is built for correctness under
concurrency, not just for demos:

- **Thread-safe.** One lock guards all indexes, so synchronous and
  asynchronous calls can share it.
- **Indexed.** Records are indexed by ID, by application and tenant, and
  provenance links by source and target, so `get`, scoped queries, and lineage
  walks never scan every record.
- **Copy-safe.** Records are stored as their JSON data and validated again on
  read. Mutating a returned record never changes the stored one.
- **Deterministic.** Query results are sorted by timestamp, event sequence,
  and ID.

It keeps records until the process exits, which suits development, tests, and
explaining runs within the same process.

## Using a database

Subclass `ProvenanceStore`, implement the five abstract methods, and register
an instance:

```python
xai.register(ProvenanceStore, MyDatabaseStore(...))
```

The [PostgreSQL store example](../examples/postgres-store.md) is a complete,
tested implementation to start from. It uses one JSONB table with indexes for
tenant and run isolation and idempotent upserts, and inherits `lineage`.
Records other than executions, events, and provenance links, such as evidence
and decisions, are delivered to [plugins](plugins.md), so a database-backed
deployment usually adds a plugin that writes them to the same database.
