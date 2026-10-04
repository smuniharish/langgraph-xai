import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, rule

from langgraph_xai import Execution, ExecutionStatus, ProvenanceLink
from langgraph_xai.core import ExecutionStartedEvent
from langgraph_xai.storage import InMemoryProvenanceStore, StoreFilter
from tests.helpers import context, execution


def link(source: str, target: str, ctx=None, **kwargs) -> ProvenanceLink:
    return ProvenanceLink(
        source_id=source,
        target_id=target,
        relation="DERIVED_FROM",
        context=ctx or context(),
        **kwargs,
    )


async def collect(store: InMemoryProvenanceStore, query: StoreFilter) -> list:
    return [item async for item in store.query(query)]


async def test_lineage_walks_upstream_once_per_link_and_survives_cycles() -> None:
    store = InMemoryProvenanceStore()
    ctx = context()
    links = [link("a", "b", ctx), link("b", "c", ctx), link("c", "a", ctx), link("x", "c", ctx)]
    for item in links:
        await store.write(item)
        await store.write(item)

    lineage = await store.lineage("c", context=ctx)
    nearest = await store.lineage("c", context=ctx, max_depth=1)

    assert sorted(str(item.id) for item in lineage) == sorted(str(item.id) for item in links)
    assert {item.source_id for item in nearest} == {"b", "x"}
    with pytest.raises(ValueError, match="max_depth"):
        await store.lineage("c", context=ctx, max_depth=0)


async def test_parents_and_children_are_scoped_to_one_run() -> None:
    store = InMemoryProvenanceStore()
    first, second = context(), context()
    await store.write(link("a", "b", first))
    await store.write(link("a", "b", second))

    assert len(await store.parents("b", context=first)) == 1
    assert [item.target_id for item in await store.children("a", context=second)] == ["b"]
    assert await store.parents("a", context=first) == ()


async def test_query_filters_orders_and_paginates() -> None:
    store = InMemoryProvenanceStore()
    ctx = context()
    record = execution(ctx)
    events = [ExecutionStartedEvent(context=ctx, sequence=index) for index in range(5)]
    timestamp = events[0].timestamp
    for event in reversed(events):
        await store.write(event.model_copy(update={"timestamp": timestamp}))
    await store.write(record)
    await store.write(link("a", "b", context("other")))

    everything = await collect(store, StoreFilter(application_id="app", tenant_id="tenant"))
    page = await collect(
        store,
        StoreFilter(
            application_id="app",
            tenant_id="tenant",
            run_id=ctx.run_id,
            item_type=ExecutionStartedEvent,
            limit=2,
            offset=1,
        ),
    )
    executions_only = await collect(
        store, StoreFilter(application_id="app", tenant_id="tenant", item_type=Execution)
    )

    assert len(everything) == 6
    assert [item.sequence for item in page] == [1, 2]
    assert executions_only == [record]
    assert await collect(store, StoreFilter(application_id="app", tenant_id="none")) == []


async def test_get_returns_isolated_copies_and_detects_ambiguity() -> None:
    store = InMemoryProvenanceStore()
    record = execution()
    await store.write(record)
    event = ExecutionStartedEvent(context=context(), sequence=0)
    await store.write(event)

    fetched = await store.get(str(record.id))
    assert fetched == record
    assert fetched is not record
    fetched.metadata["mutated"] = True  # pyrefly: ignore[missing-attribute]
    record.status = ExecutionStatus.FAILED
    assert await store.get(str(record.id)) == record.model_copy(
        update={"status": ExecutionStatus.COMPLETED}
    )
    assert await store.get(str(event.id)) == event
    assert await store.get(str(uuid4())) is None

    clash = link("a", "b", id=record.id)
    await store.write(clash)
    with pytest.raises(LookupError, match="ambiguous"):
        await store.get(str(record.id))


async def test_rewriting_a_link_reindexes_it() -> None:
    store = InMemoryProvenanceStore()
    ctx = context()
    original = link("a", "b", ctx)
    await store.write(original)
    await store.write(original.model_copy(update={"target_id": "c"}))

    assert await store.parents("b", context=ctx) == ()
    assert [item.source_id for item in await store.parents("c", context=ctx)] == ["a"]


async def test_concurrent_writes_from_many_tasks_are_all_kept() -> None:
    store = InMemoryProvenanceStore()
    ctx = context()
    links = [link(f"source-{index}", "decision", ctx) for index in range(300)]

    await asyncio.gather(*(store.write(item) for item in links))

    assert len(await store.parents("decision", context=ctx)) == 300


