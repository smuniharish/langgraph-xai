"""Versioned canonical models for LangGraph explainability.

Every model is a Pydantic v2 model with ``extra="forbid"``, assignment
validation, timezone-aware timestamps, and finite floats, and carries a
``schema_version`` so serialized payloads are self-describing contracts.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID, uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, JsonValue, field_serializer

SCHEMA_VERSION = "2.0.0"

type EntityId = UUID | str
type Metadata = dict[str, JsonValue]


def utc_now() -> datetime:
    """Return the current timezone-aware UTC timestamp."""
    return datetime.now(UTC)


class CaptureMode(StrEnum):
    """How much of a node's state change is recorded."""

    FULL = "full"
    DELTA = "delta"
    SELECTIVE = "selective"
    CUSTOM = "custom"
    NONE = "none"


class FailureMode(StrEnum):
    """What happens when an instrumentation operation fails."""

    FAIL_OPEN = "fail_open"
    FAIL_CLOSED = "fail_closed"
    STRICT = "strict"


class ExecutionStatus(StrEnum):
    """Lifecycle status of an execution or a node execution."""

    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


class ToolStatus(StrEnum):
    """Outcome of a single tool invocation."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


class DecisionType(StrEnum):
    """Common decision categories; any non-empty string is also accepted."""

    ROUTING = "routing"
    CLASSIFICATION = "classification"
    TOOL_SELECTION = "tool_selection"
    APPROVAL = "approval"
    REJECTION = "rejection"
    ESCALATION = "escalation"
    HITL = "hitl"
    FINAL_RESPONSE = "final_response"
    CUSTOM = "custom"


class EvidenceType(StrEnum):
    """Common evidence categories; any non-empty string is also accepted."""

    STATE = "state"
    TOOL_RESULT = "tool_result"
    RETRIEVAL_DOCUMENT = "retrieval_document"
    MEMORY = "memory"
    RULE = "rule"
    POLICY = "policy"
    MODEL_OUTPUT = "model_output"
    CUSTOM = "custom"


class Audience(StrEnum):
    """Built-in explanation audiences; any string is also accepted."""

    DEVELOPER = "developer"
    AUDITOR = "auditor"
    BUSINESS = "business"
    END_USER = "end_user"


class MemoryOperation(StrEnum):
    """Direction of a memory access."""

    READ = "read"
    WRITE = "write"


class HumanInteractionType(StrEnum):
    """Kind of human-in-the-loop interaction."""

    INTERRUPT = "interrupt"
    APPROVAL = "approval"
    REJECTION = "rejection"
    EDIT = "edit"
    RESUME = "resume"


class PolicyAction(StrEnum):
    """The data-handling action a policy decision governs."""

    CAPTURE = "capture"
    EXPOSE = "expose"


class CanonicalModel(BaseModel):
    """Base class for every versioned public contract."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True, allow_inf_nan=False)

    schema_version: Literal["2.0.0"] = SCHEMA_VERSION


class IdentifiedModel(CanonicalModel):
    """A canonical model with a unique ID and a timezone-aware timestamp."""

    id: UUID = Field(default_factory=uuid4)
    timestamp: AwareDatetime = Field(default_factory=utc_now)


class ExecutionContext(CanonicalModel):
    """Correlation and isolation identifiers shared by every artifact of one run."""

    application_id: str
    tenant_id: str
    graph_id: str
    run_id: UUID = Field(default_factory=uuid4)
    thread_id: str | None = None
    trace_id: str | None = None
    checkpoint_id: str | None = None
    metadata: Metadata = Field(default_factory=dict)


class ProvenanceLink(IdentifiedModel):
    """A lineage edge from an upstream ``source`` to a downstream ``target``.

    ``relation`` reads from the target back to the source, e.g. the target was
    ``DERIVED_FROM`` the source.
    """

    source_id: EntityId
    target_id: EntityId
    relation: Annotated[str, Field(min_length=1)]
    context: ExecutionContext
    metadata: Metadata = Field(default_factory=dict)


class EvidenceReference(CanonicalModel):
    """A reference from an explanation to a piece of supporting evidence."""

    evidence_id: UUID
    relationship: str = "supported_by"


class SourceReference(CanonicalModel):
    """Where a piece of evidence originated, by reference rather than by copy."""

    source_id: EntityId
    source_type: str
    uri: str | None = None
    metadata: Metadata = Field(default_factory=dict)


class Evidence(IdentifiedModel):
    """Material supporting a decision: a summary plus a reference, never a payload dump."""

    evidence_type: EvidenceType | str
    context: ExecutionContext
    summary: str | None = None
    content_reference: str | None = None
    source: SourceReference | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    quality: float | None = Field(default=None, ge=0, le=1)
    metadata: Metadata = Field(default_factory=dict)


class StateChange(CanonicalModel):
    """One changed state key: its value before and after a node ran."""

    path: str
    before: JsonValue = None
    after: JsonValue = None


