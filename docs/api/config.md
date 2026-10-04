# Configuration

`XAIConfig` holds the settings of one runtime. It is immutable and never reads
environment variables. See [Configuration](../getting-started/configuration.md)
for guidance and real examples of each capture mode.

```python
from langgraph_xai import CaptureMode, FailureMode, XAIConfig, XAIRuntime

xai = XAIRuntime(XAIConfig(capture_state=CaptureMode.DELTA, failure_mode=FailureMode.FAIL_CLOSED))
```

::: langgraph_xai.config.XAIConfig
