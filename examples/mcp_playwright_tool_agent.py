"""Real MCP tool-call capture, verified against a live Playwright MCP server and a live LLM.

This is not a mock. It:

1. launches a real Playwright MCP server (``npx @playwright/mcp``) over stdio,
2. loads its tools through ``langchain-mcp-adapters`` as ordinary LangChain tools,
3. builds a LangGraph ReAct agent bound to a real OpenAI-compatible model, and
4. instruments the compiled agent graph with :class:`XAIRuntime` **without any
   MCP-specific code in xgraph**.

Because MCP tools surface through LangChain's standard tool-calling and
callback interfaces, ``XAIRuntime.instrument`` captures them exactly like any
other tool: no ``isinstance`` branching, no MCP adapter inside xgraph itself.
That is the architectural point this example exists to prove.

Run with:

    $env:EXPLABS_API_KEY = "<set outside source control>"
    uv run --group examples --extra llm-openai python examples/mcp_playwright_tool_agent.py
"""

import asyncio
import json
import os

from langchain.agents import create_agent
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_openai import ChatOpenAI

from langgraph_xai import Execution, XAIRuntime
from langgraph_xai.core import XAIEvent
from langgraph_xai.core.protocols import ProvenanceStore
from langgraph_xai.storage.memory import StoreFilter


async def main() -> None:
    model = ChatOpenAI(
        base_url="https://api.experientiallabs.ai/v1",
        api_key=os.environ["EXPLABS_API_KEY"],
        model="gpt-5.6-luna",
    )

    mcp_client = MultiServerMCPClient(
        {
            "playwright": {
                "command": "C:\\Program Files\\nodejs\\npx.cmd",
                "args": ["-y", "@playwright/mcp@latest", "--headless", "--isolated"],
                "transport": "stdio",
            }
        }
    )
    tools = await mcp_client.get_tools()
    print(f"Loaded {len(tools)} real MCP tools: {[t.name for t in tools][:8]} ...")

    agent = create_agent(model, tools)

    runtime = XAIRuntime(
        application_id="docs-verification",
        tenant_id="xgraph-dev",
        graph_id="mcp-playwright-agent",
    )
    instrumented = runtime.instrument(agent)

    task = (
        "Use the browser tools to navigate to https://example.com and take a "
        "page snapshot or read its title, then report only the exact page "
        "title you observed, nothing else."
    )
    result = await instrumented.ainvoke(
        {"messages": [{"role": "user", "content": task}]},
        config={"metadata": {"trace_id": "mcp-playwright-demo-0001"}},
    )

    final_message = result["messages"][-1].content
    print("\n--- Agent final answer (real LLM + real browser) ---")
    print(final_message)

    tool_calls = [
        message.tool_calls for message in result["messages"] if getattr(message, "tool_calls", None)
    ]
    print("\n--- Real tool calls captured in message history ---")
    print(json.dumps(tool_calls, indent=2, default=str))

    # Correlate captured provenance: every canonical record for this run shares
    # one run_id/trace_id, no matter how many MCP tool calls happened inside it.
    store = runtime.registry.get(ProvenanceStore)
    context = runtime.context_from_config({"metadata": {"trace_id": "mcp-playwright-demo-0001"}})
    records = [
        record
        async for record in store.query(
            StoreFilter(
                application_id=context.application_id,
                tenant_id=context.tenant_id,
                limit=200,
            )
        )
    ]
    print(f"\n--- {len(records)} canonical records captured for this run ---")
    for record in records:
        kind = "Execution" if isinstance(record, Execution) else type(record).__name__
        event_kind = record.event_type if isinstance(record, XAIEvent) else kind
        print(
            json.dumps(
                {
                    "kind": str(event_kind),
                    "run_id": str(record.context.run_id),
                    "trace_id": record.context.trace_id,
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    asyncio.run(main())
