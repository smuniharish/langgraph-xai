import re
import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import create_autospec

import pytest
from hypothesis import given
from hypothesis import strategies as st

from langgraph_xai import ObservabilityProvider, XAIRuntime
from langgraph_xai.core import (
    ExceptionEvent,
    ExecutionCompletedEvent,
    ExecutionFailedEvent,
    ExecutionStartedEvent,
    HumanInteraction,
    HumanInteractionType,
    InterruptEvent,
)
from langgraph_xai.observability import (
    LangfuseObservability,
    LangSmithObservability,
    OpenTelemetryObservability,
    langfuse_trace_context,
)
from langgraph_xai.observability import langfuse as langfuse_module
from langgraph_xai.observability import langsmith as langsmith_module
from tests.helpers import context

# SDK clients are autospecced, so every call the adapters (and LangSmith's RunTree)
# make is checked against the installed SDK's real signatures.


def calls(method: Any) -> list[dict[str, Any]]:
    return [call.kwargs for call in method.call_args_list]


# --- Langfuse ---------------------------------------------------------------------------


@pytest.fixture
def langfuse_sdk() -> Any:
    return pytest.importorskip("langfuse")


@pytest.fixture
def langfuse_client(langfuse_sdk) -> Any:
    return create_autospec(langfuse_sdk.Langfuse, instance=True)


def test_langfuse_trace_context_joins_valid_traces_and_falls_back_to_the_run() -> None:
    trace = uuid.uuid4().hex
    invalid = context(trace_id="trace-8841")
    plain = context()

    assert langfuse_trace_context(context(trace_id=trace)) == {"trace_id": trace}
    assert langfuse_trace_context(invalid) == {"trace_id": invalid.run_id.hex}
    assert langfuse_trace_context(plain) == {"trace_id": plain.run_id.hex}


async def test_langfuse_adapter_sends_events_and_manages_only_owned_clients(
    monkeypatch, langfuse_sdk, langfuse_client
) -> None:
    adapter = LangfuseObservability(langfuse_client)
    item = ExecutionStartedEvent(context=context(trace_id="trace-8841"), sequence=0)

    await adapter.emit(item)
    await adapter.flush()
    await adapter.close()

    (sent,) = calls(langfuse_client.create_event)
    assert sent["name"] == "execution.started"
    assert sent["trace_context"] == {"trace_id": item.context.run_id.hex}
    assert sent["input"]["id"] == str(item.id)
    assert sent["metadata"]["xai.event_id"] == str(item.id)
    assert sent["metadata"]["xai.trace_id"] == "trace-8841"
    assert langfuse_client.flush.call_count == 1
    langfuse_client.shutdown.assert_not_called()

    owned_client = create_autospec(langfuse_sdk.Langfuse, instance=True)

    class FakeModule:
        @staticmethod
        def get_client() -> Any:
            return owned_client

    monkeypatch.setattr(langfuse_module, "optional_import", lambda *_: FakeModule)
    owned = LangfuseObservability()
    await owned.flush()
    await owned.close()
    assert (owned_client.flush.call_count, owned_client.shutdown.call_count) == (1, 1)


async def test_langfuse_adapter_with_the_real_sdk_exports_one_trace_per_run() -> None:
    langfuse = pytest.importorskip("langfuse")
    exporter_module = pytest.importorskip("opentelemetry.sdk.trace.export.in_memory_span_exporter")
    exporter = exporter_module.InMemorySpanExporter()
    client = langfuse.Langfuse(
        public_key=f"pk-lf-{uuid.uuid4().hex}",
        secret_key="sk-lf-test",
        host="http://127.0.0.1:9",
        span_exporter=exporter,
    )
    runtime = XAIRuntime()
    runtime.register(ObservabilityProvider, LangfuseObservability(client))
    run = await runtime.start_run({"metadata": {"trace_id": "not-hex"}})
    await runtime.finish_run(run)
    await runtime.flush()

    spans = exporter.get_finished_spans()
    assert runtime.errors == ()
    assert [span.name for span in spans] == ["execution.started", "execution.completed"]
    assert {format(span.context.trace_id, "032x") for span in spans} == {run.run_id.hex}
    client.shutdown()


