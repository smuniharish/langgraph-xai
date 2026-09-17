"""Versioned canonical models for LangGraph explainability."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator

SCHEMA_VERSION = "1.0.0"

type EntityId = UUID | str
type Metadata = dict[str, JsonValue]


def utc_now() -> datetime:
    """Return the current timezone-aware UTC timestamp."""
    return datetime.now(UTC)


class CaptureMode(StrEnum):
    FULL = "full"
    DELTA = "delta"
    SELECTIVE = "selective"
    CUSTOM = "custom"
    NONE = "none"


class FailureMode(StrEnum):
    FAIL_OPEN = "fail_open"
    FAIL_CLOSED = "fail_closed"
    STRICT = "strict"


class ExecutionStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"
    PARTIAL = "partial"


class ToolStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


class DecisionType(StrEnum):
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
    STATE = "state"
    TOOL_RESULT = "tool_result"
    RETRIEVAL_DOCUMENT = "retrieval_document"
    MEMORY = "memory"
    RULE = "rule"
    POLICY = "policy"
    MODEL_OUTPUT = "model_output"
    CUSTOM = "custom"


class Audience(StrEnum):
    DEVELOPER = "developer"
    AUDITOR = "auditor"
    BUSINESS = "business"
    END_USER = "end_user"


class MemoryOperation(StrEnum):
    READ = "read"
    WRITE = "write"


class HumanInteractionType(StrEnum):
    INTERRUPT = "interrupt"
    APPROVAL = "approval"
    REJECTION = "rejection"
    EDIT = "edit"
    RESUME = "resume"


class PolicyAction(StrEnum):
    CAPTURE = "capture"
    RETAIN = "retain"
    PROCESS = "process"
    EXPOSE = "expose"


class CanonicalModel(BaseModel):
    """Base for stable public contracts."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    schema_version: Literal["1.0.0"] = SCHEMA_VERSION


class IdentifiedModel(CanonicalModel):
    id: UUID = Field(default_factory=uuid4)
    timestamp: datetime = Field(default_factory=utc_now)

    @field_validator("timestamp")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
        return value


class ExecutionContext(CanonicalModel):
    application_id: str
    tenant_id: str
    graph_id: str
    run_id: UUID = Field(default_factory=uuid4)
    thread_id: str | None = None
    trace_id: str | None = None
    span_id: str | None = None
    parent_id: str | None = None
    checkpoint_id: str | None = None
    metadata: Metadata = Field(default_factory=dict)


class ProvenanceLink(IdentifiedModel):
    source_id: EntityId
    target_id: EntityId
    relation: Annotated[str, Field(min_length=1)]
    context: ExecutionContext
    metadata: Metadata = Field(default_factory=dict)


class EvidenceReference(CanonicalModel):
    evidence_id: UUID
    relationship: str = "supported_by"


class SourceReference(CanonicalModel):
    source_id: EntityId
    source_type: str
    uri: str | None = None
    metadata: Metadata = Field(default_factory=dict)


class Evidence(IdentifiedModel):
    evidence_type: EvidenceType | str
    context: ExecutionContext
    summary: str | None = None
    content_reference: str | None = None
    source: SourceReference | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    quality: float | None = Field(default=None, ge=0, le=1)
    metadata: Metadata = Field(default_factory=dict)


class StateChange(CanonicalModel):
    path: str
    before: JsonValue = None
    after: JsonValue = None


class StateTransition(IdentifiedModel):
    context: ExecutionContext
    node_id: str
    changes: list[StateChange] = Field(default_factory=list)
    capture_mode: CaptureMode = CaptureMode.DELTA
    influences: list[EntityId] = Field(default_factory=list)
    metadata: Metadata = Field(default_factory=dict)


class NodeExecution(IdentifiedModel):
    context: ExecutionContext
    node_id: str
    node_name: str | None = None
    parent_node_id: str | None = None
    status: ExecutionStatus
    started_at: datetime
    ended_at: datetime | None = None
    attempt: int = Field(default=1, ge=1)
    input_reference: str | None = None
    output_reference: str | None = None
    error_id: UUID | None = None
    metadata: Metadata = Field(default_factory=dict)


class ToolExecution(IdentifiedModel):
    context: ExecutionContext
    tool_id: str
    tool_name: str
    tool_call_id: str | None = None
    status: ToolStatus
    input_reference: str | None = None
    output_reference: str | None = None
    retry_count: int = Field(default=0, ge=0)
    latency_ms: float | None = Field(default=None, ge=0)
    error_id: UUID | None = None
    downstream_consumers: list[EntityId] = Field(default_factory=list)
    related_decisions: list[UUID] = Field(default_factory=list)
    metadata: Metadata = Field(default_factory=dict)


class RetrievedDocument(CanonicalModel):
    document_id: str
    chunk_id: str | None = None
    rank: int | None = Field(default=None, ge=1)
    score: float | None = None
    selected: bool = True
    content_reference: str | None = None
    metadata: Metadata = Field(default_factory=dict)


class RetrievalExecution(IdentifiedModel):
    context: ExecutionContext
    retriever_id: str
    query_reference: str | None = None
    documents: list[RetrievedDocument] = Field(default_factory=list)
    reranker: str | None = None
    metadata: Metadata = Field(default_factory=dict)


