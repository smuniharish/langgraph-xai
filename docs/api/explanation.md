# Explanation engines

Engines that render an `Explanation` from a policy-filtered
`ExplanationContext`. The structured engine is the default. See
[Explanations](../concepts/explanations.md) and
[LLM-phrased explanations](../how-to/llm-explanations.md).

```python
from langgraph_xai import ExplanationEngine, LLMExplanationEngine, XAIConfig, XAIRuntime

xai = XAIRuntime(XAIConfig(llm_explanation_enabled=True))
xai.register(ExplanationEngine, LLMExplanationEngine(chat_model, enabled=True))
```

::: langgraph_xai.explanation.engines.StructuredExplanationEngine

::: langgraph_xai.explanation.engines.LLMExplanationEngine

::: langgraph_xai.explanation.engines.ExplanationDraft