# --- LangSmith --------------------------------------------------------------------------


@pytest.fixture
def langsmith_sdk() -> Any:
    return pytest.importorskip("langsmith")


@pytest.fixture
def langsmith_client(langsmith_sdk) -> Any:
    return create_autospec(langsmith_sdk.Client, instance=True)


def interrupt(ctx, kind: HumanInteractionType, sequence: int) -> InterruptEvent:
    return InterruptEvent(
        context=ctx,
        sequence=sequence,
        interaction=HumanInteraction(context=ctx, interaction_type=kind),
    )


async def test_langsmith_groups_a_run_into_one_trace_and_ends_it(langsmith_client) -> None:
    adapter = LangSmithObservability(langsmith_client, project_name="xai")
    ctx = context(trace_id="external-trace")
    started = ExecutionStartedEvent(context=ctx, sequence=0)
    completed = ExecutionCompletedEvent(context=ctx, sequence=1)

    await adapter.emit(started)
    await adapter.emit(completed)
    await adapter.emit(ExecutionCompletedEvent(context=ctx, sequence=2))

    root, first, second, third = calls(langsmith_client.create_run)
    assert root["id"] == ctx.run_id
    assert root["trace_id"] == ctx.run_id
    assert root["session_name"] == "xai"
    assert root["name"] == "langgraph-xai: graph"
    assert "xai.event_id" not in root["extra"]["metadata"]
    assert [first["name"], second["name"]] == ["execution.started", "execution.completed"]
    assert first["id"] == started.id
    assert first["parent_run_id"] == ctx.run_id
    assert first["trace_id"] == ctx.run_id
    assert first["dotted_order"].startswith(root["dotted_order"] + ".")
    assert first["start_time"] == first["end_time"] == started.timestamp
    assert first["extra"]["metadata"]["xai.trace_id"] == "external-trace"
    assert third["name"] == "execution.completed"
    (update,) = calls(langsmith_client.update_run)
    assert update["run_id"] == ctx.run_id
    assert update["outputs"] == {"status": "completed"}


@pytest.mark.parametrize(
    ("make_event", "outputs", "error"),
    [
        (
            lambda ctx: ExecutionFailedEvent(
                context=ctx,
                sequence=0,
                error=ExceptionEvent(context=ctx, exception_type="ValueError", message="bad"),
            ),
            {"status": "failed"},
            "ValueError: bad",
        ),
        (
            lambda ctx: interrupt(ctx, HumanInteractionType.INTERRUPT, 0),
            {"status": "interrupted"},
            None,
        ),
    ],
)
async def test_langsmith_ends_failed_and_interrupted_runs(
    make_event, outputs, error, langsmith_client
) -> None:
    adapter = LangSmithObservability(langsmith_client)

    await adapter.emit(make_event(context()))

    (update,) = calls(langsmith_client.update_run)
    assert update["outputs"] == outputs
    assert update["error"] == error


async def test_langsmith_resume_events_do_not_end_the_trace(langsmith_client) -> None:
    adapter = LangSmithObservability(langsmith_client)

    await adapter.emit(interrupt(context(), HumanInteractionType.RESUME, 0))

    langsmith_client.update_run.assert_not_called()
    assert langsmith_client.create_run.call_count == 2


