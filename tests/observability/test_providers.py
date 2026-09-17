from __future__ import annotations

from contextlib import contextmanager

import pytest

from langgraph_xai.core.models import ExecutionContext, ExecutionStartedEvent
from langgraph_xai.observability import (
    AdapterClosedError,
    LangfuseObservability,
    LangSmithObservability,
    NoOpObservability,
    OpenTelemetryObservability,
)


def event() -> ExecutionStartedEvent:
    return ExecutionStartedEvent(
        context=ExecutionContext(
            application_id="app",
            tenant_id="tenant",
            graph_id="graph",
            trace_id="trace-1",
            span_id="span-1",
            parent_id="parent-1",
        ),
        sequence=1,
    )


@pytest.mark.asyncio
async def test_noop_has_protocol_lifecycle_and_deduplicates() -> None:
    provider = NoOpObservability()
    item = event()
    await provider.emit(item)
    await provider.emit(item)
    await provider.flush()
    await provider.close()
    await provider.close()
    with pytest.raises(AdapterClosedError):
        await provider.emit(event())


class FakeLangSmith:
    def __init__(self) -> None:
        self.runs: list[dict[str, object]] = []
        self.flushed = False
        self.closed = False

    def create_run(self, **kwargs: object) -> None:
        self.runs.append(kwargs)

    def flush(self) -> None:
        self.flushed = True

    def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_langsmith_injects_client_and_preserves_correlation() -> None:
    client = FakeLangSmith()
    provider = LangSmithObservability(client, project_name="project")
    item = event()
    await provider.emit(item)
    await provider.emit(item)
    await provider.flush()
    await provider.close()

    assert len(client.runs) == 1
    run = client.runs[0]
    assert run["id"] == item.event_id
    assert run["trace_id"] == "trace-1"
    assert run["parent_run_id"] == "parent-1"
    assert run["project_name"] == "project"
    assert not client.flushed
    assert not client.closed


class FakeLangfuse:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    async def create_event(self, **kwargs: object) -> None:
        self.events.append(kwargs)


@pytest.mark.asyncio
async def test_langfuse_v4_uses_injected_async_client() -> None:
    client = FakeLangfuse()
    item = event()
    await LangfuseObservability(client).emit(item)
    assert len(client.events) == 1
    assert client.events[0]["trace_id"] == "trace-1"
    assert client.events[0]["id"] == str(item.event_id)


class FakeSpan:
    def __init__(self) -> None:
        self.attributes: dict[str, object] = {}
        self.ended = False

    def set_attribute(self, key: str, value: object) -> None:
        self.attributes[key] = value

    def end(self) -> None:
        self.ended = True


class FakeTracer:
    def __init__(self) -> None:
        self.spans: list[FakeSpan] = []

    @contextmanager
    def start_as_current_span(self, name: str):
        del name
        span = FakeSpan()
        self.spans.append(span)
        yield span


@pytest.mark.asyncio
async def test_otel_uses_injected_tracer_without_global_provider() -> None:
    tracer = FakeTracer()
    item = event()
    await OpenTelemetryObservability(tracer).emit(item)
    span = tracer.spans[0]
    assert span.attributes["xai.event_id"] == str(item.event_id)
    assert span.attributes["xai.trace_id"] == "trace-1"
    assert span.attributes["xai.parent_id"] == "parent-1"
