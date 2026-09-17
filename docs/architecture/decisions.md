# Architecture decisions

The architecture contract is version **1.0.0**. This page records every
accepted decision as a full Architecture Decision Record (ADR): the context
that forced the decision, the decision itself, and the consequences —
including the ones we didn't like but accepted anyway. Treat this page as the
"why" companion to the [architecture overview](overview.md).

Each ADR is **Accepted** and part of the stable v1.0.0 contract unless marked
otherwise. A breaking change to any of them requires a new major architecture
version and migration guidance — see [Runtime](runtime.md) for how the
contract is enforced in code.

---

## ADR-001 — Explainability is separate from observability and graph execution

**Context.** LangGraph already owns graph execution (nodes, edges, state,
routing). LangSmith, Langfuse, and OpenTelemetry already own observability
(traces, spans, metrics). It would be tempting to bolt "explanations" onto
either layer as an afterthought.

**Decision.** `langgraph-xai` is a third, independent layer. It does not
execute graphs and it does not replace tracing. It consumes execution
signals (via instrumentation) and produces its own canonical artifacts:
`Execution`, `ProvenanceLink`, `Evidence`, `Decision`, `AttributionResult`,
`Explanation`, `PolicyDecision`.

**Consequences.** Applications keep LangGraph and their existing
observability stack unchanged. xgraph can be added to, or removed from, a
running system without touching graph topology. The cost is one more
dependency to wire in — mitigated by [`XAIRuntime.instrument()`](runtime.md)
requiring a single call site per graph (verified end-to-end in
[`examples/minimal_langgraph.py`](https://github.com/) and, for a real
production-shaped agent, [`examples/mcp_playwright_tool_agent.py`](../examples/mcp-tools.md)).

## ADR-002 — LangSmith, Langfuse, and OpenTelemetry are optional adapters

**Context.** Every serious LangGraph deployment already uses at least one
observability provider. Re-implementing tracing would duplicate mature,
widely adopted tools and violate the reuse-before-reimplementation principle.

**Decision.** Each provider is implemented as a `ObservabilityProvider`
adapter (see [Observability](observability.md)) registered into the runtime.
None is imported unless its extra is installed (`pip install
"langgraph-xai[langfuse]"`, `[otel]`, …).

**Consequences.** Core `langgraph-xai` has zero required observability
dependency. Adding a new provider (e.g. a future vendor) never touches
`XAIRuntime` — it is a new class implementing `ObservabilityProvider` plus one
line of registration. This was exercised for real with a live Langfuse
container and a live OTel collector during development; both ran the same
runtime code path as the default `NoOpObservability`.

## ADR-003 — OpenTelemetry is a context and telemetry boundary, not the XAI model

**Context.** OpenTelemetry spans are excellent for "what ran and how long
did it take", but a span attribute bag is not a substitute for the structured
`Evidence` → `Decision` → `Explanation` semantic chain xgraph needs.

**Decision.** OTel is used for context propagation (trace/span IDs) and
generic telemetry emission, never as the storage shape for canonical
artifacts. Canonical artifacts always flow through the `ProvenanceStore`
protocol, with OTel span attributes as a secondary, best-effort mirror.

**Consequences.** xgraph's canonical model is stable even if an application
swaps OTel exporters, samplers, or collectors. The cost: OTel back ends show
correlation IDs and coarse events, not full explanations — by design.

## ADR-004 — Provenance is a first-class semantic artifact

**Context.** "Where did this value come from?" is a distinct question from
"what executed?" and from "why was this decided?". Burying lineage inside log
lines makes it unqueryable.

**Decision.** `ProvenanceLink` is a canonical model with an explicit,
extensible `relation` (`DERIVED_FROM`, `PRODUCED_BY`, `CONSUMED_BY`,
`SUPPORTED_BY`, `INFLUENCED`, `TRIGGERED`, `ROUTED_TO`, `VALIDATED_BY`,
`RETRIEVED_FROM`, …) between two `EntityId`s. See [Provenance](provenance.md)
for the full relation catalogue and query API (`parents`, `children`,
`lineage`).

**Consequences.** Lineage graphs can be queried and traversed without
scraping unstructured text. New relation kinds can be introduced by
applications without a runtime code change (the field is a `str`-backed enum
with an `CUSTOM`/passthrough kind).

## ADR-005 — Evidence is distinct from provenance

**Context.** "Where did it come from" (provenance) and "what supports the
result" (evidence) are frequently conflated in ad-hoc logging, producing
lineage graphs that are unusable for either purpose.

**Decision.** `Evidence` is its own canonical model with a `confidence`,
`evidence_type` (`TOOL_RESULT`, `RETRIEVAL_DOCUMENT`, `MEMORY`, `RULE`,
`POLICY`, `MODEL_OUTPUT`, `CUSTOM`, …), and `content_reference` — separate
from `ProvenanceLink`. A `Decision` references `Evidence` by ID via
`evidence_ids`, and `Explanation.supporting_evidence` is populated from
exactly those references.

**Consequences.** An explanation can say precisely which evidence backed a
decision without conflating that with the (potentially much larger) lineage
graph of everything that was ever derived from anything. Verified with real
captured evidence in
[`examples/full_explanation_output.py`](../examples/full-explanation.md).

## ADR-006 — Decisions are explicit and are not inferred from every node

**Context.** Not every node execution is a "decision" in the explainability
sense — most are plumbing. Auto-generating a `Decision` for every state
transition would flood the model with noise and imply causality that was
never actually reasoned about.

**Decision.** `Decision` records are only created when the application (or an
instrumentation hook explicitly wired for that purpose) calls
`runtime.record_decision(...)`. Automatic capture (chain/tool/state/retrieval)
never synthesizes a `Decision`.

**Consequences.** Every `Decision` in the store is meaningful and
attributable to a real branch point. The cost is that decision capture is opt
-in per node — acceptable because decisions are, by definition, the small
subset of an execution that actually matters for explanation.

## ADR-007 — Attribution is replaceable through a protocol

**Context.** Attribution methods (rule-based scoring, gradient/embedding
similarity, LLM-graded, hybrid, future research methods) evolve fast and have
wildly different cost/latency/accuracy trade-offs.

**Decision.** `AttributionEngine` is a `Protocol`. The shipped
`HybridAttribution` combines evidence confidence and rule scoring; it is the
default, not the only option, and is swapped exactly like `ExplanationEngine`
or `PolicyProvider` via `runtime.register(AttributionEngine, ...)`.

**Consequences.** A new attribution algorithm is a new class, not a new
`if isinstance(...)` branch in the runtime. `AttributionResult.normalized`
and `.confidence` make cross-method comparison honest rather than implicit.

## ADR-008 — Explanation is separate from attribution

**Context.** Attribution answers "how much did each factor contribute?".
Explanation answers "what should be communicated to this audience?". These
are different concerns with different failure modes — attribution can be
numerically wrong; explanation can be pragmatically unclear or over/under
-disclosing.

**Decision.** `ExplanationEngine.explain(context)` consumes an
`AttributionResult` (computed automatically by `runtime.explain` if not
already present) but is a distinct capability with its own protocol, its own
default (`StructuredExplanationEngine`), and its own opt-in LLM variant
(`LLMExplanationEngine`).

**Consequences.** Attribution can be swapped without touching explanation
rendering, and vice versa. Verified directly: the real
[disclosure-policy permutation matrix](../examples/disclosure-matrix.md) runs
both `StructuredExplanationEngine` and `LLMExplanationEngine` against the same
`AttributionResult` for 16 real permutations with zero runtime changes.

## ADR-009 — Policy applies across capture, retention, processing, and exposure

**Context.** A single "redact PII" filter at the API boundary is
insufficient: sensitive data can leak earlier, at capture time, or later, in
export/retention. Explainability artifacts are a new attack surface for data
leakage if policy is only checked once.

**Decision.** Two distinct policy protocols exist: `CapturePolicy` (evaluated
before an artifact is written to any store) and `PolicyProvider` (evaluated
before an `Explanation` is exposed, via `PolicyAction.EXPOSE`). Both return a
`PolicyDecision` with `allowed_fields`/`denied_fields`, not just a boolean.

**Consequences.** A field can be captured (for audit) but never exposed to
an end user, or withheld from capture entirely for the most sensitive
integrations. Verified for real with two independent policy providers
(permissive vs. audience-scoped) across four audiences in the
[disclosure-policy matrix](../examples/disclosure-matrix.md) — the
audience-scoped policy provably withheld `contributing_factors` and
`supporting_evidence` from `business`/`end_user` while keeping them for
`developer`/`auditor`, with the same runtime and same captured evidence.

## ADR-010 — Existing LangChain security middleware is integrated, not duplicated

**Context.** PII redaction, secret handling, and guardrails are large,
security-sensitive problem spaces already addressed by LangChain/LangGraph
middleware and dedicated guardrails libraries.

**Decision.** xgraph performs only minimal, best-effort credential-key
minimization at its own capture boundary (`policy.defaults.sanitize_value`,
which strips fields like `api_key`, `password`, `authorization`, …) and
explicitly documents that it is **not** a PII-redaction platform or guardrails
framework. Applications compose xgraph with their existing
LangChain/LangGraph security middleware.

**Consequences.** xgraph never claims a compliance guarantee it cannot keep.
Teams already running guardrails/redaction middleware do not get a second,
possibly conflicting, redaction implementation.

## ADR-011 — The runtime orchestrates provider-neutral capability interfaces

**Context.** This is the core architectural invariant requested for the
whole project: adding a new storage backend, observability provider,
attribution algorithm, explanation engine, or policy provider must never
require modifying `XAIRuntime`.

**Decision.** Every extensible concern is a `typing.Protocol` in
`langgraph_xai.core.protocols` (`ProvenanceStore`, `ObservabilityProvider`,
`AttributionEngine`, `ExplanationEngine`, `PolicyProvider`, `CapturePolicy`).
Internally, `XAIRuntime` resolves each capability through its registry by
protocol type — never through an `isinstance` chain across concrete provider
classes.

**Consequences.** This was exercised for real, not just claimed: a live
Playwright MCP tool server was instrumented
([`examples/mcp_playwright_tool_agent.py`](../examples/mcp-tools.md)) and a
`deepagents`-built agent was instrumented
([`examples/deepagents_realtime.py`](../examples/deepagents.md)) with **zero**
MCP-specific or deepagents-specific code anywhere in `langgraph_xai`.

## ADR-012 — Storage is replaceable without changing runtime code

**Context.** Development, testing, and production have very different
storage needs (in-memory, Postgres, a future vector/graph store).

**Decision.** `ProvenanceStore` is a `Protocol` with `write`, `query`, and
lineage-lookup methods. `InMemoryProvenanceStore` ships as the default; a
Postgres-backed store is provided as an optional extra
(`langgraph-xai[postgres]`).

**Consequences.** Verified with a live Postgres container during
development (`tests/storage/test_postgres_live.py`, `-m postgres`) — the same
`XAIRuntime`, `runtime.explain`, and capture pipeline ran unmodified against
both the in-memory and Postgres stores.

## ADR-013 — Raw or reconstructed chain-of-thought is never captured

**Context.** Capturing a model's raw internal reasoning tokens (when a
provider exposes them) or reconstructing "hidden" reasoning from partial
signals creates both a safety risk (leaking unvalidated reasoning to
end users) and a compliance risk.

