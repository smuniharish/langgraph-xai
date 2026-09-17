# Contributing

Read the architecture pages before making material schema, disclosure, or
adapter changes. Keep contributions focused; add tests and documentation for
public behavior.

```bash
uv sync
uv run ruff check .
uv run ruff format --check .
uv run pyrefly check
uv run pytest
```

Install `@mermaid-js/mermaid-cli@11.17.0` globally, then run
`node scripts/render-diagrams.mjs` when a published Mermaid
diagram changes. New durable architecture choices need the next `ADL-###`
record with a status and justification.
