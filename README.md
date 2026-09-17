# langgraph-xai

[![CI](https://github.com/samamuniharish/langgraph-xai/actions/workflows/ci.yml/badge.svg)](https://github.com/samamuniharish/langgraph-xai/actions/workflows/ci.yml)
[![Docs](https://github.com/samamuniharish/langgraph-xai/actions/workflows/docs.yml/badge.svg)](https://samamuniharish.github.io/langgraph-xai/)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](pyproject.toml)

`langgraph-xai` is a provider-neutral explainability layer for LangGraph
applications. It turns observable graph execution into structured execution,
provenance, evidence, decisions, attribution, policy-aware disclosure, and
human-readable explanations.

It is not an observability platform, a LangGraph replacement, a security
middleware framework, or a chain-of-thought recorder. LangSmith, Langfuse, and
OpenTelemetry are complementary integrations.

## Installation

```bash
pip install langgraph-xai
```

The Python import namespace is:

```python
from langgraph_xai import XAIRuntime
```

Optional integrations are isolated:

```bash
pip install "langgraph-xai[postgres]"
pip install "langgraph-xai[langsmith]"
pip install "langgraph-xai[langfuse]"
pip install "langgraph-xai[otel]"
pip install "langgraph-xai[llm-openai]"
```

## Quickstart

```python
from langgraph.graph import END, START, StateGraph
from langgraph_xai import XAIRuntime

builder = StateGraph(dict)
builder.add_node("answer", lambda state: {**state, "answer": "observable result"})
builder.add_edge(START, "answer")
builder.add_edge("answer", END)

xai = XAIRuntime(application_id="support", tenant_id="tenant-a")
graph = xai.instrument(builder.compile())
result = await graph.ainvoke({"question": "Why?"})
```

Runtime behavior is configured explicitly per instance. There is no global
`XAI_ENABLED` environment switch:

```python
from langgraph_xai import CaptureMode, FailureMode, XAIConfig, XAIRuntime

xai = XAIRuntime(
    config=XAIConfig(
        capture_state=CaptureMode.DELTA,
        failure_mode=FailureMode.FAIL_OPEN,
        llm_explanation_enabled=False,
    )
)
```

Structured explanations are the default. LLM explanations require both a
registered `LLMExplanationEngine` and
`XAIConfig(llm_explanation_enabled=True)`. They consume only policy-filtered,
structured XAI context and never request or store chain-of-thought.

## Development

```bash
uv sync
uv run ruff check .
uv run ruff format --check .
uv run pyrefly check
uv run pytest
```

Documentation diagrams use a global pinned Mermaid CLI rather than local
`node_modules`:

```bash
npm install --global @mermaid-js/mermaid-cli@11.17.0
node scripts/render-diagrams.mjs
node scripts/render-diagrams.mjs --check
```

The project requires Python 3.12 or newer and is licensed under Apache-2.0.
