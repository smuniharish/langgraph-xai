# Examples

Every example on this page is a real, runnable script under
[`examples/`](https://github.com/samamuniharish/langgraph-xai/tree/main/examples),
and every code block and output block quoted from it is copy-pasted from an
actual run — not hand-written or idealized. Run any of them yourself with
`uv run python examples/<name>.py` (some require `EXPLABS_API_KEY` for a real
LLM call, noted per page).

- [Minimal graph](minimal-graph.md) — the smallest possible instrumented
  graph.
- [Full explanation output](full-explanation.md) — the complete, real
  `Explanation` JSON for a banking decision.
- [Disclosure-policy matrix](disclosure-matrix.md) — 16 real permutations of
  policy x audience x explanation engine, including a real LLM.
- [Human-in-the-loop interrupts](interrupt-hitl.md) — a real
  `interrupt()`/`Command(resume=...)` cycle, captured as first-class
  artifacts.
- [MCP tools (Playwright)](mcp-tools.md) — a real MCP tool server, a real
  LLM agent, zero MCP-specific xgraph code.
- [deepagents](deepagents.md) — a real `deepagents` deep agent, instrumented
  with zero deepagents-specific xgraph code.
- [Multi-agent correlation and retries](multi-agent-retry.md) — a real
  supervisor graph with a transiently-failing, retried tool call.
- [Policy-filtered export](policy-export.md) — allow, redact, and
  reference-only disclosure at an export boundary.

## Best practice

Start with minimal capture, deterministic fixtures, and no provider export.
Add one adapter at a time and verify its disclosure and failure behavior —
see [How to test disclosure policies](../how-to/disclosure-policies.md) and
[How to configure failure modes](../how-to/failure-modes.md).