**Decision.** `LLMExplanationEngine` only ever accepts a strictly validated
`ExplanationDraft` (`summary`, `reasons`, `disclosure` — `extra="forbid"`) from
the injected model, built from a prompt containing only already-captured,
policy-filtered observable facts. Any field the model invents outside that
schema is rejected, not silently accepted.

**Consequences.** This boundary is enforced by a real, reproducible test: a
live call to `gpt-5.6-luna` returning an extra `hidden_reasoning` field is
**rejected** with `ValueError: LLM explanation output failed schema
validation` (see `tests/explanation/test_engines.py::
test_llm_explanation_still_rejects_unknown_fields`). The same hardening also
had to tolerate real-world model output variance (a provider returning a
single string instead of a JSON array for `reasons`/`disclosure`) — handled
as a pure formatting normalization, not a schema relaxation.

## ADR-014 — Runtime and provider operations are async-first

**Context.** LangGraph applications are overwhelmingly async
(`ainvoke`/`astream`), and explainability capture must not become a
synchronous bottleneck on the hot path.

**Decision.** Every protocol method (`ProvenanceStore.write`,
`ObservabilityProvider.emit`, `AttributionEngine.attribute`,
`ExplanationEngine.explain`, `PolicyProvider.evaluate`, …) is `async def`.
The runtime bounds concurrency internally with a semaphore
(`XAIConfig.max_concurrency`) and applies the configured
[failure mode](failure.md) uniformly around every provider call.

