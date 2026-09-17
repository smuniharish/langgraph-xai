# How to enable live LLM explanations

**Goal:** turn on `LLMExplanationEngine` safely — understanding exactly what
boundary protects you from a model hallucinating fields you didn't ask for.

## Steps

1. `LLMExplanationEngine` is disabled by default, and doubly so: it also
   requires `XAIConfig.llm_explanation_enabled=True` at the runtime level (a
   deliberate two-key safety interlock).

   ```python
   runtime = XAIRuntime(config=XAIConfig(llm_explanation_enabled=True))
   ```

2. Inject any LangChain chat model or `Runnable[str, str]`:

   ```python
   model = ChatOpenAI(base_url=..., api_key=..., model="gpt-5.6-luna")
   engine = LLMExplanationEngine(model=model, enabled=True, timeout=30.0)
   runtime.register(ExplanationEngine, engine)
   ```

3. Call `runtime.explain(context)` as usual — the LLM only ever receives
   already-captured, policy-filtered facts (selected action, factors,
   evidence), never a raw prompt or private model reasoning, and its output
   is parsed against a strict internal schema requiring exactly three fields:
   `summary`, `reasons`, and `disclosure`. Any extra field the model invents
   (for example a `hidden_reasoning` key) is rejected outright, not silently
   accepted.

4. Handle both realistic failure shapes:
   - `asyncio.TimeoutError` if the model doesn't respond within `timeout`
     seconds;
   - `ValueError("LLM explanation output failed schema validation")` if the
     model's JSON doesn't match `ExplanationDraft` (or isn't valid JSON at
     all).

   `runtime.explain(...)` itself applies your configured
   [failure mode](failure-modes.md) around these — a `fail_open` runtime
   returns without raising (see `runtime.errors` for the captured
   exception), while `fail_closed`/`strict` propagate an
   `XAIInstrumentationError`.

## Real evidence this boundary actually holds

- `tests/explanation/test_engines.py::test_llm_explanation_still_rejects_unknown_fields`
  — a real assertion that a smuggled extra field is rejected.
- The [disclosure-policy matrix](../examples/disclosure-matrix.md) ran the
  LLM engine through 8 real permutations against `gpt-5.6-luna`, with real
  latency between 1.7s and 8.2s per call — useful for setting your own
  `timeout`.
- A real, previously-undetected provider quirk (a scalar string instead of a
  JSON array for `disclosure`) was found and fixed this way — see the
  ["Why the LLM engine needed a real fix"](../examples/disclosure-matrix.md#why-the-llm-engine-needed-a-real-fix)
  section.
