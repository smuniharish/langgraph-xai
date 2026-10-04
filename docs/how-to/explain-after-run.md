# Explain a decision after the run

Decisions are recorded while the graph runs, but explanations are usually
requested afterwards: when a reviewer opens a case or a customer asks why. This
guide shows three ways to get from a finished call to an explanation.

## Keep the run with `collect_runs`

`collect_runs()` collects every run the runtime starts inside the `with` block.
Each run holds its `Execution`, evidence, and decisions.

```python
with xai.collect_runs() as runs:
    result = await graph.ainvoke({"amount": 9200.0})
(run,) = runs

explanation = await xai.explain_decision(run.decisions[-1], audience=Audience.AUDITOR, run=run)
```

Collection follows the async context:

- Runs started by tasks spawned inside the block are included, for example by
  `asyncio.gather` or `abatch`.
- Runs started concurrently elsewhere are not.
- An inner `collect_runs` block takes precedence over an outer one.

A batch call collects one run per input:

```python
with xai.collect_runs() as runs:
    results = await graph.abatch([{"amount": 120.0}, {"amount": 9200.0}])
assert len(runs) == 2
```

## Record and explain outside a graph

Work that does not go through an instrumented graph, such as a batch scoring
job or a rules engine, can still record evidence and decisions. Start and
finish the run yourself, and pass it explicitly:

```python
run = await xai.start_run({"metadata": {"trace_id": "job-42"}})
score = await xai.record_evidence(EvidenceType.TOOL_RESULT, summary="Score 0.91.", run=run)
decision = await xai.record_decision("HUMAN_REVIEW", evidence_ids=[score.id], run=run)
await xai.finish_run(run)

explanation = await xai.explain_decision(decision, run=run)
```

Do not combine this with an instrumented call for the same work. The
instrumented call starts its own run.

## Explain later from persisted records

Runs live in memory. To explain a decision in another process or days later,
persist two things:

- **Executions.** These are written to the `ProvenanceStore`. In production,
  use a database store, such as the
  [PostgreSQL store example](../examples/postgres-store.md).
- **Evidence and decisions.** These are delivered to [plugins](../architecture/plugins.md),
  not to the store.

Later, rebuild an `ExplanationContext` and call `explain`:

```python
class Archive:
    """An XAIPlugin that keeps every evidence and decision record (use your database)."""

    def __init__(self) -> None:
        self.artifacts = {}

    async def record(self, artifact) -> None:
        self.artifacts[artifact.id] = artifact

    async def flush(self) -> None:
        pass

    async def close(self) -> None:
        pass


archive = Archive()
xai = XAIRuntime(application_id="payments", tenant_id="acme-bank", plugins=(archive,))
```

```python
async def explain_later(run_id) -> None:
    store = xai.registry.require(ProvenanceStore)
    query = StoreFilter(
        application_id="payments", tenant_id="acme-bank", run_id=run_id, item_type=Execution
    )
    (execution,) = [record async for record in store.query(query)]
    decision = next(
        item
        for item in archive.artifacts.values()
        if isinstance(item, Decision) and item.context.run_id == execution.context.run_id
    )
    evidence = [archive.artifacts[evidence_id] for evidence_id in decision.evidence_ids]
    explanation = await xai.explain(
        ExplanationContext(
            execution=execution, decision=decision, evidence=evidence, audience=Audience.AUDITOR
        )
    )
    print(explanation.summary)
    print([item.label for item in explanation.contributing_factors])
```

Output:

```text
The routing decision selected 'HUMAN_REVIEW'.
['Fraud score 0.91.']
```

`explain` applies the same policy, attribution, and engine as
`explain_decision`. Given the same records, it produces the same explanation.
To mirror `explain_decision` exactly, also include the evidence referenced by
the decision's factors.
