import json
from contextlib import asynccontextmanager

import pytest

from examples import postgres_store as postgres_module
from examples.postgres_store import PostgresProvenanceStore
from langgraph_xai import Execution, ProvenanceLink, ProvenanceStore
from langgraph_xai.core import ExecutionStartedEvent
from langgraph_xai.storage import StoreFilter
from tests.helpers import context, execution


class FakeCursor:
    def __init__(self, rows: list[tuple]) -> None:
        self.rows = rows

    async def fetchall(self) -> list[tuple]:
        return self.rows


class FakePool:
    """Records every statement and answers SELECTs from rows or a responder function."""

    def __init__(self, rows: list[tuple] | None = None, responder=None) -> None:
        self.rows = rows or []
        self.responder = responder
        self.statements: list[tuple[str, tuple | None]] = []
        self.opened = 0
        self.closed = 0

    async def open(self) -> None:
        self.opened += 1

    async def close(self) -> None:
        self.closed += 1

    @asynccontextmanager
    async def connection(self):
        yield self

    async def execute(self, sql: str, params: tuple | None = None) -> FakeCursor:
        self.statements.append((" ".join(sql.split()), params))
        return FakeCursor(self.responder(params) if self.responder else self.rows)


def row(item) -> tuple[str, object]:
    return (type(item).__name__, item.model_dump(mode="json"))


async def test_open_creates_schema_and_indexes() -> None:
    pool = FakePool()
    store = PostgresProvenanceStore("unused", pool=pool)

    await store.open()

    ((sql, params),) = pool.statements
    assert pool.opened == 1
    assert params is None
    assert "CREATE TABLE IF NOT EXISTS langgraph_xai_records" in sql
    assert "langgraph_xai_entity_idx" in sql
    assert sql == " ".join(PostgresProvenanceStore.SCHEMA.split())


async def test_open_can_skip_schema_creation_for_restricted_roles() -> None:
    pool = FakePool()

    await PostgresProvenanceStore("unused", pool=pool).open(create_schema=False)

    assert pool.opened == 1
    assert pool.statements == []


class UnreachablePool(FakePool):
    @asynccontextmanager
    async def connection(self):
        raise ConnectionError("database unreachable")
        yield self


async def test_failed_open_closes_only_an_owned_pool() -> None:
    injected = UnreachablePool()
    with pytest.raises(ConnectionError):
        await PostgresProvenanceStore("unused", pool=injected).open()
    assert injected.closed == 0

    owned = PostgresProvenanceStore("unused", pool=UnreachablePool())
    owned._owns_pool = True
    with pytest.raises(ConnectionError):
        await owned.open()
    assert owned._pool.closed == 1


async def test_write_upserts_with_isolation_columns_and_event_ids() -> None:
    pool = FakePool()
    store = PostgresProvenanceStore("unused", pool=pool)
    event = ExecutionStartedEvent(context=context(), sequence=0)

    await store.write(event)

    sql, params = pool.statements[0]
    assert "ON CONFLICT (record_key) DO UPDATE" in sql
    assert params is not None
    assert params[:4] == (
        f"ExecutionStartedEvent:{event.id}",
        "ExecutionStartedEvent",
        "app",
        "tenant",
    )
    assert json.loads(params[6])["id"] == str(event.id)


async def test_get_decodes_by_record_type_and_detects_ambiguity() -> None:
    record = execution()
    store = PostgresProvenanceStore("unused", pool=FakePool([row(record)]))
    assert await store.get(str(record.id)) == record

    text_payload = PostgresProvenanceStore(
        "unused", pool=FakePool([("Execution", json.dumps(record.model_dump(mode="json")))])
    )
    assert await text_payload.get(str(record.id)) == record

    assert await PostgresProvenanceStore("unused", pool=FakePool()).get("missing") is None
    with pytest.raises(LookupError, match="ambiguous"):
        await PostgresProvenanceStore("unused", pool=FakePool([row(record)] * 2)).get("x")
    with pytest.raises(ValueError, match="unsupported record type"):
        await PostgresProvenanceStore("unused", pool=FakePool([("Unknown", {})])).get("x")


async def test_query_passes_filters_and_orders_like_the_memory_store() -> None:
    first = ExecutionStartedEvent(context=context(), sequence=0)
    pool = FakePool([row(first)])
    store = PostgresProvenanceStore("unused", pool=pool)
    query = StoreFilter(
        application_id="app",
        tenant_id="tenant",
        run_id=first.context.run_id,
        item_type=ExecutionStartedEvent,
        limit=5,
        offset=2,
    )

    items = [item async for item in store.query(query)]

    sql, params = pool.statements[0]
    assert items == [first]
    assert "ORDER BY timestamp, COALESCE((payload->>'sequence')::int, -1), payload->>'id'" in sql
    assert params == (
        "app",
        "tenant",
        str(first.context.run_id),
        str(first.context.run_id),
        "ExecutionStartedEvent",
        "ExecutionStartedEvent",
        5,
        2,
    )
    with pytest.raises(TypeError, match="StoreFilter"):
        [item async for item in store.query(object())]  # pyrefly: ignore[bad-argument-type]


async def test_link_queries_and_lineage() -> None:
    ctx = context()
    upstream = ProvenanceLink(source_id="a", target_id="b", relation="r", context=ctx)
    pool = FakePool([(upstream.model_dump(mode="json"),)])
    store = PostgresProvenanceStore("unused", pool=pool)

    assert await store.parents("b", context=ctx) == (upstream,)
    assert await store.children("a", context=ctx) == (upstream,)

    payload = json.dumps(upstream.model_dump(mode="json"))
    pool.responder = lambda params: [(payload,)] if params[4] == "b" else []
    assert await store.lineage("b", context=ctx, max_depth=3) == (upstream,)
    assert [(params or ())[3:] for _, params in pool.statements] == [
        ("target_id", "b"),
        ("source_id", "a"),
        ("target_id", "b"),
        ("target_id", "a"),
    ]
    with pytest.raises(ValueError, match="max_depth"):
        await store.lineage("b", context=ctx, max_depth=0)


async def test_only_owned_pools_are_closed() -> None:
    injected = FakePool()
    await PostgresProvenanceStore("unused", pool=injected).close()
    assert injected.closed == 0

    owned = PostgresProvenanceStore("postgresql://localhost/unused")
    await owned.close()
    assert owned._owns_pool


def test_missing_driver_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing(name: str) -> object:
        raise ImportError(name)

    monkeypatch.setattr(postgres_module, "import_module", missing)

    with pytest.raises(ImportError, match=r"psycopg\[binary,pool\]"):
        PostgresProvenanceStore("postgresql://localhost/unused")


def test_every_stored_record_type_can_be_decoded() -> None:
    assert {"Execution", "ProvenanceLink", "ExecutionStartedEvent", "InterruptEvent"} <= set(
        postgres_module._MODELS
    )
    assert Execution.__name__ in postgres_module._MODELS


def test_the_store_is_a_provenance_store_that_inherits_lineage() -> None:
    assert issubclass(PostgresProvenanceStore, ProvenanceStore)
    assert PostgresProvenanceStore.lineage is ProvenanceStore.lineage
