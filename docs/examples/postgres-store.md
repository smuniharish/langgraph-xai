# PostgreSQL store

`langgraph-xai` keeps records in memory by default. To keep them in a database,
subclass the `ProvenanceStore` base class. This example is a complete, tested
store for PostgreSQL that you can copy into your application: one JSONB table,
indexed for tenant and run isolation, written with idempotent upserts. Source:
[`examples/postgres_store.py`](https://github.com/smuniharish/langgraph-xai/blob/master/examples/postgres_store.py).

```bash
export XAI_POSTGRES_DSN=postgresql://user:password@localhost:5432/xai
uv run --group examples python examples/postgres_store.py
```

The example needs `psycopg[binary,pool]`, which the `examples` dependency group
installs. In your own project, add it to your dependencies.

## Subclassing `ProvenanceStore`

A store implements five methods and inherits the rest:

```python
class PostgresProvenanceStore(ProvenanceStore):
    async def write(self, item): ...  # insert or replace one record
    async def get(self, entity_id): ...  # one record by ID
    async def query(self, query): ...  # records of one application and tenant
    async def parents(self, entity_id, *, context): ...  # links into an entity, in one run
    async def children(self, entity_id, *, context): ...  # links out of an entity, in one run

    async def close(self): ...  # optional: the inherited close does nothing
```

`lineage` is inherited. It walks `parents` breadth-first, nearest first, and
visits each entity once, so every store gets the same lineage semantics. A
store can override it with a faster native query, such as a recursive SQL
query.

Writes are upserts on `"<record type>:<id>"`:

```python
async def write(self, item: StoredItem) -> None:
    record_type = type(item).__name__
    async with self._pool.connection() as connection:
        await connection.execute(
            """
            INSERT INTO langgraph_xai_records
                (record_key, record_type, application_id, tenant_id,
                 run_id, timestamp, payload)
            VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb)
            ON CONFLICT (record_key) DO UPDATE SET payload = EXCLUDED.payload
            """,
            (
                f"{record_type}:{_record_id(item)}",
                record_type,
                item.context.application_id,
                item.context.tenant_id,
                item.context.run_id,
                item.timestamp,
                item.model_dump_json(),
            ),
        )
```

## Using it

```python
store = PostgresProvenanceStore(os.environ["XAI_POSTGRES_DSN"])
await store.open()  # opens the pool, creates the table and indexes if needed

xai = XAIRuntime(application_id="payments", tenant_id="acme-bank", graph_id="fraud-review")
xai.register(ProvenanceStore, store)
graph = xai.instrument(builder.compile())
try:
    await graph.ainvoke({"transaction_id": "txn-8841"})
finally:
    await xai.close()  # flushes providers and closes the store's pool
```

To share a connection pool with the rest of your application, pass it in with
`PostgresProvenanceStore(dsn, pool=pool)`. A pool you pass in stays yours, and
`close()` does not close it.

!!! warning "Use asynchronous graph calls"
    The store uses psycopg's asynchronous pool, which belongs to the event loop
    that opened it. Record through `ainvoke`, `astream`, or `abatch`.
    Synchronous calls (`invoke`, `stream`, `batch`) record from a separate
    event loop, where the pool cannot be used.

!!! note "Windows"
    psycopg's asynchronous mode needs a selector event loop on Windows:
    `asyncio.run(main(), loop_factory=asyncio.SelectorEventLoop)`.

## Output

Real output against PostgreSQL 16. The demo runs a one-node graph that records
evidence and a provenance link, then reads the run back from the database:

```text
Stored 6 records for run a0cc4663-17db-4959-a214-3e521e89ba86:
  Execution: 1
  ExecutionCompletedEvent: 1
  ExecutionStartedEvent: 1
  NodeExecutionEvent: 1
  ProvenanceLink: 1
  StateTransitionEvent: 1
Lineage of the fraud score: ['18fc9ad5-a5fb-4ec4-b9ea-cd8596feae35 DERIVED_FROM transactions://txn-8841']
```

Six records were stored: the `Execution`, its four events, and the provenance
link. Evidence is not among them, because evidence is delivered to
[plugins](../architecture/plugins.md), not to the store.

## Schema

`PostgresProvenanceStore.SCHEMA` is the DDL that `open()` runs:

```sql
CREATE TABLE IF NOT EXISTS langgraph_xai_records (
    record_key TEXT PRIMARY KEY,        -- "<record type>:<id>"
    record_type TEXT NOT NULL,          -- Execution, ProvenanceLink, NodeExecutionEvent, ...
    application_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    run_id UUID NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    payload JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS langgraph_xai_scope_idx
    ON langgraph_xai_records (application_id, tenant_id, run_id, timestamp);
CREATE INDEX IF NOT EXISTS langgraph_xai_entity_idx
    ON langgraph_xai_records ((split_part(record_key, ':', 2)));
```

Every query filters on the application and tenant, and provenance queries also
filter on the run, using the `langgraph_xai_scope_idx` index.

## Operating it

- **Credentials.** The DSN is used to connect and is never written into
  records. Load it from your secret store.
- **Least privilege.** Creating the schema needs the `CREATE` privilege, even
  when the table already exists. Apply `PostgresProvenanceStore.SCHEMA` once
  with a privileged role, for example in a migration. Then run the application
  with a role limited to `SELECT`, `INSERT`, and `UPDATE` on
  `langgraph_xai_records`, and open the store with
  `await store.open(create_schema=False)`.
- **Retention.** Records are kept until you delete them. Apply your retention
  policy with SQL, for example
  `DELETE FROM langgraph_xai_records WHERE timestamp < now() - interval '400 days'`.

## Tests

The store's unit tests run against a fake connection pool. The live tests
write, query, and walk lineage against a real server, check tenant isolation,
persist an instrumented graph run end to end, and run this demo. Set
`XAI_TEST_POSTGRES_DSN` to a disposable database to run them; see
[Testing](../development/testing.md).
