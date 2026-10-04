# Plugins

Plugins receive every semantic record (evidence, decisions, memory references,
and anything passed to `record_artifact`) as it is created. See
[Extensibility](../architecture/plugins.md#plugins) for an example.

```python
from langgraph_xai import XAIRuntime

xai = XAIRuntime(plugins=(MyArchive(),))
```

::: langgraph_xai.plugins.base.XAIPlugin

::: langgraph_xai.plugins.manager.PluginManager
