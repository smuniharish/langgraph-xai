# Storage

`InMemoryProvenanceStore` is the default store of every runtime. Other backends
subclass the [`ProvenanceStore`](protocols.md#storage) base class; the
[PostgreSQL store example](../examples/postgres-store.md) is a complete one.
`StoreFilter` is the query object both use. See
[Storage architecture](../architecture/storage.md).

```python
from langgraph_xai import Execution, ProvenanceStore, StoreFilter

store = xai.registry.require(ProvenanceStore)
query = StoreFilter(application_id="payments", tenant_id="acme-bank", item_type=Execution)
async for execution in store.query(query):
    print(execution.context.run_id, execution.status)
```

::: langgraph_xai.storage.memory.InMemoryProvenanceStore

::: langgraph_xai.storage.memory.StoreFilter
