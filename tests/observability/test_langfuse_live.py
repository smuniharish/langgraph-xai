"""Live integration test that sends real events to a self-hosted Langfuse instance.

Requires ``XAI_TEST_LANGFUSE_HOST``, ``XAI_TEST_LANGFUSE_PUBLIC_KEY``, and
``XAI_TEST_LANGFUSE_SECRET_KEY`` to point at a reachable Langfuse deployment, for example one
started with Podman/Docker Compose from the official ``langfuse/langfuse`` repository. This
test creates a real client, emits canonical events through :class:`LangfuseObservability`,
flushes them, and then reads the observations back through Langfuse's ``v2/observations``
public API (the endpoint Langfuse v4 "events_only" deployments serve) to prove ingestion
succeeded end to end. The same data is what the Langfuse UI's trace view renders.
"""

from __future__ import annotations

import asyncio
import os
import uuid

import httpx
import pytest

from langgraph_xai.core.models import ExecutionContext, ExecutionStartedEvent

pytestmark = pytest.mark.live


@pytest.mark.asyncio
async def test_langfuse_adapter_emits_real_trace_visible_via_api() -> None:
    host = os.getenv("XAI_TEST_LANGFUSE_HOST")
    public_key = os.getenv("XAI_TEST_LANGFUSE_PUBLIC_KEY")
    secret_key = os.getenv("XAI_TEST_LANGFUSE_SECRET_KEY")
    if not (host and public_key and secret_key):
        pytest.skip("XAI_TEST_LANGFUSE_HOST/PUBLIC_KEY/SECRET_KEY are not configured")
    pytest.importorskip("langfuse")

    # Optional dependency required only for this live test; not part of the
    # default dev environment, so pyrefly cannot resolve it statically.
    from langfuse import Langfuse  # pyrefly: ignore[missing-import]

    from langgraph_xai.observability import LangfuseObservability

    client = Langfuse(public_key=public_key, secret_key=secret_key, host=host)
    adapter = LangfuseObservability(client)
    # A fresh trace ID per run keeps this test repeatable against a persistent server.
    trace_id = uuid.uuid4().hex
    context = ExecutionContext(
        application_id="live-app",
        tenant_id="live-tenant",
        graph_id="banking-review",
        trace_id=trace_id,
    )
    try:
        for sequence in range(1, 4):
            await adapter.emit(ExecutionStartedEvent(context=context, sequence=sequence))
        client.flush()

        # Give the async ingestion worker a moment to persist to ClickHouse, then confirm
        # the trace is retrievable through Langfuse's own public API (same data source used
        # to render the UI trace view).
        auth = (public_key, secret_key)
        async with httpx.AsyncClient(base_url=host, auth=auth, timeout=10.0) as http_client:
            for _ in range(10):
                response = await http_client.get(
                    "/api/public/v2/observations", params={"traceId": trace_id}
                )
                if response.status_code == 200 and response.json()["data"]:
                    break
                await asyncio.sleep(1.5)
            assert response.status_code == 200, response.text
            observations = response.json()["data"]
            assert len(observations) == 3
            assert all(item["traceId"] == trace_id for item in observations)
            assert all(item["name"] == "execution.started" for item in observations)
    finally:
        client.shutdown()
