"""Live integration test that exports real spans to an OpenTelemetry Collector.

Requires ``XAI_TEST_OTEL_ENDPOINT`` to point at an OTLP/HTTP endpoint, for example one
started with Podman running ``otel/opentelemetry-collector`` with an OTLP receiver and a
``debug`` exporter:

    $env:XAI_TEST_OTEL_ENDPOINT = "http://<host>:4318"

Verification is intentionally end-to-end: this test builds a real ``TracerProvider`` with a
``BatchSpanProcessor``/``OTLPSpanExporter`` exactly as a host application would, forces a
flush, and asserts the exporter reports success. Visual confirmation of the received spans is
done by inspecting the collector's own logs (``podman logs <collector>``).
"""

from __future__ import annotations

import os

import pytest

from langgraph_xai.core.models import ExecutionContext, ExecutionStartedEvent

pytestmark = pytest.mark.live


@pytest.mark.asyncio
async def test_otel_adapter_exports_real_spans_to_collector() -> None:
    endpoint = os.getenv("XAI_TEST_OTEL_ENDPOINT")
    if not endpoint:
        pytest.skip("XAI_TEST_OTEL_ENDPOINT is not configured")
    pytest.importorskip("opentelemetry.exporter.otlp.proto.http.trace_exporter")

    # Optional dependencies required only for this live test; not part of the
    # default dev environment, so pyrefly cannot resolve them statically.
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import (  # pyrefly: ignore[missing-import]
        OTLPSpanExporter,
    )
    from opentelemetry.sdk.resources import Resource  # pyrefly: ignore[missing-import]
    from opentelemetry.sdk.trace import TracerProvider  # pyrefly: ignore[missing-import]
    from opentelemetry.sdk.trace.export import BatchSpanProcessor  # pyrefly: ignore[missing-import]

    from langgraph_xai.observability import OpenTelemetryObservability

    resource = Resource.create({"service.name": "xgraph-live-test"})
    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces")
    processor = BatchSpanProcessor(exporter)
    provider.add_span_processor(processor)
    tracer = provider.get_tracer("xgraph.live-test")

    adapter = OpenTelemetryObservability(tracer, owns_provider=True)
    context = ExecutionContext(
        application_id="live-app",
        tenant_id="live-tenant",
        graph_id="banking-review",
        trace_id="live-trace-1",
        span_id="live-span-1",
    )
    try:
        for sequence in range(1, 4):
            await adapter.emit(ExecutionStartedEvent(context=context, sequence=sequence))
        flush_ok = provider.force_flush(timeout_millis=10_000)
        assert flush_ok is True
    finally:
        await adapter.close()
        provider.shutdown()
