# How to integrate MCP tools

**Goal:** get full explainability capture for tools served by any [Model
Context Protocol](https://modelcontextprotocol.io/) server, with no
MCP-specific xgraph code — because there isn't any.

## Steps

1. Load MCP tools with an independent, general-purpose adapter (xgraph does
   not ship or require one):

   ```python
   from langchain_mcp_adapters.client import MultiServerMCPClient

   async with MultiServerMCPClient(
       {
           "playwright": {
               "command": "npx",
               "args": ["-y", "@playwright/mcp@latest", "--headless", "--isolated"],
               "transport": "stdio",
           }
       }
   ) as client:
       tools = await client.get_tools()
   ```

2. Build a normal LangChain/LangGraph agent with those tools:

   ```python
   from langchain.agents import create_agent

   agent = create_agent(model=model, tools=tools)
   ```

3. Instrument the compiled agent graph exactly as you would any other graph:

   ```python
   runtime = XAIRuntime(graph_id="mcp-playwright-agent")
   instrumented = runtime.instrument(agent)
   result = await instrumented.ainvoke({"messages": [...]})
   ```

That's it — every MCP tool call is captured as an ordinary `ToolExecution`
record (real tool name, real latency, real `tool_call_id`), because from
LangChain's perspective an MCP tool and a plain `@tool`-decorated function are
both just `BaseTool` invocations dispatched through the same callback
surface.

## Full example and real captured output

See [examples: MCP tools](../examples/mcp-tools.md) for the full runnable
script (a real Playwright MCP server, a real LLM, a real browsing task) and
the 10 real canonical records it captured, all sharing one `run_id`.

## Why this is the strongest proof of the "no isinstance branching" claim

MCP was not designed into xgraph's instrumentation layer up front — it works
because `InstrumentedGraph` only depends on the public LangChain
Runnable/callback contract, never on a specific tool provider. See
[ADR-011](../architecture/decisions.md#adr-011-the-runtime-orchestrates-provider-neutral-capability-interfaces).
