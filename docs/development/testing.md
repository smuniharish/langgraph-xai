# Testing and live-evaluation methodology

## Kid-level view

Tests check that the note-taker writes the right labels. Live evaluation
checks whether those labels help real people without leaking private data.

## Production view

Use layered tests:

1. Unit-test canonical validation, policy outcomes, ordering, redaction, and
   failure modes with deterministic fixtures.
2. Contract-test each adapter for schema, correlation, retries, and retention.
3. Integration-test a small graph with parallel nodes and missing providers.
4. Run live evaluations on a versioned, consented dataset with fixed prompts,
   expected evidence references, reviewer rubrics, and privacy checks.

Measure factual support, citation/source resolution, decision consistency,
uncertainty preservation, latency, export failure rate, and sensitive-field
leakage. Compare changes against a baseline; do not optimize for fluent prose
alone. Keep live data out of source control and record dataset/model/policy
versions.

The repository includes an opt-in OpenAI-compatible evaluation harness. Keep
the key in the process environment; never pass it as a command argument:

```powershell
$env:EXPLABS_API_KEY = "<set outside source control>"
uv run --extra llm-openai python scripts\run-live-llm-evaluation.py
```

The harness writes JSON and Markdown reports with schema-success rate,
expected-term grounded-rubric pass rate, policy-safety pass rate, per-scenario
errors, and minimum/median/maximum latency. These are repeatable engineering
checks, not a claim of statistical model accuracy.

## Live infrastructure integration tests

`ruff`, `pyrefly`, and the default `pytest` run all use fakes and in-memory
fixtures so contributors never need external services. Three additional
suites validate the optional adapters against **real** backends and are
skipped automatically unless you point them at a running instance:

| Suite | Marker | Required environment variables |
| --- | --- | --- |
| `tests/storage/test_postgres_live.py` | `postgres` | `XAI_TEST_POSTGRES_DSN` |
| `tests/observability/test_otel_live.py` | `live` | `XAI_TEST_OTEL_ENDPOINT` |
| `tests/observability/test_langfuse_live.py` | `live` | `XAI_TEST_LANGFUSE_HOST`, `XAI_TEST_LANGFUSE_PUBLIC_KEY`, `XAI_TEST_LANGFUSE_SECRET_KEY` |

A minimal local stack can be started with [Podman](https://podman.io) (Docker
works identically):

```powershell
podman network create xai-net

# PostgreSQL, for PostgresProvenanceStore
podman run -d --name xai-postgres --network xai-net `
    -e POSTGRES_PASSWORD=xai_test -e POSTGRES_DB=xai `
    -p 55432:5432 postgres:16-alpine

# OpenTelemetry Collector, for OpenTelemetryObservability
podman run -d --name xai-otel-collector --network xai-net `
    -p 4317:4317 -p 4318:4318 `
    -v "${PWD}/.tmp-otel/collector-config.yaml:/etc/otelcol/config.yaml:Z" `
    docker.io/otel/opentelemetry-collector:latest --config=/etc/otelcol/config.yaml
```

Self-hosted Langfuse needs its own multi-service stack (Postgres, ClickHouse,
Redis, MinIO, plus the `langfuse-web`/`langfuse-worker` services). Clone
[`langfuse/langfuse`](https://github.com/langfuse/langfuse) and start its
`docker-compose.yml` with `podman compose up -d`, then create a project and
API key either through the web UI at `http://localhost:3000` or by setting
`LANGFUSE_INIT_*` environment variables on `langfuse-web` before first boot
(see the [Langfuse self-hosting docs](https://langfuse.com/self-hosting)).

With the containers running:

```powershell
$env:XAI_TEST_POSTGRES_DSN = "postgresql://postgres:xai_test@localhost:55432/xai"
$env:XAI_TEST_OTEL_ENDPOINT = "http://localhost:4318"
$env:XAI_TEST_LANGFUSE_HOST = "http://localhost:3000"
$env:XAI_TEST_LANGFUSE_PUBLIC_KEY = "<project public key>"
$env:XAI_TEST_LANGFUSE_SECRET_KEY = "<project secret key>"

uv sync --extra postgres --extra otel --extra langfuse --group dev
uv run pytest -m "live or postgres"
```

Each suite proves ingestion, not just that a call did not raise: the Postgres
tests read rows back through `parents()`/`children()`/`lineage()`, the
OpenTelemetry test forces a real export and asserts the collector accepted
it, and the Langfuse test polls `GET /api/public/v2/observations` (the
events-only API Langfuse v4 self-hosted deployments serve) until the emitted
observations are visible — the same data the Langfuse **Tracing** UI page
renders. Because these tests write to a real, persistent server, they
generate their own unique identifiers (or truncate their own scratch table)
so repeated runs stay deterministic.

On Windows, `psycopg`'s async connection pool requires a selector-based
event loop; `test_postgres_live.py` switches to
`asyncio.WindowsSelectorEventLoopPolicy()` for its own process because the
default `ProactorEventLoop` cannot host it.

## Common mistakes

Do not use production secrets as fixtures, call a trace presence “quality,” or
accept a green graph test when export and policy paths were not exercised.
