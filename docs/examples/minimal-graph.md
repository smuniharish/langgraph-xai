# Minimal graph

The smallest useful integration: wrap a compiled graph, run it, and read what
was captured. Source:
[`examples/minimal_langgraph.py`](https://github.com/smuniharish/langgraph-xai/blob/master/examples/minimal_langgraph.py).

```python
class State(TypedDict, total=False):
    question: str
    answer: str


def answer(state: State) -> State:
    return {"answer": f"Echo: {state['question']}"}


builder = StateGraph(State)
builder.add_node("answer", answer)
builder.add_edge(START, "answer")
builder.add_edge("answer", END)

xai = XAIRuntime(graph_id="minimal")
graph = xai.instrument(builder.compile())

with xai.collect_runs() as runs:
    result = await graph.ainvoke({"question": "Why?"})

execution = runs[0].execution
print(result)
print(f"status={execution.status} nodes={[node.node_id for node in execution.nodes]}")
for transition in execution.state_transitions:
    for change in transition.changes:
        print(f"{transition.node_id}: {change.path} {change.before!r} -> {change.after!r}")
```

Run it:

```bash
uv run python examples/minimal_langgraph.py
```

Output:

```text
{'question': 'Why?', 'answer': 'Echo: Why?'}
status=completed nodes=['answer']
answer: answer None -> 'Echo: Why?'
```

## What to notice

- The graph's result is exactly what the uninstrumented graph returns.
- The run recorded the node, its status, and the state it changed, with no
  explainability code inside the node.
- The default `DELTA` capture recorded only `answer`, the key that changed.
  `question` was untouched, so it was not recorded.

Next: record *why* the graph decided something in the
[fraud review example](full-explanation.md).
