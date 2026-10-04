# Capture MCP tool calls

Tools served by a [Model Context Protocol](https://modelcontextprotocol.io)
server become ordinary LangChain tools through
[`langchain-mcp-adapters`](https://github.com/langchain-ai/langchain-mcp-adapters).
An instrumented graph therefore records every MCP tool call like any other tool,
with no MCP-specific code.

## Load the tools and instrument the agent

```python
from langchain.agents import create_agent
from langchain_mcp_adapters.client import MultiServerMCPClient

client = MultiServerMCPClient(
    {
        "playwright": {
            "command": "npx",
            "args": ["-y", "@playwright/mcp@latest", "--headless", "--isolated"],
            "transport": "stdio",
        }
    }
)
tools = await client.get_tools()

xai = XAIRuntime(graph_id="mcp-browser-agent")
agent = xai.instrument(create_agent(model, tools))

with xai.collect_runs() as runs:
    result = await agent.ainvoke(
        {
            "messages": [
                {"role": "user", "content": "Open https://example.com and report the page title."}
            ]
        }
    )
```

`MultiServerMCPClient` is not a context manager. `get_tools()` returns the
tools, and each call opens a session to the server.

## What is recorded

Real output of the [MCP example](../examples/mcp-tools.md), run against the
Playwright MCP server with a live model:

```text
Loaded 25 MCP tools, e.g. ['browser_close', 'browser_resize', 'browser_console_messages', 'browser_handle_dialog']
Agent: Example Domain
```

```json
[
  {
    "tool": "browser_navigate",
    "status": "succeeded",
    "tool_call_id": "call_civ6Cs9tAhbLtotMzjcJGLfw",
    "latency_ms": 9535.6
  }
]
```

Each call records the MCP tool name, the outcome, the latency, and the model's
`tool_call_id`, so it can be matched to the assistant message that requested
it. A server error records the call as `failed`, and a timeout records it as
`timed_out`.

## Tool results as evidence

Tool arguments and results are not stored, because they often contain page
content or personal data. When a result supports a decision, record what it
showed as [evidence](../concepts/evidence.md), and point back to the call:

```python
await xai.record_evidence(
    EvidenceType.TOOL_RESULT,
    summary="The page title was 'Example Domain'.",
    content_reference=f"tool-call://{tool_call_id}",
)
```

The [create_agent example](../examples/create-agent.md) shows this pattern in
middleware that runs after the model's final answer.
