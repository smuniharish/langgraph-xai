# How to run multi-agent graphs with correlation

**Goal:** confirm that every artifact produced by a multi-agent (or
multi-subgraph) run — including retried tool calls inside any one agent —
correlates under a single `run_id`/`trace_id`.

## Steps

1. Build a supervisor graph composing two or more agent-like nodes (or
   compiled subgraphs) as usual — nothing xgraph-specific here.

2. Instrument the **top-level** compiled graph once:

   ```python
   runtime = XAIRuntime(graph_id="supervisor-researcher-writer")
   instrumented = runtime.instrument(graph)
   ```

3. If a node calls a `Runnable`/tool directly (rather than via a `ToolNode`),
   make sure the node function accepts and forwards `config` — otherwise
   xgraph's callback handler never sees that call:

   ```python
   def researcher(state, config: RunnableConfig):
       return {"research": retrying_tool.invoke({"symbol": state["symbol"]}, config=config)}
   ```

4. Optionally pin a `trace_id` for easier correlation in external systems:

   ```python
   await instrumented.ainvoke(
       {"symbol": "ACME"},
       config={"metadata": {"trace_id": "my-external-correlation-id"}},
   )
   ```

5. Verify correlation by querying the store and checking the distinct
   `run_id`/`trace_id` sets:

   ```python
   run_ids = {str(r.context.run_id) for r in records}
   assert len(run_ids) == 1
   ```

## Full example and real captured output

See [examples: multi-agent correlation, retries, and failures](../examples/multi-agent-retry.md):
a real supervisor graph where a tool fails once and recovers via
`.with_retry()`. Both the failed attempt and the succeeded retry are
captured as distinct `ToolExecution` records, under the same `run_id`, so a
transient failure is never silently lost even though the overall run
completes successfully.
