import asyncio
from uuid import uuid4

import pytest
from hypothesis import given
from hypothesis import strategies as st

from langgraph_xai.core import ExecutionStartedEvent
from langgraph_xai.observability import (
    AdapterClosedError,
    NoOpObservability,
    ObservabilityAdapter,
    ObservabilityAdapterError,
    OptionalDependencyError,
    correlation_fields,
    event_payload,
)
from langgraph_xai.observability.base import optional_import
from tests.helpers import context


def event(**overrides) -> ExecutionStartedEvent:
    return ExecutionStartedEvent(context=context(**overrides), sequence=0)


class Collecting(ObservabilityAdapter):
    def __init__(self, *, fail_times: int = 0, error: Exception | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self.sent: list[object] = []
        self.fail_times = fail_times
        self.error = error or ConnectionError("down")

    async def _emit(self, event) -> None:
        if self.fail_times:
            self.fail_times -= 1
            raise self.error
        self.sent.append(event.id)


async def test_duplicates_within_the_window_are_dropped() -> None:
    adapter = Collecting(deduplication_window=2)
    first, second, third = event(), event(), event()

    for item in (first, first, second, third, first):
        await adapter.emit(item)

    assert adapter.sent == [first.id, second.id, third.id, first.id]
    assert len(adapter._seen) == 2


async def test_window_zero_disables_deduplication() -> None:
    adapter = Collecting(deduplication_window=0)
    item = event()

    await adapter.emit(item)
    await adapter.emit(item)

    assert adapter.sent == [item.id, item.id]
    with pytest.raises(ValueError, match="deduplication_window"):
        Collecting(deduplication_window=-1)


async def test_failed_emits_are_wrapped_and_can_be_retried() -> None:
    adapter = Collecting(fail_times=1)
    item = event()

    with pytest.raises(
        ObservabilityAdapterError, match=r"failed to emit execution\.started"
    ) as raised:
        await adapter.emit(item)
    await adapter.emit(item)

    assert isinstance(raised.value.__cause__, ConnectionError)
    assert adapter.sent == [item.id]


async def test_adapter_errors_and_cancellation_propagate_unwrapped() -> None:
    adapter = Collecting(fail_times=2, error=ObservabilityAdapterError("specific"))
    with pytest.raises(ObservabilityAdapterError, match="specific"):
        await adapter.emit(event())

    class Cancelling(ObservabilityAdapter):
        async def _emit(self, event) -> None:
            raise asyncio.CancelledError

    cancelling = Cancelling()
    item = event()
    with pytest.raises(asyncio.CancelledError):
        await cancelling.emit(item)
    assert item.id not in cancelling._seen


async def test_lifecycle_errors_and_closed_state() -> None:
    class Broken(ObservabilityAdapter):
        async def _emit(self, event) -> None: ...

        async def _flush(self) -> None:
            raise OSError("flush")

        async def _close(self) -> None:
            raise OSError("close")

    broken = Broken()
    with pytest.raises(ObservabilityAdapterError, match="failed to flush"):
        await broken.flush()
    with pytest.raises(ObservabilityAdapterError, match="failed to close"):
        await broken.close()
    await broken.close()
    with pytest.raises(AdapterClosedError):
        await broken.emit(event())
    with pytest.raises(AdapterClosedError):
        await broken.flush()

    class Specific(ObservabilityAdapter):
        async def _emit(self, event) -> None: ...

        async def _flush(self) -> None:
            raise ObservabilityAdapterError("flush specific")

        async def _close(self) -> None:
            raise ObservabilityAdapterError("close specific")

    specific = Specific()
    with pytest.raises(ObservabilityAdapterError, match="flush specific"):
        await specific.flush()
    with pytest.raises(ObservabilityAdapterError, match="close specific"):
        await specific.close()


async def test_noop_provider_has_the_full_lifecycle() -> None:
    provider = NoOpObservability()

    await provider.emit(event())
    await provider.flush()
    await provider.close()
    await provider.close()

    with pytest.raises(AdapterClosedError):
        await provider.emit(event())


def test_correlation_fields_include_only_present_identifiers() -> None:
    minimal = event()
    full = event(thread_id="thread", trace_id="trace", checkpoint_id="cp")
    base = {
        "xai.event_type": "execution.started",
        "xai.application_id": "app",
        "xai.tenant_id": "tenant",
        "xai.graph_id": "graph",
    }

    assert correlation_fields(minimal) == {
        **base,
        "xai.event_id": str(minimal.id),
        "xai.run_id": str(minimal.context.run_id),
    }
    assert correlation_fields(full) == {
        **base,
        "xai.event_id": str(full.id),
        "xai.run_id": str(full.context.run_id),
        "xai.thread_id": "thread",
        "xai.trace_id": "trace",
        "xai.checkpoint_id": "cp",
    }
    assert event_payload(minimal)["event_type"] == "execution.started"


def test_optional_import_names_the_missing_extra() -> None:
    assert optional_import("json", "json").dumps({}) == "{}"
    with pytest.raises(OptionalDependencyError, match=r"pip install 'langgraph-xai\[otel\]'"):
        optional_import(f"not_a_module_{uuid4().hex}", "otel")


optional_identifiers = st.none() | st.text(min_size=1, max_size=12)


@given(thread=optional_identifiers, trace=optional_identifiers, checkpoint=optional_identifiers)
def test_correlation_fields_are_strings_naming_only_present_identifiers(
    thread: str | None, trace: str | None, checkpoint: str | None
) -> None:
    item = event(thread_id=thread, trace_id=trace, checkpoint_id=checkpoint)

    fields = correlation_fields(item)

    optional = {"thread_id": thread, "trace_id": trace, "checkpoint_id": checkpoint}
    assert set(fields) == {
        "xai.event_id",
        "xai.event_type",
        "xai.application_id",
        "xai.tenant_id",
        "xai.graph_id",
        "xai.run_id",
    } | {f"xai.{name}" for name, value in optional.items() if value is not None}
    assert all(isinstance(value, str) for value in fields.values())
    assert (fields["xai.event_id"], fields["xai.run_id"]) == (
        str(item.id),
        str(item.context.run_id),
    )