class StateTransition(IdentifiedModel):
    """The state changes produced by one node execution."""

    context: ExecutionContext
    node_id: str
    changes: list[StateChange] = Field(default_factory=list)
    capture_mode: CaptureMode = CaptureMode.DELTA
    metadata: Metadata = Field(default_factory=dict)


class NodeExecution(IdentifiedModel):
    """Timing and outcome of one graph node execution."""

    context: ExecutionContext
    node_id: str
    parent_node_id: str | None = None
    status: ExecutionStatus
    started_at: AwareDatetime
    ended_at: AwareDatetime | None = None
    attempt: int = Field(default=1, ge=1)
    metadata: Metadata = Field(default_factory=dict)


class ToolExecution(IdentifiedModel):
    """Outcome and latency of one tool invocation."""

    context: ExecutionContext
    tool_id: str
    tool_name: str
    tool_call_id: str | None = None
    status: ToolStatus
    input_reference: str | None = None
    output_reference: str | None = None
    latency_ms: float | None = Field(default=None, ge=0)
    metadata: Metadata = Field(default_factory=dict)


class RetrievedDocument(CanonicalModel):
    """A retrieved document or chunk, identified by reference and rank."""

    document_id: str
    chunk_id: str | None = None
    rank: int | None = Field(default=None, ge=1)
    score: float | None = None
    selected: bool = True
    content_reference: str | None = None
    metadata: Metadata = Field(default_factory=dict)


class RetrievalExecution(IdentifiedModel):
    """One retriever call and the documents it returned."""

    context: ExecutionContext
    retriever_id: str
    query_reference: str | None = None
    documents: list[RetrievedDocument] = Field(default_factory=list)
    reranker: str | None = None
    metadata: Metadata = Field(default_factory=dict)


class MemoryReference(IdentifiedModel):
    """A read from or write to long-term memory, by reference."""

    context: ExecutionContext
    memory_id: str
    operation: MemoryOperation
    namespace: str | None = None
    content_reference: str | None = None
    private: bool = True
    metadata: Metadata = Field(default_factory=dict)


class CheckpointReference(IdentifiedModel):
    """A LangGraph checkpoint associated with a run."""

    context: ExecutionContext
    checkpoint_id: str
    parent_checkpoint_id: str | None = None
    restored: bool = False
    metadata: Metadata = Field(default_factory=dict)


class HumanInteraction(IdentifiedModel):
    """A human-in-the-loop interrupt, approval, rejection, edit, or resume."""

    context: ExecutionContext
    interaction_type: HumanInteractionType
    actor_reference: str | None = None
    request_reference: str | None = None
    response_reference: str | None = None
    metadata: Metadata = Field(default_factory=dict)


class ExceptionEvent(IdentifiedModel):
    """An exception observed during a run, by type and message."""

    context: ExecutionContext
    exception_type: str
    message: str
    metadata: Metadata = Field(default_factory=dict)


class DecisionFactor(CanonicalModel):
    """A named, optionally weighted input to a decision."""

    name: str
    value: JsonValue = None
    evidence_ids: list[UUID] = Field(default_factory=list)
    weight: float | None = None
    metadata: Metadata = Field(default_factory=dict)


class Decision(IdentifiedModel):
    """The action an application selected, its alternatives, factors, and evidence."""

    context: ExecutionContext
    decision_type: DecisionType | str
    selected_action: str
    candidate_actions: list[str] = Field(default_factory=list)
    evidence_ids: list[UUID] = Field(default_factory=list)
    provenance_ids: list[UUID] = Field(default_factory=list)
    factors: list[DecisionFactor] = Field(default_factory=list)
    policy_references: list[str] = Field(default_factory=list)
    confidence: float | None = Field(default=None, ge=0, le=1)
    uncertainty: float | None = Field(default=None, ge=0, le=1)
    metadata: Metadata = Field(default_factory=dict)


class AttributionContribution(CanonicalModel):
    """One factor's or evidence item's signed contribution to a decision."""

    factor_id: EntityId
    factor_type: str
    score: float
    label: str | None = None
    evidence_ids: list[UUID] = Field(default_factory=list)
    rationale: str | None = None
    metadata: Metadata = Field(default_factory=dict)


class AttributionResult(IdentifiedModel):
    """The output of an attribution method: contributions plus the method that produced them."""

    context: ExecutionContext
    subject_id: EntityId
    method: str
    contributions: list[AttributionContribution] = Field(default_factory=list)
    normalized: bool = False
    confidence: float | None = Field(default=None, ge=0, le=1)
    metadata: Metadata = Field(default_factory=dict)


