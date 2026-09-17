# Canonical models

Every model below is a Pydantic v2 `BaseModel`: JSON-serializable
(`.model_dump_json()`), validated on construction, and identified by a
`schema_version` field so exported payloads are versioned contracts. See
each concept page for a complete, real example of the JSON these models
produce.

## Context

`ExecutionContext` correlates every artifact belonging to one run
(`application_id`, `tenant_id`, `graph_id`, `run_id`, `thread_id`,
`trace_id`). `ExplanationContext` is the input to `runtime.explain(...)`:
the execution, decision, evidence, provenance, attribution, audience, and
already-applied policies to assemble an explanation from.

::: langgraph_xai.core.models.ExecutionContext

::: langgraph_xai.core.models.ExplanationContext

## Execution — [concept](../concepts/execution.md)

::: langgraph_xai.core.models.Execution

::: langgraph_xai.core.models.ExecutionStatus

::: langgraph_xai.core.models.StateTransition

::: langgraph_xai.core.models.StateChange

::: langgraph_xai.core.models.ToolExecution

::: langgraph_xai.core.models.ToolStatus

::: langgraph_xai.core.models.RetrievalExecution

::: langgraph_xai.core.models.RetrievedDocument

::: langgraph_xai.core.models.MemoryReference

::: langgraph_xai.core.models.MemoryOperation

::: langgraph_xai.core.models.HumanInteraction

::: langgraph_xai.core.models.HumanInteractionType

::: langgraph_xai.core.models.CheckpointReference

## Provenance — [concept](../concepts/provenance.md)

::: langgraph_xai.core.models.ProvenanceLink

## Evidence — [concept](../concepts/evidence.md)

::: langgraph_xai.core.models.Evidence

::: langgraph_xai.core.models.EvidenceType

::: langgraph_xai.core.models.EvidenceReference

::: langgraph_xai.core.models.SourceReference

## Decisions — [concept](../concepts/decisions.md)

::: langgraph_xai.core.models.Decision

::: langgraph_xai.core.models.DecisionFactor

::: langgraph_xai.core.models.DecisionType

## Attribution — [concept](../concepts/attribution.md)

::: langgraph_xai.core.models.AttributionResult

::: langgraph_xai.core.models.AttributionContribution

## Policy — [concept](../concepts/policies.md)

::: langgraph_xai.core.models.PolicyDecision

::: langgraph_xai.core.models.PolicyAction

## Explanation — [concept](../concepts/explanations.md)

::: langgraph_xai.core.models.Explanation

## Events

Canonical events are what an `ObservabilityProvider` receives via `emit(...)`
— see [Observability](observability.md).

::: langgraph_xai.core.models.CanonicalEvent

::: langgraph_xai.core.models.ExecutionStartedEvent

::: langgraph_xai.core.models.ExecutionCompletedEvent

::: langgraph_xai.core.models.ExecutionFailedEvent

::: langgraph_xai.core.models.ExceptionEvent

::: langgraph_xai.core.models.StateTransitionEvent

::: langgraph_xai.core.models.ToolExecutionEvent

::: langgraph_xai.core.models.RetrievalExecutionEvent

::: langgraph_xai.core.models.NodeExecution

::: langgraph_xai.core.models.NodeExecutionEvent

::: langgraph_xai.core.models.InterruptEvent

::: langgraph_xai.core.models.CheckpointEvent
