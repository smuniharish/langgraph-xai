import asyncio
import time

import pytest

from langgraph_xai.core import ExecutionContext, ProvenanceLink
from langgraph_xai.storage import InMemoryProvenanceStore

pytestmark = pytest.mark.benchmark


@pytest.mark.asyncio
async def test_1000_concurrent_event_writes_complete_within_regression_budget() -> None:
    store = InMemoryProvenanceStore()
    context = ExecutionContext(application_id="bench", tenant_id="one", graph_id="write")
    links = [
        ProvenanceLink(
            context=context,
            source_id=f"source-{index}",
            target_id="decision",
            relation="INFLUENCED",
        )
        for index in range(1000)
    ]

    started = time.perf_counter()
    await asyncio.gather(*(store.write(link) for link in links))
    elapsed = time.perf_counter() - started

    assert elapsed < 5.0
