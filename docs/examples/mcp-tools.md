# MCP tools

An agent uses browser tools served by the
[Playwright MCP server](https://github.com/microsoft/playwright-mcp) over stdio.
The tools are loaded with `langchain-mcp-adapters`, so they are ordinary
LangChain tools, and every call is captured. Source:
[`examples/mcp_playwright_tool_agent.py`](https://github.com/smuniharish/langgraph-xai/blob/master/examples/mcp_playwright_tool_agent.py).

Requires Node.js (for `npx`) and a browser for Playwright. Chrome is used by
default; set `PLAYWRIGHT_MCP_BROWSER=msedge` (or another supported browser) to
use a different one.

```bash
export OPENAI_API_KEY=...
uv run --group examples python examples/mcp_playwright_tool_agent.py
```

## The agent

```python
client = MultiServerMCPClient(
    {"playwright": {"command": npx, "args": arguments, "transport": "stdio"}}
)
tools = await client.get_tools()

xai = XAIRuntime(graph_id="mcp-browser-agent")
agent = create_agent(chat_model(), tools)
with xai.collect_runs() as runs:
    result = await xai.instrument(agent).ainvoke({"messages": [{"role": "user", "content": task}]})
```

## Output

Real output from a live OpenAI-compatible chat model and the Playwright MCP
server:

```text
Loaded 25 MCP tools, e.g. ['browser_close', 'browser_resize', 'browser_console_messages', 'browser_handle_dialog']
Agent: Example Domain

--- Captured MCP tool calls ---
[
  {
    "tool": "browser_navigate",
    "status": "succeeded",
    "tool_call_id": "call_civ6Cs9tAhbLtotMzjcJGLfw",
    "latency_ms": 9535.6
  }
]
```

## What to notice

- **MCP needs no special support.** The tool call is recorded with its MCP tool
  name, outcome, latency, and the model's `tool_call_id`.
- **Page content is not recorded.** Tool arguments and results stay out of the
  record. Record what a result showed as evidence when a decision relies on it;
  see [Capture MCP tool calls](../how-to/mcp-tools.md).
