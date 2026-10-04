import json
from datetime import UTC, datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, cast

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import TypeAdapter, ValidationError

from langgraph_xai.core import (
    SCHEMA_VERSION,
    AttributionContribution,
    CanonicalEvent,
    CaptureMode,
    CheckpointEvent,
    CheckpointReference,
    DecisionFactor,
    Evidence,
    EvidenceType,
    ExceptionEvent,
    Execution,
    ExecutionCompletedEvent,
    ExecutionContext,
    ExecutionFailedEvent,
    ExecutionStartedEvent,
    ExecutionStatus,
    Explanation,
    HumanInteraction,
    HumanInteractionType,
    InterruptEvent,
    NodeExecution,
    NodeExecutionEvent,
    PolicyAction,
    PolicyDecision,
    ProvenanceLink,
    RetrievalExecution,
    RetrievalExecutionEvent,
    RetrievedDocument,
    StateChange,
    StateTransition,
    StateTransitionEvent,
    ToolExecution,
    ToolExecutionEvent,
    ToolStatus,
    XAIEvent,
    utc_now,
)
from tests.helpers import context

if TYPE_CHECKING:
    from collections.abc import Callable

EVENTS = TypeAdapter(CanonicalEvent)


def test_utc_now_is_timezone_aware() -> None:
    assert utc_now().tzinfo is UTC


def test_context_round_trips_with_stable_identity() -> None:
    value = context(thread_id="t", trace_id="trace", metadata={"k": [1, "v"]})
    restored = ExecutionContext.model_validate_json(value.model_dump_json())

    assert restored == value
    assert restored.schema_version == SCHEMA_VERSION


@pytest.mark.parametrize(
    "build",
    [
        lambda naive: ProvenanceLink(
            source_id="a", target_id="b", relation="r", context=context(), timestamp=naive
        ),
        lambda naive: Execution(
            context=context(), status=ExecutionStatus.RUNNING, started_at=naive
        ),
        lambda naive: Execution(
            context=context(),
            status=ExecutionStatus.RUNNING,
            started_at=datetime.now(UTC),
            ended_at=naive,
        ),
        lambda naive: NodeExecution(
            context=context(), node_id="n", status=ExecutionStatus.COMPLETED, started_at=naive
        ),
    ],
)
def test_every_timestamp_must_be_timezone_aware(build) -> None:
    naive = datetime(2026, 1, 1)  # noqa: DTZ001 - deliberately naive
    with pytest.raises(ValidationError):
        build(naive)