class PolicyDecision(IdentifiedModel):
    """The outcome of a policy evaluation for one action and audience.

    For ``PolicyAction.EXPOSE``, the explanation engines withhold a section
    (``reasons``, ``contributing_factors``, or ``supporting_evidence``) when
    ``allowed`` is false, when the section is in ``denied_fields``, or when
    ``allowed_fields`` is non-empty and does not name it. ``reason`` is shown
    to the audience as a disclosure note.
    """

    context: ExecutionContext
    policy_id: str
    action: PolicyAction
    allowed: bool
    audience: Audience | str | None = None
    reason: str | None = None
    allowed_fields: set[str] = Field(default_factory=set)
    denied_fields: set[str] = Field(default_factory=set)
    metadata: Metadata = Field(default_factory=dict)

    @field_serializer("allowed_fields", "denied_fields")
    def _serialize_field_set(self, value: set[str]) -> list[str]:
        return sorted(value)


class ExplanationContext(CanonicalModel):
    """The request to explain: an execution, an optional decision, and an audience."""

    execution: Execution
    decision: Decision | None = None
    evidence: list[Evidence] = Field(default_factory=list)
    attribution: AttributionResult | None = None
    policies: list[PolicyDecision] = Field(default_factory=list)
    audience: Audience | str = Audience.DEVELOPER


class Explanation(IdentifiedModel):
    """A policy-filtered, audience-specific account of a decision."""

    context: ExecutionContext
    audience: Audience | str
    summary: Annotated[str, Field(min_length=1)]
    reasons: list[str] = Field(default_factory=list)
    supporting_evidence: list[EvidenceReference] = Field(default_factory=list)
    contributing_factors: list[AttributionContribution] = Field(default_factory=list)
    disclosure: list[str] = Field(default_factory=list)
    metadata: Metadata = Field(default_factory=dict)


class Execution(IdentifiedModel):
    """The record of one graph run: status, timing, and everything observed during it.

    ``continuation_of`` is the ``run_id`` of the earlier run whose checkpoint
    this run continued from: the interrupted run it resumed, the failed run it
    retried, or the run whose history it replayed.
    """

    context: ExecutionContext
    status: ExecutionStatus
    started_at: AwareDatetime
    ended_at: AwareDatetime | None = None
    continuation_of: UUID | None = None
    nodes: list[NodeExecution] = Field(default_factory=list)
    state_transitions: list[StateTransition] = Field(default_factory=list)
    tools: list[ToolExecution] = Field(default_factory=list)
    retrievals: list[RetrievalExecution] = Field(default_factory=list)
    memory: list[MemoryReference] = Field(default_factory=list)
    checkpoints: list[CheckpointReference] = Field(default_factory=list)
    human_interactions: list[HumanInteraction] = Field(default_factory=list)
    exceptions: list[ExceptionEvent] = Field(default_factory=list)
    metadata: Metadata = Field(default_factory=dict)


class XAIEvent(IdentifiedModel):
    """Base class for canonical events; ``sequence`` orders events within a run."""

    context: ExecutionContext
    sequence: int = Field(ge=0)


class ExecutionStartedEvent(XAIEvent):
    """Emitted when a run starts."""

    event_type: Literal["execution.started"] = "execution.started"


class ExecutionCompletedEvent(XAIEvent):
    """Emitted when a run completes successfully."""

    event_type: Literal["execution.completed"] = "execution.completed"


class ExecutionFailedEvent(XAIEvent):
    """Emitted when a run fails or is cancelled."""

    event_type: Literal["execution.failed"] = "execution.failed"
    error: ExceptionEvent


class StateTransitionEvent(XAIEvent):
    """Emitted when a node's state change is recorded."""

    event_type: Literal["state.transition"] = "state.transition"
    transition: StateTransition


class NodeExecutionEvent(XAIEvent):
    """Emitted when a node finishes, fails, or is interrupted."""

    event_type: Literal["node.execution"] = "node.execution"
    node: NodeExecution


class ToolExecutionEvent(XAIEvent):
    """Emitted when a tool invocation finishes."""

    event_type: Literal["tool.execution"] = "tool.execution"
    tool: ToolExecution


class RetrievalExecutionEvent(XAIEvent):
    """Emitted when a retriever call finishes."""

    event_type: Literal["retrieval.execution"] = "retrieval.execution"
    retrieval: RetrievalExecution


class CheckpointEvent(XAIEvent):
    """Emitted when a checkpoint is linked to a run."""

    event_type: Literal["checkpoint"] = "checkpoint"
    checkpoint: CheckpointReference


class InterruptEvent(XAIEvent):
    """Emitted when a human interaction (interrupt, resume, approval, ...) is recorded."""

    event_type: Literal["interrupt"] = "interrupt"
    interaction: HumanInteraction


type CanonicalEvent = Annotated[
    ExecutionStartedEvent
    | ExecutionCompletedEvent
    | ExecutionFailedEvent
    | StateTransitionEvent
    | NodeExecutionEvent
    | ToolExecutionEvent
    | RetrievalExecutionEvent
    | CheckpointEvent
    | InterruptEvent,
    Field(discriminator="event_type"),
]
