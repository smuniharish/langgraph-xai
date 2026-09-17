# How to handle human-in-the-loop interrupts

**Goal:** capture a real LangGraph `interrupt()` pause and its later
`Command(resume=...)` continuation as first-class, queryable artifacts
instead of losing the pause entirely.

## Why this needs explicit handling

LangGraph's `interrupt()` does not raise through `ainvoke()`/`invoke()` and
is not visible to the LangChain callback system at all — it returns
*normally* with a `{"__interrupt__": [...]}` key in the output. Naively
instrumented code (anything relying only on callbacks) will record an
interrupted run as a normal `COMPLETED` execution.

## Steps

1. Compile your graph with a checkpointer, as HITL requires one:

   ```python
   graph = builder.compile(checkpointer=InMemorySaver())
   ```

2. Instrument the graph exactly as you would any other graph — no special
   API is needed:

   ```python
   runtime = XAIRuntime(graph_id="wire-transfer-hitl")
   instrumented = runtime.instrument(graph)
   ```

3. Invoke normally. When the graph pauses at `interrupt(...)`, xgraph
   automatically records `ExecutionStatus.INTERRUPTED` plus a
   `HumanInteraction(interaction_type=INTERRUPT, ...)` carrying the real
   interrupt payload:

   ```python
   thread = {"configurable": {"thread_id": "wire-42"}}
   paused = await instrumented.ainvoke({"amount": 9000.0}, thread)
   ```

4. Resume with `Command(resume=...)` on the same thread. xgraph records a
   matching `HumanInteraction(interaction_type=RESUME, ...)` on the
   continuation run:

   ```python
   resumed = await instrumented.ainvoke(Command(resume=True), thread)
   ```

5. Verify what was captured by querying the store directly:

   ```python
   executions = [
       r
       async for r in store.query(
           StoreFilter(
               application_id=context.application_id,
               tenant_id=context.tenant_id,
               item_type=Execution,
           )
       )
   ]
   assert any(e.status == ExecutionStatus.INTERRUPTED for e in executions)
   ```

## Full example and real captured output

See [examples: interrupt / HITL](../examples/interrupt-hitl.md) for the
complete runnable script and its real JSON output, and
`tests/langgraph/test_instrumentation.py::test_interrupt_is_captured_as_interrupted_not_completed`
for the automated regression test.

## Gotcha

`Execution.continuation_of` is **not** populated automatically today —
correlate the paused and resumed runs via `thread_id`/`trace_id` instead. See
the "Known simplification" note on the [interrupt example page](../examples/interrupt-hitl.md).
