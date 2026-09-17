# deepagents (real deep-agent + real LLM)

[`deepagents`](https://github.com/langchain-ai/deepagents) builds a
"deep agent" — planning, filesystem, and subagent middleware layered on top
of `langchain.agents.create_agent` — but the result it returns is still an
ordinary compiled LangGraph `StateGraph`. This page proves xgraph needs zero
deepagents-specific code to instrument one.

Source: [`examples/deepagents_realtime.py`](https://github.com/samamuniharish/langgraph-xai/blob/main/examples/deepagents_realtime.py).

```python
agent = create_deep_agent(
    model=ChatOpenAI(
        base_url="https://api.experientiallabs.ai/v1",
        api_key=os.environ["EXPLABS_API_KEY"],
        model="gpt-5.6-luna",
    ),
    tools=[word_count],
    system_prompt="You are a concise research assistant. Use the word_count "
    "tool on any text you are given, then report the count.",
)

runtime = XAIRuntime(graph_id="deepagents-word-counter")
instrumented = runtime.instrument(agent)  # <- the entire integration
result = await instrumented.ainvoke({"messages": [...]})
```

```bash
uv run --system-certs python examples/deepagents_realtime.py
```

## Real captured output

```text
--- Final agent message ---
4 words.

--- 8 records captured across one deepagents run ---
Execution
execution.started
state.transition
state.transition
tool.execution
state.transition
state.transition
execution.completed

Distinct run_ids: {'4dafd1f1-3430-44ef-ba22-350dd481b62e'}
```

A single `run_id` covers the deep agent's internal planning/state middleware
*and* its real tool call (`word_count`) — confirmed by the script's own
assertion, not just visual inspection:

```python
assert len(run_ids) == 1, "the whole deep-agent run (including any subagent work) must correlate"
```

## Why this matters

deepagents did not exist when xgraph's instrumentation layer was designed.
It works anyway, because `InstrumentedGraph` only depends on the public
LangChain Runnable/callback surface — not on any framework-specific
internals — which is the same guarantee demonstrated for MCP tools in
[MCP tools](mcp-tools.md).
