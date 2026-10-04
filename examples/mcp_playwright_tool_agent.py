"""Capture tool calls served by a Model Context Protocol (MCP) server.

The Playwright MCP server is started over stdio and its tools are loaded with
``langchain-mcp-adapters``. To LangChain they are ordinary tools, so an agent built
with ``create_agent`` and wrapped with ``XAIRuntime.instrument`` has every MCP tool call
recorded, with its name, status, latency, and the model's tool-call ID.

Requires Node.js (for ``npx``), a browser for Playwright (Chrome by default; set
``PLAYWRIGHT_MCP_BROWSER``, e.g. to ``msedge``, to use another), the ``examples``
dependency group, and ``OPENAI_API_KEY`` (optionally ``OPENAI_BASE_URL`` and
``OPENAI_MODEL``).

Run with:

    uv run --group examples --extra llm-openai python examples/mcp_playwright_tool_agent.py
"""

import asyncio
import os
import shutil

from _shared import chat_model, show
from langchain.agents import create_agent
from langchain_mcp_adapters.client import MultiServerMCPClient

from langgraph_xai import XAIRuntime


async def main() -> None:
    npx = shutil.which("npx")
    if npx is None:
        raise SystemExit("Node.js is required: npx was not found on PATH.")
    arguments = ["-y", "@playwright/mcp@latest", "--headless", "--isolated"]
    if browser := os.getenv("PLAYWRIGHT_MCP_BROWSER"):
        arguments += ["--browser", browser]
    client = MultiServerMCPClient(
        {"playwright": {"command": npx, "args": arguments, "transport": "stdio"}}
    )
    tools = await client.get_tools()
    print(f"Loaded {len(tools)} MCP tools, e.g. {[item.name for item in tools[:4]]}")

    xai = XAIRuntime(graph_id="mcp-browser-agent")
    task = (
        "Use the browser tools to open https://example.com and report only the exact "
        "page title you observed."
    )
    async with chat_model() as model:
        agent = create_agent(model, tools)
        with xai.collect_runs() as runs:
            result = await xai.instrument(agent).ainvoke(
                {"messages": [{"role": "user", "content": task}]}
            )
    (run,) = runs

    print(f"Agent: {result['messages'][-1].content}")
    show(
        "Captured MCP tool calls",
        [
            {
                "tool": item.tool_name,
                "status": item.status,
                "tool_call_id": item.tool_call_id,
                "latency_ms": round(item.latency_ms or 0.0, 1),
            }
            for item in run.execution.tools
        ],
    )


if __name__ == "__main__":
    asyncio.run(main())
