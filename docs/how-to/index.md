# How-to guides

Task-oriented guides. Each one links to a real, runnable example and the
real output it produced — not a hypothetical snippet. If you're looking for
*why* something is designed the way it is, see
[Concepts](../concepts/index.md) and [Architecture](../architecture/overview.md)
instead.

- [Handle human-in-the-loop interrupts](interrupts.md) — capture a real
  LangGraph `interrupt()`/`Command(resume=...)` pause/resume cycle as
  first-class artifacts.
- [Integrate MCP tools](mcp-tools.md) — instrument a real Playwright MCP
  server's tools with zero MCP-specific code.
- [Run multi-agent graphs with correlation](multi-agent.md) — verify that a
  supervisor + subagent graph, including retried tool calls, all correlate
  under one `run_id`.
- [Test disclosure policies](disclosure-policies.md) — exercise a real
  permutation matrix of policies x audiences x explanation engines before
  trusting a disclosure boundary in production.
- [Enable live LLM explanations](llm-explanations.md) — turn on the
  LLM-backed explanation engine safely, including the schema-validation
  boundary that rejects hallucinated fields.
- [Configure failure modes](failure-modes.md) — choose between
  `fail_open`, `fail_closed`, and `strict` for xgraph's own instrumentation
  failures.
