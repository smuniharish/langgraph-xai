# Canonical models

Every record is a Pydantic v2 model with a `schema_version`. Unknown fields are
rejected, numbers must be finite, and timestamps must be timezone-aware. See
[Canonical model](../architecture/canonical-model.md) for the rules and
[Concepts](../concepts/index.md) for what each record means. All classes on
this page are importable from `langgraph_xai.core`; the most common ones are
also importable from `langgraph_xai`.

## Context and execution

::: langgraph_xai.core.models.ExecutionContext

::: langgraph_xai.core.models.Execution

::: langgraph_xai.core.models.NodeExecution

::: langgraph_xai.core.models.StateTransition

::: langgraph_xai.core.models.StateChange

::: langgraph_xai.core.models.ToolExecution

::: langgraph_xai.core.models.RetrievalExecution

::: langgraph_xai.core.models.RetrievedDocument

::: langgraph_xai.core.models.MemoryReference

::: langgraph_xai.core.models.CheckpointReference

::: langgraph_xai.core.models.HumanInteraction

::: langgraph_xai.core.models.ExceptionEvent

## Decision basis

::: langgraph_xai.core.models.Evidence

::: langgraph_xai.core.models.SourceReference

::: langgraph_xai.core.models.Decision

::: langgraph_xai.core.models.DecisionFactor

::: langgraph_xai.core.models.ProvenanceLink

## Explanation

::: langgraph_xai.core.models.AttributionResult

::: langgraph_xai.core.models.AttributionContribution

::: langgraph_xai.core.models.PolicyDecision

::: langgraph_xai.core.models.ExplanationContext

::: langgraph_xai.core.models.Explanation

::: langgraph_xai.core.models.EvidenceReference

## Events

`CanonicalEvent` is the union of the event types below, discriminated by
`event_type`.

::: langgraph_xai.core.models.XAIEvent

::: langgraph_xai.core.models.ExecutionStartedEvent

::: langgraph_xai.core.models.ExecutionCompletedEvent

::: langgraph_xai.core.models.ExecutionFailedEvent

::: langgraph_xai.core.models.StateTransitionEvent

::: langgraph_xai.core.models.NodeExecutionEvent

::: langgraph_xai.core.models.ToolExecutionEvent

::: langgraph_xai.core.models.RetrievalExecutionEvent

::: langgraph_xai.core.models.CheckpointEvent

::: langgraph_xai.core.models.InterruptEvent

## Enumerations

::: langgraph_xai.core.models.CaptureMode

::: langgraph_xai.core.models.FailureMode

::: langgraph_xai.core.models.ExecutionStatus

::: langgraph_xai.core.models.ToolStatus

::: langgraph_xai.core.models.DecisionType

::: langgraph_xai.core.models.EvidenceType

::: langgraph_xai.core.models.Audience

::: langgraph_xai.core.models.MemoryOperation

::: langgraph_xai.core.models.HumanInteractionType

::: langgraph_xai.core.models.PolicyAction

## Base classes

::: langgraph_xai.core.models.CanonicalModel

::: langgraph_xai.core.models.IdentifiedModel
