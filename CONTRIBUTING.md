# Contributing

Thank you for improving `langgraph-xai`. Contributions should preserve its
provider-neutral explainability focus and avoid broadening the project into a
graph runtime or observability platform.

## Before opening a change

1. Read the [architecture overview](docs/architecture/overview.md) and
   [architecture decisions](docs/architecture/decisions.md).
2. Discuss material API, schema, disclosure, or adapter changes in an issue.
3. Keep a change focused; include tests and documentation for public behavior.

## Development

```bash
uv sync
uv run ruff check .
uv run ruff format --check .
uv run pyrefly check
uv run pytest
```

Use Python 3.12 or later. Do not commit credentials, local environments, or
generated build output.

## Documentation and diagrams

Build the documentation with the docs dependency group:

```bash
uv sync --group docs
uv run mkdocs build --strict
```

Architecture diagrams are Mermaid source files under
[`diagrams/`](diagrams). Render their PNG counterparts with:

```bash
npm install --global @mermaid-js/mermaid-cli@11.17.0
node scripts/render-diagrams.mjs
node scripts/render-diagrams.mjs --check
```

Commit a changed Mermaid source and its rendered PNG together when the diagram
is published in the site.

## Pull request expectations

- Explain the user-visible and architectural impact.
- Add or update tests for behavior changes.
- Update relevant pages under [`docs/`](docs), the decision log, or security
  guidance.
- Identify data capture, retention, disclosure, or external export effects.
- Ensure format, lint, types, tests, diagram rendering, and strict docs build
  pass when applicable.

## Decision records

Add an `ADL-###` entry for a durable architectural decision. State the status,
decision, and justification; supersede rather than rewrite an accepted
decision.

## Security reports

Do not file sensitive vulnerabilities in public issues. Follow
[SECURITY.md](SECURITY.md).