async def test_closed_store_rejects_operations_and_unknown_queries() -> None:
    store = InMemoryProvenanceStore()
    with pytest.raises(TypeError, match="StoreFilter"):
        await collect(store, object())  # pyrefly: ignore[bad-argument-type]
    await store.close()

    with pytest.raises(RuntimeError, match="closed"):
        await store.write(execution())
    with pytest.raises(RuntimeError, match="closed"):
        await store.get("x")
    with pytest.raises(RuntimeError, match="closed"):
        await store.parents("x", context=context())
    with pytest.raises(RuntimeError, match="closed"):
        await store.lineage("x", context=context())


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [({"limit": 0}, "limit"), ({"offset": -1}, "offset"), ({"run_id": "nope"}, "UUID")],
)
def test_store_filter_validation(kwargs: dict, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        StoreFilter(application_id="a", tenant_id="t", **kwargs)


def test_store_filter_normalizes_run_ids() -> None:
    identifier = uuid4()

    assert StoreFilter(application_id="a", tenant_id="t", run_id=identifier).run_id == str(
        identifier
    )
    assert StoreFilter(
        application_id="a", tenant_id="t", run_id=str(identifier).upper()
    ).run_id == (str(identifier))


NODES = st.sampled_from(list("abcdef"))


class LinkStoreMachine(RuleBasedStateMachine):
    """Drive the store with random writes and compare every query with a reference model."""

    def __init__(self) -> None:
        super().__init__()
        self.store = InMemoryProvenanceStore()
        self.context = context()
        self.model: dict[str, ProvenanceLink] = {}
        # One loop per run: creating a loop per call churns sockets on Windows.
        self.loop = asyncio.new_event_loop()

    def _run(self, coroutine):
        return self.loop.run_until_complete(coroutine)

    def teardown(self) -> None:
        self.loop.close()

    @rule(source=NODES, destination=NODES)
    def write_link(self, source: str, destination: str) -> None:
        item = link(source, destination, self.context)
        self._run(self.store.write(item))
        self.model[str(item.id)] = item

    @rule(data=st.data(), destination=NODES)
    def retarget_existing_link(self, data: st.DataObject, destination: str) -> None:
        if not self.model:
            return
        key = data.draw(st.sampled_from(sorted(self.model)))
        moved = self.model[key].model_copy(update={"target_id": destination})
        self._run(self.store.write(moved))
        self.model[key] = moved

    def _expected_parents(self, node: str) -> set[str]:
        return {key for key, item in self.model.items() if item.target_id == node}

    def _expected_lineage(self, node: str) -> set[str]:
        seen, frontier, result = {node}, [node], set()
        while frontier:
            current = frontier.pop()
            for key in self._expected_parents(current):
                result.add(key)
                source = str(self.model[key].source_id)
                if source not in seen:
                    seen.add(source)
                    frontier.append(source)
        return result

    @invariant()
    def queries_match_the_model(self) -> None:
        for node in "abcdef":
            parents = self._run(self.store.parents(node, context=self.context))
            children = self._run(self.store.children(node, context=self.context))
            lineage = self._run(self.store.lineage(node, context=self.context))
            assert {str(item.id) for item in parents} == self._expected_parents(node)
            assert {str(item.id) for item in children} == {
                key for key, item in self.model.items() if item.source_id == node
            }
            assert len(lineage) == len({str(item.id) for item in lineage})
            assert {str(item.id) for item in lineage} == self._expected_lineage(node)
        records = self._run(
            collect(self.store, StoreFilter(application_id="app", tenant_id="tenant", limit=500))
        )
        assert {str(item.id) for item in records} == set(self.model)


LinkStoreMachine.TestCase.settings = settings(max_examples=40, stateful_step_count=15)
TestLinkStore = LinkStoreMachine.TestCase


@given(
    stamps=st.lists(st.tuples(st.integers(0, 2), st.integers(0, 3)), max_size=20),
    page_size=st.integers(1, 7),
)
async def test_pages_partition_the_ordered_results(
    stamps: list[tuple[int, int]], page_size: int
) -> None:
    store = InMemoryProvenanceStore()
    ctx = context()
    base = datetime(2026, 1, 1, tzinfo=UTC)
    for second, sequence in stamps:
        await store.write(
            ExecutionStartedEvent(
                context=ctx, sequence=sequence, timestamp=base + timedelta(seconds=second)
            )
        )

    def page(offset: int, limit: int) -> StoreFilter:
        return StoreFilter("app", "tenant", run_id=ctx.run_id, limit=limit, offset=offset)

    everything = [
        item async for item in store.query(page(0, 1000)) if isinstance(item, ExecutionStartedEvent)
    ]
    pages: list[ExecutionStartedEvent] = []
    for offset in range(0, len(stamps) + page_size, page_size):
        pages.extend(
            [
                item
                async for item in store.query(page(offset, page_size))
                if isinstance(item, ExecutionStartedEvent)
            ]
        )

    assert pages == everything
    assert len({item.id for item in everything}) == len(stamps)
    assert [(item.timestamp, item.sequence, item.id) for item in everything] == sorted(
        (item.timestamp, item.sequence, item.id) for item in everything
    )
