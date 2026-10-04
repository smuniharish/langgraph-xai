"""Live test that sends events to a self-hosted Langfuse deployment.

Set ``XAI_TEST_LANGFUSE_HOST``, ``XAI_TEST_LANGFUSE_PUBLIC_KEY``, and
``XAI_TEST_LANGFUSE_SECRET_KEY`` (for example for a stack started from the
official ``langfuse/langfuse`` compose file). The test emits events, flushes,
and reads the observations back through Langfuse's public API to prove
ingestion end to end.
"""

from __future__ import annotations

import asyncio
import os
import uuid

import pytest

from langgraph_xai.core import ExecutionStartedEvent
from langgraph_xai.observability import LangfuseObservability
from tests.helpers import context

pytestmark = pytest.mark.live


async def test_langfuse_adapter_events_are_queryable_through_the_api() -> None:
    host = os.getenv("XAI_TEST_LANGFUSE_HOST")
    public_key = os.getenv("XAI_TEST_LANGFUSE_PUBLIC_KEY")
    secret_key = os.getenv("XAI_TEST_LANGFUSE_SECRET_KEY")
    if not (host and public_key and secret_key):
        pytest.skip("XAI_TEST_LANGFUSE_HOST/PUBLIC_KEY/SECRET_KEY are not configured")
    langfuse = pytest.importorskip("langfuse")
    httpx = pytest.importorskip("httpx")

    client = langfuse.Langfuse(public_key=public_key, secret_key=secret_key, host=host)
    adapter = LangfuseObservability(client)
    trace_id = uuid.uuid4().hex
    try:
        for sequence in range(3):
            await adapter.emit(
                ExecutionStartedEvent(context=context(trace_id=trace_id), sequence=sequence)
            )
        await adapter.flush()

        async with httpx.AsyncClient(
            base_url=host, auth=(public_key, secret_key), timeout=10.0
        ) as http:
            for _ in range(10):
                response = await http.get(
                    "/api/public/v2/observations", params={"traceId": trace_id}
                )
                if response.status_code == 200 and len(response.json()["data"]) == 3:
                    break
                await asyncio.sleep(1.5)
        assert response.status_code == 200, response.text
        observations = response.json()["data"]
        assert len(observations) == 3
        assert {item["traceId"] for item in observations} == {trace_id}
        assert {item["name"] for item in observations} == {"execution.started"}
    finally:
        client.shutdown()
