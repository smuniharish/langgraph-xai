from datetime import datetime
from uuid import uuid4

import pytest
from pydantic import TypeAdapter, ValidationError

from langgraph_xai.core import (
    CanonicalEvent,
    CaptureMode,
    ExceptionEvent,
    ExecutionContext,
    ExecutionFailedEvent,
    ProvenanceLink,
)


def context() -> ExecutionContext:
    return ExecutionContext(application_id="app", tenant_id="tenant", graph_id="graph")


def test_context_has_stable_run_identity() -> None:
    value = context()
    restored = ExecutionContext.model_validate_json(value.model_dump_json())

    assert restored.run_id == value.run_id
    assert restored.schema_version == "1.0.0"


def test_provenance_relation_is_extensible() -> None:
    link = ProvenanceLink(
        source_id="document",
        target_id="decision",
        relation="RETRIEVED_FROM:VECTOR_STORE",
        context=context(),
    )

    assert link.relation == "RETRIEVED_FROM:VECTOR_STORE"


def test_events_are_discriminated() -> None:
    ctx = context()
    error = ExceptionEvent(context=ctx, exception_type="ValueError", message="boom")
    raw = ExecutionFailedEvent(
        context=ctx,
        sequence=2,
        error=error,
    ).model_dump(mode="json")

    event = TypeAdapter(CanonicalEvent).validate_python(raw)

    assert isinstance(event, ExecutionFailedEvent)


def test_naive_timestamp_is_rejected() -> None:
    with pytest.raises(ValidationError):
        ProvenanceLink(
            source_id="a",
            target_id="b",
            relation="DERIVED_FROM",
            context=context(),
            timestamp=datetime.fromisoformat("2026-01-01T00:00:00"),
        )


def test_capture_modes_are_complete() -> None:
    assert {mode.value for mode in CaptureMode} == {
        "full",
        "delta",
        "selective",
        "custom",
        "none",
    }


def test_context_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        ExecutionContext.model_validate(
            {
                "application_id": "app",
                "tenant_id": "tenant",
                "graph_id": "graph",
                "unknown_id": uuid4(),
            }
        )
