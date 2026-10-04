# langgraph-xai

[![PyPI](https://img.shields.io/pypi/v/langgraph-xai.svg)](https://pypi.org/project/langgraph-xai/)
[![Python](https://img.shields.io/pypi/pyversions/langgraph-xai.svg)](https://pypi.org/project/langgraph-xai/)
[![CI](https://github.com/smuniharish/langgraph-xai/actions/workflows/ci.yml/badge.svg)](https://github.com/smuniharish/langgraph-xai/actions/workflows/ci.yml)
[![Docs](https://readthedocs.org/projects/langgraph-xai/badge/?version=latest)](https://langgraph-xai.readthedocs.io/)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](https://github.com/smuniharish/langgraph-xai/blob/master/LICENSE)

**Explainability for LangGraph applications: what ran, why it was decided, and
what each audience may see.**

`langgraph-xai` wraps a compiled LangGraph graph and records every run as
structured, versioned records. Nodes, state changes, tools, retrievers, and
human-in-the-loop interrupts are captured automatically. Your code records the
evidence it relied on and the decisions it made. From those records it builds
explanations for developers, auditors, business owners, or end users, filtered
by a disclosure policy you control.

![langgraph-xai architecture](https://raw.githubusercontent.com/smuniharish/langgraph-xai/master/docs/assets/diagrams/architecture-overview.png)

## Features

- **Drop-in instrumentation.** `xai.instrument(graph)` records `invoke`,
  `stream`, `batch`, `astream_events`, and the other Runnable entry points,
  sync and async, without changing inputs, outputs, or exceptions. It works
  with `StateGraph`, the functional API, `create_agent`, `deepagents`,
  subgraphs, and MCP tools.
- **Human-in-the-loop aware.** Interrupts and resumes are recorded with the
  reviewer's answer. For a graph with a checkpointer, each run is linked to
  its checkpoints, and a resumed run points back to the run it continues, even
  across processes.
- **Evidence, decisions, and provenance as data.** Explanations are built from
  recorded facts, never from model reasoning.
- **Audience-aware explanations.** Attribution shows how much each factor and
  piece of evidence contributed. A per-audience policy decides what each
  reader sees, and withheld sections are announced.
- **Safe by default.** Credentials are redacted before anything is stored,
  explanations fail closed, LLM phrasing needs two explicit opt-ins, and
  instrumentation failures never break your graph unless you ask them to.
- **Pluggable.** Records are kept in memory by default. Subclass
  `ProvenanceStore` for your database; a complete PostgreSQL store is included
  as an example. Events can be forwarded to LangSmith, Langfuse, or any
  OpenTelemetry backend.

## Install

```bash
pip install langgraph-xai
```

Requires Python 3.12+, LangGraph 1.x (1.2.12 or newer), and LangChain Core 1.x
(1.6.6 or newer). Integrations are optional extras:

```bash
pip install "langgraph-xai[langsmith]"   # LangSmithObservability
pip install "langgraph-xai[langfuse]"    # LangfuseObservability
pip install "langgraph-xai[otel]"        # OpenTelemetryObservability
pip install "langgraph-xai[llm-openai]"  # LLM-phrased explanations with langchain-openai
```

## Quickstart

```python
import asyncio
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from langgraph_xai import Audience, DecisionType, EvidenceType, XAIRuntime

xai = XAIRuntime(application_id="payments", tenant_id="acme-bank", graph_id="fraud-review")


class Review(TypedDict, total=False):
    amount: float
    risk_score: float
    route: str


async def score_risk(state: Review) -> Review:
    risk_score = 0.91 if state["amount"] > 5000 else 0.12
    await xai.record_evidence(
        EvidenceType.TOOL_RESULT,
        summary=f"Fraud model scored the transaction {risk_score:.2f}.",
        confidence=0.97,
    )
    return {"risk_score": risk_score}


async def route(state: Review) -> Review:
    run = xai.current_run  # the run of the instrumented call executing this node
    assert run is not None
    selected = "HUMAN_REVIEW" if state["risk_score"] >= 0.8 else "AUTO_APPROVE"
    await xai.record_decision(
        selected,
        decision_type=DecisionType.ROUTING,
        candidate_actions=["AUTO_APPROVE", "HUMAN_REVIEW"],
        evidence_ids=[item.id for item in run.evidence],
        confidence=0.93,
    )
    return {"route": selected}


builder = StateGraph(Review)
builder.add_node("score_risk", score_risk)
builder.add_node("route", route)
builder.add_edge(START, "score_risk")
builder.add_edge("score_risk", "route")
builder.add_edge("route", END)
graph = xai.instrument(builder.compile())


async def main() -> None:
    with xai.collect_runs() as runs:
        result = await graph.ainvoke({"amount": 9200.0})
    (run,) = runs

    print(result)
    print([f"{node.node_id}: {node.status}" for node in run.execution.nodes])

    explanation = await xai.explain_decision(run.decisions[0], audience=Audience.AUDITOR, run=run)
    print(explanation.summary)
    print(explanation.reasons)


asyncio.run(main())
```

Output:

```text
{'amount': 9200.0, 'risk_score': 0.91, 'route': 'HUMAN_REVIEW'}
['score_risk: completed', 'route: completed']
The routing decision selected 'HUMAN_REVIEW'.
['Selected action: HUMAN_REVIEW.', 'Alternatives considered: AUTO_APPROVE.', 'Decision confidence: 0.93.']
```

The [fraud review example](https://langgraph-xai.readthedocs.io/en/latest/examples/full-explanation/)
goes further: it explains one decision to an auditor, with attribution and
evidence, and to a customer, with internal scores withheld and the withholding
disclosed.

## How it relates to tracing

LangSmith, Langfuse, and OpenTelemetry show **what ran**: run trees, spans,
latency, tokens. `langgraph-xai` records **why it was decided** and **who may
see the explanation**. The two work together, and the bundled adapters send
`langgraph-xai` events to the tracing backend you already use.

## Documentation

Full documentation: **[langgraph-xai.readthedocs.io](https://langgraph-xai.readthedocs.io/)**

- [Quickstart](https://langgraph-xai.readthedocs.io/en/latest/getting-started/quickstart/)
- [Concepts](https://langgraph-xai.readthedocs.io/en/latest/concepts/)
- [How-to guides](https://langgraph-xai.readthedocs.io/en/latest/how-to/)
- [Examples](https://langgraph-xai.readthedocs.io/en/latest/examples/)
- [API reference](https://langgraph-xai.readthedocs.io/en/latest/api/)

`langgraph-xai` 1.x follows semantic versioning: minor releases add features
without breaking your code or your stored records. Changes are listed in the
[changelog](https://github.com/smuniharish/langgraph-xai/blob/master/CHANGELOG.md).

An [Agent Skill](https://langgraph-xai.readthedocs.io/en/latest/agent-skills/)
teaches coding agents such as Claude Code, Codex, Cursor, and GitHub Copilot to
integrate `langgraph-xai` correctly.

## Contributing

Contributions are welcome. See
[CONTRIBUTING.md](https://github.com/smuniharish/langgraph-xai/blob/master/CONTRIBUTING.md)
for the development setup and checks, and
[SECURITY.md](https://github.com/smuniharish/langgraph-xai/blob/master/SECURITY.md)
to report a vulnerability.

## License

Apache License 2.0. See
[LICENSE](https://github.com/smuniharish/langgraph-xai/blob/master/LICENSE).
