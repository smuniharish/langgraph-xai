# Testing

The default test run needs no services, no network, and no API keys. Live
suites run against real backends when you point them at one.

## Everyday commands

```bash
uv sync --all-extras --all-groups
uv run pytest                                              # the full offline suite
uv run pytest --cov=langgraph_xai --cov-branch             # with coverage (kept at 100%)
uv run ruff check . && uv run ruff format --check .        # lint and formatting
uv run pyrefly check                                       # type checking
```

Warnings are errors: pytest runs with `filterwarnings = ["error"]`, so a new
deprecation warning from the package or a dependency fails the suite until it
is fixed. Ignores are narrow and name the third-party warning they silence.

## Layout

| Directory | Covers |
| --- | --- |
| `tests/unit` | Models, configuration, registry, redaction, plugins |
| `tests/runtime` | The run lifecycle, recording, failure modes, concurrency, the sync bridge |
| `tests/langgraph` | Instrumentation of real LangGraph graphs: every entry point, output version, and stream mode; nodes, state, tools, retrievers; interrupts, static breakpoints, checkpoints, and resumed runs; subgraphs, `Send`, the functional API, node caching, `create_agent` |
| `tests/attribution`, `tests/explanation` | Attribution math, explanation content, disclosure, the LLM engine with stub models |
| `tests/storage` | The in-memory store, including a stateful property test |
| `tests/observability` | Every adapter, against the real LangSmith, Langfuse, and OpenTelemetry SDKs |
| `tests/examples` | Every example script, the PostgreSQL store example, and the README and documentation quickstarts |
| `tests/skill` | The Agent Skill: the reference validator, links, the setup check, and the test template |
| `tests/benchmarks` | Performance regression bounds |
| `tests/live` | The LLM explanation engine against a real model |

## Property-based tests

[Hypothesis](https://hypothesis.readthedocs.io) checks invariants over
generated inputs. For example:

- redaction always returns JSON-safe data, is idempotent, and never keeps a
  credential-named value at any depth;
- every canonical event, and an execution holding every kind of record,
  survives a JSON round trip;
- normalized attribution always sums to 1, and attribution weights are the
  shares of each source;
- every withheld section is announced, and invalid LLM replies are rejected
  with `ValueError`, never another error;
- events of one run stay strictly ordered under concurrent recording;
- the in-memory store behaves like a simple model under random sequences of
  writes and queries, and pagination partitions query results.

Three profiles are registered:

| Profile | Use |
| --- | --- |
| `default` | Local runs: 100 examples per test, no deadline |
| `ci` | Continuous integration: 300 examples, derandomized, failing examples printed for reproduction |
| `thorough` | Before a release: 2,000 examples per test |

```bash
HYPOTHESIS_PROFILE=ci uv run pytest
HYPOTHESIS_PROFILE=thorough uv run pytest tests/unit tests/storage
```

## Markers

| Marker | Selects |
| --- | --- |
| `examples` | Tests that run the scripts under `examples/` |
| `live` | Tests that need an external service |
| `postgres` | Tests that need `XAI_TEST_POSTGRES_DSN` |
| `benchmark` | Performance regression tests |

`uv run pytest -m "not live and not postgres"` runs everything that never
touches the network.

## Live suites

Each live suite is skipped unless its environment variables are set. Each one
asserts that data actually arrived, not just that a call did not raise.

| Suite | Environment variables |
| --- | --- |
| `tests/examples/test_postgres_store_live.py` | `XAI_TEST_POSTGRES_DSN` |
| `tests/observability/test_otel_live.py` | `XAI_TEST_OTEL_ENDPOINT` (an OTLP/HTTP endpoint) |
| `tests/observability/test_langfuse_live.py` | `XAI_TEST_LANGFUSE_HOST`, `XAI_TEST_LANGFUSE_PUBLIC_KEY`, `XAI_TEST_LANGFUSE_SECRET_KEY` |
| `tests/live/test_llm_explanation_live.py` and the model-backed examples | `XAI_TEST_LLM_API_KEY`, optionally `XAI_TEST_LLM_BASE_URL` and `XAI_TEST_LLM_MODEL` |

A local PostgreSQL and OpenTelemetry Collector, with Docker or Podman:

```bash
docker run -d --name xai-postgres -e POSTGRES_PASSWORD=xai -e POSTGRES_DB=xai \
    -p 55432:5432 postgres:18-alpine
docker run -d --name xai-otel -p 4318:4318 otel/opentelemetry-collector:latest

export XAI_TEST_POSTGRES_DSN=postgresql://postgres:xai@localhost:55432/xai
export XAI_TEST_OTEL_ENDPOINT=http://localhost:4318
uv pip install opentelemetry-exporter-otlp-proto-http
uv run pytest -m "live or postgres"
```

For Langfuse, run a self-hosted instance (see the
[Langfuse self-hosting guide](https://langfuse.com/self-hosting)) and create a
project key. Live suites create their own identifiers, or truncate their own
table, so repeated runs stay independent.

## Live LLM evaluation

`scripts/run-live-llm-evaluation.py` runs the LLM explanation engine over fixed
scenarios and reports schema validity, grounding against expected terms, policy
safety, and latency:

```bash
export OPENAI_API_KEY=...          # never pass keys as command-line arguments
uv run python scripts/run-live-llm-evaluation.py --model gpt-4o-mini
```

Use `--base-url` (or `OPENAI_BASE_URL`) for OpenAI-compatible endpoints. Reports
are written as JSON and Markdown under `reports/live-llm-evaluation/`, which is
ignored by git. The results are repeatable engineering checks, not a
statistical claim about model accuracy.

## Documentation

```bash
uv run mkdocs build --strict           # fails on broken links and references
node scripts/render-diagrams.mjs        # re-render diagrams after editing diagrams/*.mmd
node scripts/render-diagrams.mjs --check
```

Diagrams are rendered with Mermaid CLI 12.0.0, installed globally
(`npm install --global --allow-scripts=puppeteer @mermaid-js/mermaid-cli@12.0.0`,
Node.js 22.13 or later). The check needs only Node.js, and fails when a
rendered image is missing, stale, or has no source.