def test_non_utc_offsets_are_accepted() -> None:
    offset = datetime(2026, 1, 1, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    link = ProvenanceLink(
        source_id="a", target_id="b", relation="r", context=context(), timestamp=offset
    )

    assert link.timestamp.utcoffset() == timedelta(hours=5, minutes=30)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_floats_are_rejected(value: float) -> None:
    with pytest.raises(ValidationError):
        AttributionContribution(factor_id="f", factor_type="t", score=value)
    with pytest.raises(ValidationError):
        DecisionFactor(name="f", weight=value)
    with pytest.raises(ValidationError):
        RetrievedDocument(document_id="d", score=value)
    with pytest.raises(ValidationError):
        Evidence(evidence_type="rule", context=context(), confidence=value)


def test_unknown_fields_and_invalid_assignments_are_rejected() -> None:
    with pytest.raises(ValidationError):
        ExecutionContext.model_validate(
            {"application_id": "a", "tenant_id": "t", "graph_id": "g", "unknown": 1}
        )
    evidence = Evidence(evidence_type=EvidenceType.RULE, context=context())
    with pytest.raises(ValidationError):
        evidence.confidence = 2


def test_constrained_fields_are_validated() -> None:
    with pytest.raises(ValidationError):
        ProvenanceLink(source_id="a", target_id="b", relation="", context=context())
    with pytest.raises(ValidationError):
        Explanation(context=context(), audience="developer", summary="")
    with pytest.raises(ValidationError):
        RetrievedDocument.model_validate({"document_id": "d", "rank": 0})


def test_open_vocabularies_accept_custom_strings() -> None:
    link = ProvenanceLink(
        source_id="doc", target_id="decision", relation="RETRIEVED_FROM:VECTOR", context=context()
    )
    evidence = Evidence(evidence_type="sensor_reading", context=context())

    assert link.relation == "RETRIEVED_FROM:VECTOR"
    assert evidence.evidence_type == "sensor_reading"


def test_policy_field_sets_serialize_sorted_and_round_trip() -> None:
    decision = PolicyDecision(
        context=context(),
        policy_id="p",
        action=PolicyAction.EXPOSE,
        allowed=True,
        allowed_fields={"zeta", "alpha"},
        denied_fields={"raw_content", "private_memory", "content_reference"},
    )
    payload = json.loads(decision.model_dump_json())

    assert payload["allowed_fields"] == ["alpha", "zeta"]
    assert payload["denied_fields"] == ["content_reference", "private_memory", "raw_content"]
    assert PolicyDecision.model_validate(payload) == decision


def test_capture_modes_are_complete() -> None:
    assert {mode.value for mode in CaptureMode} == {"full", "delta", "selective", "custom", "none"}


def _events() -> list[object]:
    ctx = context()
    error = ExceptionEvent(context=ctx, exception_type="ValueError", message="boom")
    return [
        ExecutionStartedEvent(context=ctx, sequence=0),
        ExecutionCompletedEvent(context=ctx, sequence=1),
        ExecutionFailedEvent(context=ctx, sequence=2, error=error),
        StateTransitionEvent(
            context=ctx,
            sequence=3,
            transition=StateTransition(
                context=ctx, node_id="n", changes=[StateChange(path="x", before=1, after=2)]
            ),
        ),
        NodeExecutionEvent(
            context=ctx,
            sequence=4,
            node=NodeExecution(
                context=ctx,
                node_id="n",
                status=ExecutionStatus.COMPLETED,
                started_at=datetime.now(UTC),
            ),
        ),
        ToolExecutionEvent(
            context=ctx,
            sequence=5,
            tool=ToolExecution(context=ctx, tool_id="t", tool_name="t", status=ToolStatus.FAILED),
        ),
        RetrievalExecutionEvent(
            context=ctx,
            sequence=6,
            retrieval=RetrievalExecution(
                context=ctx, retriever_id="r", documents=[RetrievedDocument(document_id="d")]
            ),
        ),
        CheckpointEvent(
            context=ctx,
            sequence=7,
            checkpoint=CheckpointReference(context=ctx, checkpoint_id="c"),
        ),
        InterruptEvent(
            context=ctx,
            sequence=8,
            interaction=HumanInteraction(
                context=ctx, interaction_type=HumanInteractionType.INTERRUPT
            ),
        ),
    ]


@pytest.mark.parametrize("event", _events(), ids=lambda event: type(event).__name__)
def test_every_canonical_event_round_trips_through_the_discriminated_union(event) -> None:
    restored = EVENTS.validate_json(event.model_dump_json())

    assert type(restored) is type(event)
    assert restored == event


json_values = st.recursive(
    st.none()
    | st.booleans()
    | st.integers(min_value=-(2**53), max_value=2**53)
    | st.floats(allow_nan=False, allow_infinity=False)
    | st.text(max_size=20),
    lambda children: (
        st.lists(children, max_size=4) | st.dictionaries(st.text(max_size=8), children, max_size=4)
    ),
    max_leaves=12,
)
identifiers = st.text(min_size=1, max_size=12)


@given(
    application_id=identifiers,
    tenant_id=identifiers,
    metadata=st.dictionaries(st.text(max_size=8), json_values, max_size=4),
    changes=st.lists(
        st.builds(StateChange, path=identifiers, before=json_values, after=json_values),
        max_size=4,
    ),
    sequence=st.integers(min_value=0, max_value=10_000),
)
def test_state_transition_events_round_trip_for_arbitrary_json(
    application_id: str, tenant_id: str, metadata: dict, changes: list, sequence: int
) -> None:
    ctx = ExecutionContext(
        application_id=application_id, tenant_id=tenant_id, graph_id="g", metadata=metadata
    )
    event = StateTransitionEvent(
        context=ctx,
        sequence=sequence,
        transition=StateTransition(context=ctx, node_id="node", changes=changes),
    )

    assert EVENTS.validate_json(event.model_dump_json()) == event
    assert EVENTS.validate_python(event.model_dump()) == event


@given(
    source=st.one_of(identifiers, st.uuids()),
    target=st.one_of(identifiers, st.uuids()),
    relation=identifiers,
)
def test_provenance_links_preserve_entity_id_types(source, target, relation: str) -> None:
    link = ProvenanceLink(source_id=source, target_id=target, relation=relation, context=context())
    restored = ProvenanceLink.model_validate(link.model_dump())

    assert restored == link
    assert type(restored.source_id) is type(source)


optional_ids = st.none() | identifiers
# Hypothesis takes naive bounds and attaches the time zones itself.
moments = st.datetimes(
    min_value=datetime(2000, 1, 1),  # noqa: DTZ001
    max_value=datetime(2100, 1, 1),  # noqa: DTZ001
    timezones=st.just(UTC),
)
json_metadata = st.dictionaries(st.text(max_size=8), json_values, max_size=3)
finite = st.floats(allow_nan=False, allow_infinity=False)
contexts = st.builds(
    ExecutionContext,
    application_id=identifiers,
    tenant_id=identifiers,
    graph_id=identifiers,
    run_id=st.uuids(),
    thread_id=optional_ids,
    trace_id=optional_ids,
    checkpoint_id=optional_ids,
    metadata=json_metadata,
)


@st.composite
def canonical_events(draw: st.DrawFn) -> CanonicalEvent:
    ctx = draw(contexts)
    common = {"context": ctx, "metadata": draw(json_metadata), "timestamp": draw(moments)}
    records: dict[str, Callable[[], dict[str, Any]]] = {
        "failed": lambda: {
            "error": ExceptionEvent(
                **common, exception_type=draw(identifiers), message=draw(st.text(max_size=30))
            )
        },
        "transition": lambda: {
            "transition": StateTransition(
                **common,
                node_id=draw(identifiers),
                capture_mode=draw(st.sampled_from(CaptureMode)),
                changes=draw(
                    st.lists(
                        st.builds(
                            StateChange, path=identifiers, before=json_values, after=json_values
                        ),
                        max_size=3,
                    )
                ),
            )
        },
        "node": lambda: {
            "node": NodeExecution(
                **common,
                node_id=draw(identifiers),
                parent_node_id=draw(optional_ids),
                status=draw(st.sampled_from(ExecutionStatus)),
                started_at=draw(moments),
                ended_at=draw(st.none() | moments),
                attempt=draw(st.integers(min_value=1, max_value=9)),
            )
        },
        "tool": lambda: {
            "tool": ToolExecution(
                **common,
                tool_id=draw(identifiers),
                tool_name=draw(identifiers),
                tool_call_id=draw(optional_ids),
                status=draw(st.sampled_from(ToolStatus)),
                input_reference=draw(optional_ids),
                output_reference=draw(optional_ids),
                latency_ms=draw(st.none() | st.floats(min_value=0, max_value=1e9)),
            )
        },
        "retrieval": lambda: {
            "retrieval": RetrievalExecution(
                **common,
                retriever_id=draw(identifiers),
                query_reference=draw(optional_ids),
                reranker=draw(optional_ids),
                documents=draw(
                    st.lists(
                        st.builds(
                            RetrievedDocument,
                            document_id=identifiers,
                            chunk_id=optional_ids,
                            rank=st.none() | st.integers(min_value=1, max_value=100),
                            score=st.none() | finite,
                            selected=st.booleans(),
                            content_reference=optional_ids,
                            metadata=json_metadata,
                        ),
                        max_size=3,
                    )
                ),
            )
        },
        "checkpoint": lambda: {
            "checkpoint": CheckpointReference(
                **common,
                checkpoint_id=draw(identifiers),
                parent_checkpoint_id=draw(optional_ids),
                restored=draw(st.booleans()),
            )
        },
        "interrupt": lambda: {
            "interaction": HumanInteraction(
                **common,
                interaction_type=draw(st.sampled_from(HumanInteractionType)),
                actor_reference=draw(optional_ids),
                request_reference=draw(optional_ids),
                response_reference=draw(optional_ids),
            )
        },
    }
    event_types: dict[str, type[XAIEvent]] = {
        "started": ExecutionStartedEvent,
        "completed": ExecutionCompletedEvent,
        "failed": ExecutionFailedEvent,
        "transition": StateTransitionEvent,
        "node": NodeExecutionEvent,
        "tool": ToolExecutionEvent,
        "retrieval": RetrievalExecutionEvent,
        "checkpoint": CheckpointEvent,
        "interrupt": InterruptEvent,
    }
    kind = draw(st.sampled_from(sorted(event_types)))
    payload = records[kind]() if kind in records else {}
    event = event_types[kind](
        context=ctx,
        sequence=draw(st.integers(min_value=0, max_value=10_000)),
        timestamp=draw(moments),
        **payload,
    )
    return cast("CanonicalEvent", event)


@given(canonical_events())
def test_every_canonical_event_round_trips_through_json(event: CanonicalEvent) -> None:
    assert EVENTS.validate_json(event.model_dump_json()) == event
    assert EVENTS.validate_python(json.loads(event.model_dump_json())) == event


@given(events=st.lists(canonical_events(), max_size=6), status=st.sampled_from(ExecutionStatus))
def test_executions_round_trip_with_every_record_kind(events: list, status) -> None:
    ctx = ExecutionContext(application_id="app", tenant_id="tenant", graph_id="graph")
    fields = {
        NodeExecutionEvent: ("nodes", "node"),
        StateTransitionEvent: ("state_transitions", "transition"),
        ToolExecutionEvent: ("tools", "tool"),
        RetrievalExecutionEvent: ("retrievals", "retrieval"),
        CheckpointEvent: ("checkpoints", "checkpoint"),
        InterruptEvent: ("human_interactions", "interaction"),
        ExecutionFailedEvent: ("exceptions", "error"),
    }
    records: dict[str, Any] = {name: [] for name, _ in fields.values()}
    for event in events:
        if type(event) in fields:
            name, attribute = fields[type(event)]
            records[name].append(getattr(event, attribute))
    execution = Execution(context=ctx, status=status, started_at=utc_now(), **records)

    assert Execution.model_validate_json(execution.model_dump_json()) == execution
