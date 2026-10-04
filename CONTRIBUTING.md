# Contributing

Thank you for improving `langgraph-xai`. Contributions should keep its focus:
an explainability layer for LangGraph, not a graph runtime or an observability
platform.

## Before opening a change

1. Read the [architecture overview](docs/architecture/overview.md).
2. Open an issue first for changes to the public API, the canonical schema,
   disclosure behavior, or an integration.
3. Keep each change focused, with tests and documentation for anything a user
   can observe.

## Development setup

Python 3.12 or later and [uv](https://docs.astral.sh/uv/) are required.

```bash
uv sync --all-extras --all-groups
uv run ruff check .
uv run ruff format --check .
uv run pyrefly check
uv run pytest --cov=langgraph_xai --cov-branch
```

The default test run needs no services or API keys, and coverage is kept at
100%. Live suites for PostgreSQL, OpenTelemetry, Langfuse, and LLM endpoints
run when their environment variables are set; see
[Testing](docs/development/testing.md).

Never commit credentials, local environments, or generated reports.

## Documentation and diagrams

```bash
uv run mkdocs build --strict
```

Diagrams are Mermaid sources under [`diagrams/`](diagrams), rendered to PNG
with Mermaid CLI 12.0.0. Install it globally; it needs Node.js 22.13 or later.
`--allow-scripts=puppeteer` lets Puppeteer download the headless browser the
CLI renders with:

```bash
npm install --global --allow-scripts=puppeteer @mermaid-js/mermaid-cli@12.0.0
node scripts/render-diagrams.mjs
node scripts/render-diagrams.mjs --check
```

Commit a changed diagram source together with its rendered image and the
updated `docs/assets/diagrams/manifest.json`.

## Pull requests

- Describe the user-visible impact, including any effect on what is captured,
  stored, exported, or disclosed.
- Add or update tests for every behavior change.
- Update the affected pages under [`docs/`](docs) and the
  [changelog](CHANGELOG.md).
- Make sure formatting, lint, type checks, tests, the strict docs build, and
  the diagram check pass.

## Releases

Releases follow [semantic versioning](https://semver.org/). To publish one:

1. Set the version in `pyproject.toml` and the Agent Skill's
   `metadata.version` in `langgraph-xai-skills/skills/langgraph-xai/SKILL.md`,
   then run `uv lock`. A test fails until the two versions match.
2. Move the changelog entries under a heading with the version and date.
3. Merge to `master`, then publish a GitHub release whose tag is the version
   with a `v` prefix, such as `v1.0.0`.

The [release workflow](.github/workflows/release.yml) checks that the tag
matches the version, builds and checks the distributions, and publishes them
to PyPI with trusted publishing, so no API token is stored in the repository.
Before the first release, a maintainer adds the workflow as a trusted
publisher in the PyPI project settings (repository
`smuniharish/langgraph-xai`, workflow `release.yml`, environment `pypi`).

## Security reports

Do not report vulnerabilities in public issues. Follow [SECURITY.md](SECURITY.md).
