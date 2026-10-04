# deepagents

[`deepagents`](https://github.com/langchain-ai/deepagents) adds planning,
filesystem, and sub-agent middleware on top of `create_agent`. The result is
still a compiled LangGraph graph, so the same `xai.instrument` call captures the
whole run. Source:
[`examples/deepagents_agent.py`](https://github.com/smuniharish/langgraph-xai/blob/master/examples/deepagents_agent.py).

```bash
export OPENAI_API_KEY=...
uv run --group examples python examples/deepagents_agent.py
```

## The agent

```python
@tool
def word_count(text: str) -> int:
    """Count the words in a piece of text."""
    return len(text.split())


agent = create_deep_agent(
    model=chat_model(),
    tools=[word_count],
    system_prompt=(
        "You are a concise research assistant. Use the word_count tool on any text "
        "you are given, then report the count."
    ),
)

with xai.collect_runs() as runs:
    result = await xai.instrument(agent).ainvoke(
        {
            "messages": [
                {
                    "role": "user",
                    "content": "Count the words in: explainability makes agents accountable.",
                }
            ]
        }
    )
```

## Output

Real output from a live OpenAI-compatible chat model:

```text
Agent: 4 words.

--- Captured for one run ---
{
  "run_id": "7ea8967e-d86c-4eec-b612-0f60571a1c8b",
  "status": "completed",
  "nodes": {
    "PatchToolCallsMiddleware.before_agent": 1,
    "model": 2,
    "tools": 1
  },
  "tools": [
    "word_count: succeeded"
  ],
  "state_transitions": 3
}
```

## What to notice

- **Middleware nodes are real graph nodes.** `PatchToolCallsMiddleware.before_agent`
  is a node that deepagents adds. It is recorded like any other node.
- **The model ran twice.** It requested the tool, then answered. Each model turn
  is a node execution, and the tool call between them is a tool execution.
- **No framework-specific code.** Sub-agents spawned by deepagents run inside
  the same call, so their nodes and tools join the same run.
