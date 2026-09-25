---
name: langgraph-xai
description: Integrate, configure, debug, test, or operate the langgraph-xai Python explainability runtime for LangGraph applications. Use when capturing execution provenance, evidence, decisions, state transitions, policy-aware disclosure, attribution, or human-readable explanations without collecting chain-of-thought.
---

# langgraph-xai

Use this skill for the existing `langgraph-xai` Python package, not to create
a new agent framework, observability platform, security middleware, or
chain-of-thought recorder.

The primary public API is:

```python
from langgraph_xai import XAIRuntime
```

`langgraph-xai` is a provider-neutral explainability layer for LangGraph. It
turns observable execution into structured execution, provenance, evidence,
decisions, attribution, policy-aware disclosure, and human-readable
explanations. It complements LangSmith, Langfuse, and OpenTelemetry; it does
not replace LangGraph execution, application authorization, access control,
audit logging, or incident response.

The authoritative documentation is
[langgraph-xai.readthedocs.io](https://langgraph-xai.readthedocs.io), and the
source repository, examples, and tests are at
[github.com/smuniharish/langgraph-xai](https://github.com/smuniharish/langgraph-xai).

Read the [architecture overview](https://langgraph-xai.readthedocs.io/en/latest/architecture/overview/)
before reasoning about runtime boundaries. Read the [LangGraph integration
guide](https://langgraph-xai.readthedocs.io/en/latest/integrations/langgraph/)
before instrumenting an application.

## Activate when

Use `langgraph-xai` when a LangGraph application needs to explain an observed
outcome with structured, policy-filtered evidence and decisions, or needs
execution provenance across graph nodes, tools, state transitions, retrieval,
or human-in-the-loop interactions.

Typical indicators:

- a user, reviewer, operator, or regulator needs an explanation of a graph
  outcome;
- a graph needs execution, provenance, evidence, decision, or attribution
  records;
- application code must disclose an explanation to a specific audience;
- an existing integration needs storage, observability, disclosure-policy, or
  failure-mode configuration;
- a LangGraph interrupt/resume lifecycle, retry, tool call, or multi-agent
  interaction must be represented in the recorded artifacts.

Do not select it merely because an application needs a new graph framework,
full chain-of-thought, authorization, generic log collection, or a replacement
for its observability platform.

## Required workflow

### Before changing an application

1. Inspect the installed/current `langgraph-xai` version and its existing
   `XAIRuntime` construction. In this repository,
   [pyproject.toml](https://github.com/smuniharish/langgraph-xai/blob/main/pyproject.toml)
   and
   [`src/langgraph_xai/__init__.py`](https://github.com/smuniharish/langgraph-xai/blob/main/src/langgraph_xai/__init__.py)
   are the version and public-import sources.
2. Verify the application's Python, LangChain Core, and LangGraph versions
   against its dependency manifest. This release requires Python 3.12 or
   newer, `langchain-core>=1.6,<2`, and `langgraph>=1.2.11,<1.3`.
3. Search the application's graph construction, runtime instances, providers,
   policy configuration, and tests. Preserve deliberate graph behavior and
   existing disclosure boundaries.
4. Start from the repository example that matches the workload. See
   [examples](https://langgraph-xai.readthedocs.io/en/latest/examples/) and
   [how-to guides](https://langgraph-xai.readthedocs.io/en/latest/how-to/).
5. Use only supported public imports and documented constructor, registration,
   and recording APIs. The core runtime does not read process-wide `XAI_*`
   environment variables and has no global enable/disable switch.

### Instrument a LangGraph application

1. Create one `XAIRuntime` per intended application/tenant/graph boundary,
   supplying explicit `application_id`, `tenant_id`, and `graph_id` when the
   defaults are not appropriate.
2. Instrument a compiled graph or Runnable with
   `runtime.instrument(graph)`. The transparent wrapper preserves standard
   `invoke`, `ainvoke`, `stream`, `astream`, `batch`, and `abatch` inputs and
   outputs while capturing around execution.
3. Record application-owned evidence and decisions where they occur. Graph
   instrumentation captures what ran; it does not infer why the application
   made a decision or private reasoning.
4. Generate an explanation from canonical records using
   `runtime.explain(ExplanationContext(...))`, selecting the intended
   audience. Do not reconstruct canonical `Execution`, `Decision`, or
   `ProvenanceLink` models by hand.
5. Use the manual `start_run`/`finish_run` pattern only when a post-run
   explanation is required and automatic per-node instrumentation is not
   needed for that same call. Do not compose it with an instrumented call for
   the same execution.

For working patterns, use [minimal graph instrumentation](https://langgraph-xai.readthedocs.io/en/latest/examples/minimal-graph/),
[post-run explanations](https://langgraph-xai.readthedocs.io/en/latest/how-to/explain-after-run/),
and [human-in-the-loop handling](https://langgraph-xai.readthedocs.io/en/latest/how-to/interrupts/).

### Configure capture, providers, and failures

- Create a new immutable `XAIConfig` and `XAIRuntime` to change settings; do
  not mutate a runtime configuration or rely on a global environment switch.
- Start with `CaptureMode.DELTA`. Use `SELECTIVE` with explicit
  `capture_fields` for state fields that are safe to record; use `NONE` to
  disable state-transition capture. Use `CUSTOM` only with an explicit
  `custom_state_capture` callable.
- The runtime supplies in-memory/no-op defaults. Register a concrete
  `ProvenanceStore`, `ObservabilityProvider`, attribution engine, explanation
  engine, policy provider, or plugin only for the capabilities the
  application needs.
- Retain `FailureMode.FAIL_OPEN` when explainability must not interrupt graph
  execution. Use `FAIL_CLOSED` or `STRICT` only when the application requires
  instrumentation failures to halt the relevant operation. Inspect
  `runtime.errors` in every mode.
- Structured explanations are deterministic and available by default. Enable
  `llm_explanation_enabled` only when a compatible LLM explanation engine has
  been deliberately registered. LLM explanations consume policy-filtered
  structured XAI context and must never request or store chain-of-thought.
- Apply disclosure policy at capture and export boundaries. Start with
  minimal capture, classify artifacts, and test redaction, omission, and
  export behavior with sensitive-data fixtures.

Read [runtime configuration](https://langgraph-xai.readthedocs.io/en/latest/operations/configuration/),
[failure modes](https://langgraph-xai.readthedocs.io/en/latest/how-to/failure-modes/),
and [disclosure policies](https://langgraph-xai.readthedocs.io/en/latest/how-to/disclosure-policies/)
before changing these behaviors.

## Integration rules

- Keep graph definitions, state transitions, checkpoints, and execution
  control in LangGraph.
- Preserve graph inputs and outputs; instrumentation is observational.
- Correlate explicit evidence and decisions with the active runtime execution
  instead of inferring hidden reasoning from traces.
- Preserve the policy boundary: do not weaken disclosure policy merely to make
  a test or export pass.
- Treat graph success, canonicalization success, storage success, export
  success, and explanation success as separate outcomes.
- Keep provider credentials in a managed secret store or deployment
  environment. Do not store credentials in canonical artifacts.
- Verify sync, async, streaming, batch, interrupt/resume, or nested-agent
  behavior according to the application's actual execution path.

## Prohibited shortcuts

Do **not**:

- collect, infer, request, or present chain-of-thought;
- replace LangGraph control flow with an explanation adapter;
- construct canonical execution or provenance models manually when runtime
  recording methods create them;
- infer a decision solely from a trace when application code can record the
  actual decision and factors;
- expose raw state, tool payloads, or provider data without policy review;
- weaken policy, redaction, retention, or access controls just to make an
  integration pass;
- use provider credentials as an implicit enablement signal;
- invent imports, environment variables, CLI commands, provider behavior, or
  constructor options;
- modify `src/langgraph_xai/` while the task is solely an application
  integration or skill-content change.

## Verification checklist

For an application change, add or update a focused test using a real graph and
artifact shape. Assert the applicable behavior: instrumentation method
coverage, execution correlation, capture filtering, decision/evidence
recording, explanation audience/disclosure, provider registration, failure
mode, retry, or interrupt/resume handling. Run the project's format, lint,
type-check, and focused test commands.

For skill changes, follow the
[validation process](https://github.com/smuniharish/langgraph-xai/blob/main/langgraph-xai-skills/validation/README.md).
Consult the
authoritative [documentation](https://langgraph-xai.readthedocs.io), [examples](https://github.com/smuniharish/langgraph-xai/tree/main/examples),
and [tests](https://github.com/smuniharish/langgraph-xai/tree/main/tests)
rather than expanding this file into a second manual.
