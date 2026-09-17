# Explanation engines

An `ExplanationEngine` assembles a final `Explanation` from a
policy-filtered `ExplanationContext`. It is the last step of
`runtime.explain(...)`.

## `StructuredExplanationEngine` (default)

Renders reasons/factors/evidence directly from canonical fields —
deterministic, free, and requires no LLM (`requires_llm = False`). See
[Concepts: Explanations](../concepts/explanations.md) for a full real
output.

## `LLMExplanationEngine` (opt-in)

Phrases an *already-assembled* structured explanation through an injected
LangChain chat model or runnable — it never invents facts, since its output
is validated against a strict schema before use:

```python
from langchain_openai import ChatOpenAI
from langgraph_xai.explanation import LLMExplanationEngine
from langgraph_xai.core.protocols import ExplanationEngine
from langgraph_xai import XAIConfig

runtime = XAIRuntime(config=XAIConfig(llm_explanation_enabled=True))
runtime.register(
    ExplanationEngine,
    LLMExplanationEngine(ChatOpenAI(model="gpt-4o-mini"), enabled=True, timeout=30.0),
)
```

Requires `XAIConfig.llm_explanation_enabled=True` (checked before every
call) *and* `enabled=True` on the engine itself — two independent switches,
so enabling the config flag alone is not enough to start making live model
calls. The model's raw response is parsed into an `ExplanationDraft` — a
strict, three-field (`summary`, `reasons`, `disclosure`) schema with
`extra="forbid"` — before being merged back into the structured result;
policy-withheld fields (e.g. `reasons` when denied) are restored from the
structured engine's output regardless of what the model returned. See
[Enable live LLM explanations](../how-to/llm-explanations.md) for the full
walkthrough and [failure-mode interaction](../how-to/failure-modes.md).

## Reference

::: langgraph_xai.explanation.StructuredExplanationEngine

::: langgraph_xai.explanation.LLMExplanationEngine

::: langgraph_xai.explanation.ExplanationDraft
