# Examples

Complete, runnable programs in the
[`examples/`](https://github.com/smuniharish/langgraph-xai/tree/master/examples)
directory. Every page shows real output from running the script. The offline
examples also run in the test suite, so they keep working.

## Run without any service

| Example | Shows |
| --- | --- |
| [Minimal graph](minimal-graph.md) | The smallest instrumented graph and what it captures |
| [Fraud review: full explanation](full-explanation.md) | Evidence, a decision, provenance, and one decision explained to two audiences |
| [Retrieval and tools](retrieval-and-tools.md) | Retrievers and `ToolNode` calls captured automatically and turned into evidence |
| [Human-in-the-loop](interrupt-hitl.md) | `interrupt()` and `Command(resume=...)`, linked to the checkpoint to replay |
| [Multi-agent retries and correlation](multi-agent-retry.md) | A recovered tool timeout and a shared run and trace ID |
| [Disclosure matrix](disclosure-matrix.md) | One decision checked against every policy, audience, and engine |

Two more scripts back the documentation: the
[canonical model gallery](https://github.com/smuniharish/langgraph-xai/blob/master/examples/canonical_model_gallery.py)
prints every record type for the [Concepts](../concepts/index.md) pages, and
[`failure_modes.py`](https://github.com/smuniharish/langgraph-xai/blob/master/examples/failure_modes.py)
produces the output in [Configure failure modes](../how-to/failure-modes.md).

## Run with a chat model

These need `OPENAI_API_KEY`. Set `OPENAI_BASE_URL` for an OpenAI-compatible
gateway and `OPENAI_MODEL` to pick the model (default `gpt-4o-mini`).

| Example | Shows | Also needs |
| --- | --- | --- |
| [create_agent decision](create-agent.md) | Recording and explaining a decision from agent middleware | |
| [create_agent inside a node](create-agent-nested.md) | An agent nested in a larger graph, captured as one run | |
| [deepagents](deepagents.md) | A deep agent instrumented with no framework-specific code | `examples` group |
| [MCP tools](mcp-tools.md) | Tool calls served by the Playwright MCP server | `examples` group, Node.js |

## Run with a database

| Example | Shows | Needs |
| --- | --- | --- |
| [PostgreSQL store](postgres-store.md) | A complete `ProvenanceStore` subclass that keeps records in PostgreSQL | `examples` group, `XAI_POSTGRES_DSN` |

## Running an example

From a clone of the repository:

```bash
uv sync --all-extras --all-groups
uv run python examples/fraud_review.py
```

For the model-backed examples:

```bash
export OPENAI_API_KEY=...
uv run python examples/create_agent_decision_explanation.py
```
