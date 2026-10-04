"""Live test that exports real spans to an OpenTelemetry Collector.

Set ``XAI_TEST_OTEL_ENDPOINT`` to an OTLP/HTTP endpoint, for example a local
``otel/opentelemetry-collector`` container listening on ``http://localhost:4318``.
The test builds a real ``TracerProvider`` with an OTLP exporter, sends events
through the adapter, and asserts the exporter delivered them.
"""

from __future__ import annotations

import os

import pytest

from langgraph_xai.core import ExecutionStartedEvent
from langgraph_xai.observability import OpenTelemetryObservability
from tests.helpers import context

pytestmark = pytest.mark.live


async def test_otel_adapter_exports_spans_to_a_collector() -> None:
    endpoint = os.getenv("XAI_TEST_OTEL_ENDPOINT")
    if not endpoint:
        pytest.skip("XAI_TEST_OTEL_ENDPOINT is not configured")
    exporter_module = pytest.importorskip("opentelemetry.exporter.otlp.proto.http.trace_exporter")
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    provider = TracerProvider(resource=Resource.create({"service.name": "langgraph-xai-live-test"}))
    provider.add_span_processor(
        BatchSpanProcessor(exporter_module.OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces"))
    )
    adapter = OpenTelemetryObservability(tracer_provider=provider, owns_provider=True)
    try:
        for sequence in range(3):
            await adapter.emit(ExecutionStartedEvent(context=context(), sequence=sequence))
        assert provider.force_flush(timeout_millis=10_000) is True
        await adapter.flush()
    finally:
        await adapter.close()
