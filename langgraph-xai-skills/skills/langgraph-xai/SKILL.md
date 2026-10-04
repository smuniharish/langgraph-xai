---
name: langgraph-xai
description: Integrate, configure, test, and debug langgraph-xai, the explainability layer for LangGraph. Use when a LangGraph graph or agent (StateGraph, the functional API, create_agent, deepagents) must record what ran and why - execution records, evidence and decisions, provenance, attribution, audience-specific explanations with disclosure policies, human-in-the-loop interrupts and checkpoints - or export those records to LangSmith, Langfuse, OpenTelemetry, or a database. Also use when explanations are missing, withheld, or failing, or when runs are not recorded. Do not use to collect model chain-of-thought or as a replacement for a tracing tool.
license: Apache-2.0
compatibility: Python 3.12 or newer with LangGraph 1.x. Installs langgraph-xai 1.x from PyPI. scripts/verify_setup.py runs offline in the project's Python environment.
metadata:
  version: "1.0.0"
  documentation: "https://langgraph-xai.readthedocs.io"
---

# langgraph-xai

`langgraph-xai` wraps a compiled LangGraph graph and records every run as
versioned records. Nodes, state changes, tools, retrievers, interrupts, and
checkpoints are captured automatically. Application code records the evidence
it relied on and the decisions it made. Explanations are built from those
records for one audience at a time and filtered by a disclosure policy.

Use this skill to add the existing package to an application. It is not an
agent framework, a tracing backend, or a way to record model reasoning.

## Before you change anything

1. From the project's Python environment, run the setup check in this skill's
   directory:

   ```bash
   python scripts/verify_setup.py
   ```

   It checks Python and package versions and runs a small instrumented graph
   offline. Fix every `FAIL` line first.
2. Find the compiled graphs or agents to instrument, any existing
   `XAIRuntime`, and the tests that cover them.
3. Pick the matching recipe in [references/RECIPES.md](references/RECIPES.md).
   Look up exact signatures in [references/API.md](references/API.md).

## Core workflow

1. Install the package. Add an extra only for the integrations you use:
   `langsmith`, `langfuse`, `otel`, `llm-openai`, or `all`.

   ```bash
   pip install langgraph-xai
   ```

2. Create one runtime per application and tenant boundary, and instrument the
   compiled graph. The wrapper is called exactly like the graph.

   ```python
   from langgraph_xai import XAIRuntime

   xai = XAIRuntime(application_id="payments", tenant_id="acme-bank", graph_id="fraud-review")
   graph = xai.instrument(builder.compile())
   ```

3. Inside nodes, tools, or middleware, record why. The `record_*` methods are
   coroutines; a synchronous node wraps them in `xai.run_sync(...)`.

   ```python
   evidence = await xai.record_evidence(
       EvidenceType.TOOL_RESULT, summary="Fraud model scored the transaction 0.91.", confidence=0.97
   )
   await xai.record_decision(
       "HUMAN_REVIEW",
       decision_type=DecisionType.ROUTING,
       candidate_actions=["AUTO_APPROVE", "HUMAN_REVIEW"],
       evidence_ids=[evidence.id],
       factors=[DecisionFactor(name="fraud_risk_score", value=0.91, evidence_ids=[evidence.id])],
   )
   ```

4. Keep the run and explain the decision after the call returns:

   ```python
   with xai.collect_runs() as runs:
       result = await graph.ainvoke({"amount": 9200.0})
   (run,) = runs
   explanation = await xai.explain_decision(run.decisions[-1], audience=Audience.AUDITOR, run=run)
   ```

5. If different audiences may see different things, register a
   `PolicyProvider` and test it with
   [assets/test_disclosure_policy.py](assets/test_disclosure_policy.py).
6. Run the project's tests, then `python scripts/verify_setup.py` again.

## Rules

- **Observe, never steer.** Do not change graph inputs, outputs, state, or
  control flow to make recording work.
- **Record decisions explicitly.** Call `record_decision` where the
  application decides. Never infer a decision from a trace, and never ask a
  model for its chain-of-thought.
- **Let instrumentation create execution records.** Do not build `Execution`,
  `NodeExecution`, or event models by hand for instrumented calls. Use
  `start_run` and `finish_run` only for work outside any instrumented graph.
- **Instrument the runnable you call.** Methods that build a new runnable,
  such as `graph.with_retry()` or `graph.bind(...)`, return an uninstrumented
  runnable. `with_config(...)` keeps the instrumentation.
- **Use the recorded entry points.** `invoke`, `stream`, `batch`,
  `batch_as_completed`, `astream_events` (v1 and v2), `transform`, and their
  async forms are recorded. LangGraph's experimental v3 streaming
  (`stream_events`, `astream_events(version="v3")`) and LangChain's deprecated
  `astream_log` are not.
- **Keep the policy boundary.** Never weaken a disclosure policy, redaction,
  or capture settings to make a test or an export pass.
- **Keep secrets out of records.** Redaction works on key names such as
  `api_key` or `token`, not on values. Reference people and documents by ID.
- **Choose the failure mode on purpose.** `FAIL_OPEN`, the default, never
  breaks the graph and keeps errors in `xai.errors`. `FAIL_CLOSED` and
  `STRICT` raise `XAIInstrumentationError`. Explanations fail closed in every
  mode.

## Human-in-the-loop

Compile the graph with a LangGraph checkpointer and call it with a
`thread_id`. Interrupts, `Command(resume=...)` answers, static breakpoints,
and checkpoints are then recorded automatically. A resumed, retried, or
replayed run names the run it continues in `Execution.continuation_of`.
Record approvals made outside the graph with `record_human_interaction`, even
after the run finished. Do not also call `record_checkpoint` for these graphs,
which would record each checkpoint twice; it is for runs you manage yourself
or for `XAIConfig(capture_checkpoints=False)`.

## Where records go

- `Execution`, events, and provenance links go to the `ProvenanceStore`, by
  default `InMemoryProvenanceStore`. To persist them, subclass
  `ProvenanceStore`.
- Evidence, decisions, and memory references are kept on `run.evidence` and
  `run.decisions` and delivered to `XAIPlugin` instances, not to the store.
- Events can also go to one `ObservabilityProvider`: LangSmith, Langfuse, or
  OpenTelemetry.

## When something is wrong

Check `xai.errors` first, then follow
[references/TROUBLESHOOTING.md](references/TROUBLESHOOTING.md). Common causes:

- `RuntimeError: no active run`: a `record_*` call ran outside an instrumented
  call. Pass `run=` or record inside the graph.
- No run was recorded: the call went to the uninstrumented graph, or used an
  entry point that is not recorded.
- An explanation raises `XAIInstrumentationError`: the policy, attribution, or
  engine failed; the cause is in `xai.errors`.

## References

- [references/API.md](references/API.md): public imports, methods, settings,
  and records.
- [references/RECIPES.md](references/RECIPES.md): complete patterns for common
  integration tasks.
- [references/TROUBLESHOOTING.md](references/TROUBLESHOOTING.md): symptoms,
  causes, and fixes.
- Documentation: <https://langgraph-xai.readthedocs.io>