async def test_langsmith_bounds_open_traces_and_manages_only_owned_clients(
    monkeypatch, langsmith_sdk, langsmith_client
) -> None:
    adapter = LangSmithObservability(langsmith_client, max_open_traces=1)
    for _ in range(3):
        await adapter.emit(ExecutionStartedEvent(context=context(), sequence=0))
    await adapter.flush()
    await adapter.close()

    assert len(adapter._roots) == 1
    assert langsmith_client.flush.call_count == 1
    langsmith_client.close.assert_not_called()
    with pytest.raises(ValueError, match="max_open_traces"):
        LangSmithObservability(langsmith_client, max_open_traces=0)

    owned_client = create_autospec(langsmith_sdk.Client, instance=True)

    class FakeModule:
        RunTree = langsmith_sdk.RunTree

        @staticmethod
        def Client() -> Any:  # noqa: N802 - mirrors langsmith.Client
            return owned_client

    monkeypatch.setattr(langsmith_module, "optional_import", lambda *_: FakeModule)
    owned = LangSmithObservability()
    await owned.flush()
    await owned.close()
    assert (owned_client.flush.call_count, owned_client.close.call_count) == (1, 1)


# --- OpenTelemetry ------------------------------------------------------------------------


@pytest.fixture
def otel():
    sdk = pytest.importorskip("opentelemetry.sdk.trace")
    exporter_module = pytest.importorskip("opentelemetry.sdk.trace.export.in_memory_span_exporter")
    export = pytest.importorskip("opentelemetry.sdk.trace.export")
    exporter = exporter_module.InMemorySpanExporter()
    provider = sdk.TracerProvider()
    provider.add_span_processor(export.SimpleSpanProcessor(exporter))
    return provider, exporter


async def test_otel_spans_carry_correlation_payload_and_event_time(otel) -> None:
    provider, exporter = otel
    adapter = OpenTelemetryObservability(tracer_provider=provider)
    item = ExecutionStartedEvent(
        context=context(trace_id="trace"),
        sequence=0,
        timestamp=datetime(2026, 1, 2, 3, 4, 5, 678901, tzinfo=UTC),
    )

    await adapter.emit(item)

    (span,) = exporter.get_finished_spans()
    assert span.name == "execution.started"
    assert span.start_time == span.end_time == 1767323045678901000
    assert span.attributes["xai.event_id"] == str(item.id)
    assert span.attributes["xai.trace_id"] == "trace"
    assert '"event_type":"execution.started"' in span.attributes["xai.payload"]


async def test_otel_flushes_any_provider_and_shuts_down_only_owned_ones(otel) -> None:
    provider, _ = otel
    calls: list[str] = []
    provider.force_flush = lambda *a, **k: calls.append("flush") or True
    provider.shutdown = lambda *a, **k: calls.append("shutdown")

    borrowed = OpenTelemetryObservability(tracer_provider=provider)
    await borrowed.flush()
    await borrowed.close()
    owned = OpenTelemetryObservability(tracer_provider=provider, owns_provider=True)
    await owned.close()

    assert calls == ["flush", "shutdown"]


async def test_otel_defaults_and_validation(otel) -> None:
    provider, _ = otel
    global_tracer = OpenTelemetryObservability()
    await global_tracer.emit(ExecutionStartedEvent(context=context(), sequence=0))
    await global_tracer.flush()
    await global_tracer.close()

    explicit = OpenTelemetryObservability(provider.get_tracer("custom"))
    assert explicit.tracer_provider is None
    with pytest.raises(ValueError, match="owns_provider requires a tracer_provider"):
        OpenTelemetryObservability(owns_provider=True)


@given(trace_id=st.none() | st.text(max_size=40) | st.uuids().map(lambda value: value.hex))
def test_langfuse_trace_ids_are_always_valid_and_reuse_valid_ones(trace_id: str | None) -> None:
    ctx = context(trace_id=trace_id)

    trace = langfuse_trace_context(ctx)["trace_id"]

    assert re.fullmatch(r"[0-9a-f]{32}", trace)
    joins = trace_id is not None and re.fullmatch(r"[0-9a-f]{32}", trace_id) is not None
    assert trace == (trace_id if joins else ctx.run_id.hex)