**Consequences.** Verified under real concurrent load: 120 concurrent
`ainvoke` calls across 5 tenants complete correctly with tenant isolation
preserved (`tests/langgraph/test_instrumentation.py::
test_100_concurrent_runs_keep_tenants_isolated`).

## ADR-015 — Runtime and plugin state is instance-scoped, never global mutable state

**Context.** Global mutable singletons make multi-tenant, multi-graph, or
test-parallel deployments fragile and hard to reason about.

**Decision.** `XAIRuntime` holds all state (registry, config, error buffer,
concurrency semaphore) on the instance. The only module-level state is a
`contextvars.ContextVar` tracking the *currently active* run per async
context — never a shared mutable dict keyed by anything global.

**Consequences.** Multiple `XAIRuntime` instances (different applications,
different tenants, different test cases) can coexist in the same process
without cross-talk. This is exactly what the concurrency test in ADR-014
exercises.

## ADR-016 — Canonical serialized contracts carry a schema version

**Context.** Explainability artifacts are frequently persisted, exported,
and consumed by tooling built independently of the runtime version that
produced them. Silent schema drift breaks that tooling.

**Decision.** Every canonical model derived from `CanonicalModel` carries a
`schema_version: str = "1.0.0"` field, visible in every serialized payload
(see the real captured JSON in
[`examples/full_explanation_output.py`](../examples/full-explanation.md)'s
output — every nested object has its own `schema_version`).

