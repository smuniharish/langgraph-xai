# Storage

## `InMemoryProvenanceStore` (default)

Process-local, concurrency-safe, and tenant/application isolated. Registered
automatically by `XAIRuntime()`, so development and tests work without any
external database.

```python
from langgraph_xai.storage import InMemoryProvenanceStore, StoreFilter

store = InMemoryProvenanceStore()
runtime.register(ProvenanceStore, store)

# Direct query, scoped to one application/tenant/run:
records = [
    item
    async for item in store.query(
        StoreFilter(application_id="bank-fraud", tenant_id="default", run_id=str(run_id))
    )
]
```

## `PostgresProvenanceStore` (production)

A real, JSONB-backed `ProvenanceStore` shipped in the `postgres` extra
(`uv add "langgraph-xai[postgres]"`), storing every canonical record as a row
keyed by an idempotent `record_key`, indexed by
`(application_id, tenant_id, run_id, timestamp)`:

```python
from langgraph_xai.storage import PostgresProvenanceStore

store = PostgresProvenanceStore("postgresql://user:pass@localhost/xai")
await store.open()  # creates the table/index if they don't exist
runtime.register(ProvenanceStore, store)
...
await store.close()
```

`write(...)` is an upsert (`ON CONFLICT ... DO UPDATE`), so retried writes
for the same entity are safe. `lineage(...)` performs the same breadth-first
walk as `InMemoryProvenanceStore`, one SQL query per depth level.

For any other backend, implement `ProvenanceStore` directly — see
[Protocols](protocols.md) for the contract, and
[Architecture: Storage](../architecture/storage.md) for the isolation and
consistency guarantees a store should preserve.

## Reference

::: langgraph_xai.storage.InMemoryProvenanceStore

::: langgraph_xai.storage.memory.StoreFilter

::: langgraph_xai.storage.PostgresProvenanceStore
