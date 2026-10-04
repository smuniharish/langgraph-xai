# langgraph-xai API at a glance

Everything below is importable from `langgraph_xai` unless a module is named.
Names that start with an underscore are private. Full reference:
<https://langgraph-xai.readthedocs.io/en/latest/api/>.

## Contents

- [Runtime](#runtime)
- [Configuration](#configuration)
- [Instrumented graphs](#instrumented-graphs)
- [Runs](#runs)
- [Records](#records)
- [Enumerations](#enumerations)
- [Capabilities and providers](#capabilities-and-providers)
- [Errors](#errors)

## Runtime

```python
class XAIRuntime:
    def __init__(
        self,
        config: XAIConfig | None = None,
        registry: Registry | None = None,
        *,
        application_id: str = "application",
        tenant_id: str = "default",
        graph_id: str = "graph",
        plugins: tuple[XAIPlugin, ...] = (),
        custom_state_capture: Callable[[Mapping, Mapping], Mapping] | None = None,
    ) -> None: ...
```

Instrumentation and runs:

| Member | Purpose |
| --- | --- |
| `instrument(graph) -> InstrumentedGraph` | Wrap a compiled graph or any `Runnable`. Instrumenting twice with the same runtime returns the same wrapper. |
| `collect_runs()` | Context manager yielding a list that receives every `Run` started in the block, including in tasks it spawns. |
| `current_run` | The `Run` of the instrumented call executing the current node, tool, or middleware; `None` outside one. |
| `start_run(config=None, *, continuation_of=None) -> Run` | Start a run for work that does not go through an instrumented graph. |
| `finish_run(run, error=None, *, cancelled=False, interrupts=(), pending_nodes=())` | Finish a manually started run. |
| `run_sync(coroutine)` | Run a coroutine from synchronous code, such as a `record_*` call in a sync node. |
| `context_from_config(config) -> ExecutionContext` | The context a LangChain config produces. |

Recording. Every method is a coroutine, accepts `run=` (default: `current_run`),
and returns the record it created:

| Method | Records |
| --- | --- |
| `record_evidence(evidence_type, *, summary, content_reference, source, confidence, quality, metadata)` | `Evidence` the application relied on. `confidence` and `quality` are 0 to 1. |
| `record_decision(selected_action, *, decision_type, candidate_actions, evidence_ids, provenance_ids, factors, policy_references, confidence, uncertainty, metadata)` | A `Decision`. `factors` is a list of `DecisionFactor(name, value, weight=None, evidence_ids=[])`. |
| `record_provenance(source_id, target_id, relation, *, metadata)` | A `ProvenanceLink`: the target was derived from, supported by, or produced by the source. |
| `record_human_interaction(interaction_type, *, actor_reference, request_reference, response_reference, metadata)` | An approval, rejection, edit, interrupt, or resume. Works after the run finished. |
| `record_memory(memory_id, operation, *, namespace, content_reference, private=True, metadata)` | A long-term memory read or write, by reference. |
| `record_tool(tool_name, *, tool_id, status, tool_call_id, input_reference, output_reference, latency_ms, metadata)` | A tool call made outside the graph. Graph tools are captured automatically. |
| `record_retrieval(retriever_id, *, documents, query_reference, reranker, metadata)` | A retrieval made outside the graph. LangChain retrievers are captured automatically. |
| `record_node(node_id, *, status, started_at, ended_at, attempt, parent_node_id, metadata)` | A node execution, for manual runs. |
| `record_state_delta(node_id, before, after, *, metadata)` | A state change, filtered by the capture mode, for manual runs. |
| `record_checkpoint(checkpoint_id, *, parent_checkpoint_id, restored, metadata)` | A checkpoint link, for manual runs or with `capture_checkpoints=False`. |
| `record_artifact(artifact)` | Deliver an `AttributionResult`, `Explanation`, or `PolicyDecision` to plugins. |

Explaining:

| Method | Purpose |
| --- | --- |
| `explain_decision(decision, *, audience=Audience.DEVELOPER, run=None) -> Explanation` | Gather the decision's evidence, attribute, apply the exposure policy, and render. Raises `ValueError` if the decision is not from `run`. |
| `explain(context: ExplanationContext) -> Explanation` | The same for a context you build, for example from stored records. |
| `attribute(context) -> AttributionResult` | Attribution only. |

Providers and lifecycle:

| Member | Purpose |
| --- | --- |
| `register(capability, provider)` | Replace the provider of one capability, for example `xai.register(PolicyProvider, MyPolicy())`. |
| `registry` | The `Registry`; `registry.require(ProvenanceStore)` returns the active store. |
| `errors` | The last 100 instrumentation errors, newest last. |
| `flush()` | Flush the observability provider and plugins. |
| `close()` | Flush, then close the store, the observability provider, and plugins. Call it at shutdown. |

## Configuration

`XAIConfig` is immutable. Build a new config and runtime to change it.

| Field | Default | Meaning |
| --- | --- | --- |
| `capture_state` | `CaptureMode.DELTA` | How much of each node's state change is recorded. |
| `capture_fields` | `frozenset()` | State keys recorded in `SELECTIVE` mode. |
| `capture_checkpoints` | `True` | Read checkpointed threads' state to record checkpoints, static breakpoints, and `continuation_of`. |
| `failure_mode` | `FailureMode.FAIL_OPEN` | What an instrumentation failure does. |
| `llm_explanation_enabled` | `False` | Allow a registered `LLMExplanationEngine` to run. |
| `max_concurrency` | `32` | Instrumentation operations in flight at once. |
| `operation_timeout_seconds` | `10.0` | Budget for one operation, including the wait for a slot. |

Per-call identity comes from the LangChain config:

| Config entry | Becomes |
| --- | --- |
| `metadata["xai_application_id"]`, `["xai_tenant_id"]`, `["xai_graph_id"]` | The run's application, tenant, and graph IDs |
| `metadata["xai_run_id"]` | The run ID (a UUID string) |
| `metadata["trace_id"]` | `ExecutionContext.trace_id` |
| `configurable["thread_id"]`, `["checkpoint_id"]` | `thread_id`, `checkpoint_id` |
| Other metadata | `ExecutionContext.metadata`, redacted |

The graph receives the run ID in its config metadata under
`RUN_ID_METADATA_KEY` (`"langgraph_xai_run_id"`).

## Instrumented graphs

`InstrumentedGraph` returns exactly what the wrapped graph returns. One run is
recorded per top-level call, and per input for batches:

| Recorded | Not recorded |
| --- | --- |
| `invoke`, `ainvoke`, `stream`, `astream`, `batch`, `abatch`, `batch_as_completed`, `abatch_as_completed`, `astream_events` (v1, v2), `transform`, `atransform` | `stream_events` and `astream_events(version="v3")` (LangGraph's experimental v3 streaming), `astream_log` (deprecated by LangChain) |

Unrecorded calls reach the graph unchanged and count as failed operations:
kept in `xai.errors` under `FAIL_OPEN`, raised under `FAIL_CLOSED` and
`STRICT`. Calls made inside another instrumented call of the same runtime join
the outer run. Other attributes, such as `get_state` or `update_state`, pass
through; `with_config(...)` returns an instrumented wrapper.

## Runs

`Run` is the handle of one execution:

| Member | Contents |
| --- | --- |
| `run_id` | The run's UUID |
| `execution` | The live `Execution` |
| `evidence`, `decisions` | Evidence and decisions recorded in the run |
| `artifacts` | Every semantic record delivered to plugins |

## Records

Every record is a strict Pydantic model with `schema_version` `"2.0.0"`.
Top-level records have an `id`, a `timestamp`, and a `context`
(`ExecutionContext`: `application_id`, `tenant_id`, `graph_id`, `run_id`,
`thread_id`, `trace_id`, `checkpoint_id`, `metadata`).

| Record | Key fields |
| --- | --- |
| `Execution` | `status`, `started_at`, `ended_at`, `continuation_of`, `nodes`, `state_transitions`, `tools`, `retrievals`, `memory`, `checkpoints`, `human_interactions`, `exceptions` |
| `Evidence` | `evidence_type`, `summary`, `content_reference`, `source`, `confidence`, `quality` |
| `Decision` | `decision_type`, `selected_action`, `candidate_actions`, `factors`, `evidence_ids`, `provenance_ids`, `policy_references`, `confidence`, `uncertainty` |
| `Explanation` | `audience`, `summary`, `reasons`, `supporting_evidence`, `contributing_factors`, `disclosure` |
| `AttributionResult` | `subject_id`, `method`, `contributions`, `normalized`, `confidence` |
| `PolicyDecision` | `policy_id`, `action`, `allowed`, `audience`, `reason`, `allowed_fields`, `denied_fields` |
| `ProvenanceLink` | `source_id`, `target_id`, `relation` |

## Enumerations

| Enum | Values |
| --- | --- |
| `Audience` | `DEVELOPER`, `AUDITOR`, `BUSINESS`, `END_USER`; any string is accepted |
| `DecisionType` | `ROUTING`, `CLASSIFICATION`, `TOOL_SELECTION`, `APPROVAL`, `REJECTION`, `ESCALATION`, `HITL`, `FINAL_RESPONSE`, `CUSTOM`; any string is accepted |
| `EvidenceType` | `STATE`, `TOOL_RESULT`, `RETRIEVAL_DOCUMENT`, `MEMORY`, `RULE`, `POLICY`, `MODEL_OUTPUT`, `CUSTOM`; any string is accepted |
| `CaptureMode` | `FULL`, `DELTA`, `SELECTIVE`, `CUSTOM`, `NONE` |
| `FailureMode` | `FAIL_OPEN`, `FAIL_CLOSED`, `STRICT` |
| `ExecutionStatus` | `RUNNING`, `COMPLETED`, `FAILED`, `CANCELLED`, `INTERRUPTED` |
| `HumanInteractionType` | `INTERRUPT`, `APPROVAL`, `REJECTION`, `EDIT`, `RESUME` |
| `PolicyAction` | `CAPTURE`, `EXPOSE` |

## Capabilities and providers

Register a provider with `xai.register(Capability, provider)`:

| Capability | Default | Contract |
| --- | --- | --- |
| `ProvenanceStore` | `InMemoryProvenanceStore` | Abstract base class: implement `write`, `get`, `query`, `parents`, `children`; `lineage` and `close` are inherited. |
| `ObservabilityProvider` | `NoOpObservability` | `LangSmithObservability(client=None, *, project_name=None)`, `LangfuseObservability(client=None)`, `OpenTelemetryObservability(tracer=None, *, tracer_provider=None, owns_provider=False)` |
| `PolicyProvider` | `DefaultPolicyProvider` | `async evaluate(context: ExplanationContext, action: PolicyAction) -> PolicyDecision` |
| `CapturePolicy` | `DefaultCapturePolicy` | `async evaluate(event: CanonicalEvent) -> PolicyDecision`; `allowed=False` drops the event. |
| `AttributionEngine` | `HybridAttribution` | Also `RuleBasedAttribution`, `EvidenceAttribution` |
| `ExplanationEngine` | `StructuredExplanationEngine` | Also `LLMExplanationEngine(model, *, enabled=False, timeout=30.0)`, which also needs `XAIConfig(llm_explanation_enabled=True)` |

`XAIPlugin` instances, passed as `XAIRuntime(plugins=(...))`, receive every
evidence, decision, and memory record through `async record(artifact)`, plus
`flush()` and `close()`.

An exposure `PolicyDecision` withholds an explanation section (`reasons`,
`contributing_factors`, or `supporting_evidence`) when `allowed` is false, when
the section is in `denied_fields`, or when `allowed_fields` is non-empty and
does not name it. Each withheld section is announced in `disclosure`.

`StoreFilter(application_id, tenant_id, run_id=None, item_type=None, limit=100, offset=0)`
queries a store: `[item async for item in store.query(StoreFilter(...))]`.

## Errors

| Error | Raised when |
| --- | --- |
| `XAIInstrumentationError` | An operation failed under `FAIL_CLOSED` or `STRICT`, or an explanation could not be produced safely (any mode). |
| `RuntimeError("no active run: ...")` | A `record_*` call had no `run=` and no current run. |
| `langgraph_xai.observability.OptionalDependencyError` | An adapter's SDK is not installed; the message names the extra. |