**Consequences.** A consumer can detect and branch on schema version
without guessing from field presence/absence. A future v2 schema is an
additive, versioned change, not a silent break.

## ADR-017 — LangSmith and langgraph-xai are complementary

**Context.** Teams already invested in LangSmith for debugging and
evaluation should not have to choose between LangSmith and xgraph.

**Decision.** xgraph does not attempt to replace LangSmith's run tree,
evaluation, or debugging UI. It only optionally forwards canonical events to
an `ObservabilityProvider`, of which a LangSmith-compatible adapter can be
one implementation, alongside Langfuse and OpenTelemetry.

**Consequences.** Adopting xgraph is additive to an existing LangSmith
deployment, not a migration.

## ADR-018 — Policy controls disclosure; it is not a security middleware product

**Context.** "Policy" is an overloaded word. xgraph's policy layer must not
be mistaken for (or marketed as) an authorization, authentication, or
guardrails system.

**Decision.** `PolicyProvider`/`CapturePolicy` control exactly one thing:
what explainability data is captured, retained, and exposed, and to which
audience. They do not gate tool execution, do not authenticate callers, and
do not implement content moderation.

**Consequences.** Applications keep their existing authz/guardrails stack
untouched; xgraph's policy layer sits strictly downstream of "should this
tool call be allowed to run at all", governing only "should this already
-permitted execution's data be disclosed, and to whom".

## ADR-019 — Core configuration is explicit and per-runtime, not environment-driven

**Context.** An earlier draft of xgraph configured itself from environment
variables (`XAI_ENABLED`, `XAI_CAPTURE_STATE`, `XAI_FAILURE_MODE`, …). This
was rejected during review: a boolean "is explainability on" flag read from
the environment is meaningless in a library that is instantiated explicitly
per application, and split configuration (partly code, partly environment)
makes behavior harder to test and to reason about at a call site.

**Decision.** `XAIConfig` is a plain, explicit Pydantic model constructed in
code and passed to `XAIRuntime(config=...)`. There is no environment-variable
based on/off switch and no implicit environment fallback for runtime
behavior. Deployment-specific *values* (an API key, a database URL) are the
application's own concern, passed explicitly to the provider it constructs
(for example, `ChatOpenAI(api_key=os.environ["EXPLABS_API_KEY"], ...)` in the
examples) — xgraph itself never reads `os.environ`.

**Consequences.** Every runtime's behavior is fully visible at its
construction call site and trivially testable (construct a different
`XAIConfig` per test, no environment mutation required). The cost: no
"flip an env var in production to change behavior" convenience — an
explicit, reviewed code change (or an application's own config layer) is
required instead, which is the intended trade-off for a library whose
behavior affects what data is captured and disclosed.

---

Architecture versioning applies to public schemas, protocols, boundaries, and
semantic invariants captured by these ADRs. Future adapters and capabilities
can be added without changing those foundations. A breaking contract change
requires a new major architecture version and migration guidance.