class MemoryReference(IdentifiedModel):
    context: ExecutionContext
    memory_id: str
    operation: MemoryOperation
    namespace: str | None = None
    content_reference: str | None = None
    private: bool = True
    influenced: list[EntityId] = Field(default_factory=list)
    metadata: Metadata = Field(default_factory=dict)


class CheckpointReference(IdentifiedModel):
    context: ExecutionContext
    checkpoint_id: str
    parent_checkpoint_id: str | None = None
    restored: bool = False
    metadata: Metadata = Field(default_factory=dict)


class HumanInteraction(IdentifiedModel):
    context: ExecutionContext
    interaction_type: HumanInteractionType
    actor_reference: str | None = None
    request_reference: str | None = None
    response_reference: str | None = None
    continuation_run_id: UUID | None = None
    metadata: Metadata = Field(default_factory=dict)


class ExceptionEvent(IdentifiedModel):
    context: ExecutionContext
    exception_type: str
    message: str
    retryable: bool = False
    attempt: int = Field(default=1, ge=1)
    traceback_reference: str | None = None
    metadata: Metadata = Field(default_factory=dict)


class DecisionFactor(CanonicalModel):
    name: str
    value: JsonValue = None
    evidence_ids: list[UUID] = Field(default_factory=list)
    weight: float | None = None
    metadata: Metadata = Field(default_factory=dict)


class Decision(IdentifiedModel):
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
    factor_id: EntityId
    factor_type: str
    score: float
    label: str | None = None
    evidence_ids: list[UUID] = Field(default_factory=list)
    rationale: str | None = None
    metadata: Metadata = Field(default_factory=dict)


class AttributionResult(IdentifiedModel):
    context: ExecutionContext
    subject_id: EntityId
    method: str
    contributions: list[AttributionContribution] = Field(default_factory=list)
    normalized: bool = False
    confidence: float | None = Field(default=None, ge=0, le=1)
    metadata: Metadata = Field(default_factory=dict)


class PolicyDecision(IdentifiedModel):
    context: ExecutionContext
    policy_id: str
    action: PolicyAction
    allowed: bool
    audience: Audience | str | None = None
    reason: str | None = None
    allowed_fields: set[str] = Field(default_factory=set)
    denied_fields: set[str] = Field(default_factory=set)
    obligations: list[str] = Field(default_factory=list)
    metadata: Metadata = Field(default_factory=dict)


class ExplanationContext(CanonicalModel):
    execution: Execution
    decision: Decision | None = None
    evidence: list[Evidence] = Field(default_factory=list)
    provenance: list[ProvenanceLink] = Field(default_factory=list)
    attribution: AttributionResult | None = None
    policies: list[PolicyDecision] = Field(default_factory=list)
    audience: Audience | str = Audience.DEVELOPER


class Explanation(IdentifiedModel):
    context: ExecutionContext
    audience: Audience | str
    summary: Annotated[str, Field(min_length=1)]
    reasons: list[str] = Field(default_factory=list)
    supporting_evidence: list[EvidenceReference] = Field(default_factory=list)
    contributing_factors: list[AttributionContribution] = Field(default_factory=list)
    disclosure: list[str] = Field(default_factory=list)
    metadata: Metadata = Field(default_factory=dict)


class Execution(IdentifiedModel):
    context: ExecutionContext
    status: ExecutionStatus
    started_at: datetime
    ended_at: datetime | None = None
    parent_execution_id: UUID | None = None
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
    event_id: UUID = Field(default_factory=uuid4)
    context: ExecutionContext
    sequence: int = Field(ge=0)
    payload: Metadata = Field(default_factory=dict)


class ExecutionStartedEvent(XAIEvent):
    event_type: Literal["execution.started"] = "execution.started"


class ExecutionCompletedEvent(XAIEvent):
    event_type: Literal["execution.completed"] = "execution.completed"


class ExecutionFailedEvent(XAIEvent):
    event_type: Literal["execution.failed"] = "execution.failed"
    error: ExceptionEvent


class StateTransitionEvent(XAIEvent):
    event_type: Literal["state.transition"] = "state.transition"
    transition: StateTransition


class NodeExecutionEvent(XAIEvent):
    event_type: Literal["node.execution"] = "node.execution"
    node: NodeExecution


class ToolExecutionEvent(XAIEvent):
    event_type: Literal["tool.execution"] = "tool.execution"
    tool: ToolExecution


class RetrievalExecutionEvent(XAIEvent):
    event_type: Literal["retrieval.execution"] = "retrieval.execution"
    retrieval: RetrievalExecution


class CheckpointEvent(XAIEvent):
    event_type: Literal["checkpoint"] = "checkpoint"
    checkpoint: CheckpointReference


class InterruptEvent(XAIEvent):
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

# Compatibility aliases retained during the initial development cycle.
VERSION = SCHEMA_VERSION
Event = XAIEvent
EventUnion = CanonicalEvent
ExecutionRecord = Execution
Attribution = AttributionResult
Relation = ProvenanceLink
StateCaptured = StateTransitionEvent
ExecutionStarted = ExecutionStartedEvent
ExecutionCompleted = ExecutionCompletedEvent
ExecutionFailed = ExecutionFailedEvent
