# Configuration

Core behavior is configured explicitly on each `XAIRuntime` instance. It does
not read process-wide `XAI_*` environment variables, and there is no global
enable/disable switch.

```python
from langgraph_xai import CaptureMode, FailureMode, XAIConfig, XAIRuntime

runtime = XAIRuntime(
    config=XAIConfig(
        capture_state=CaptureMode.DELTA,
        failure_mode=FailureMode.FAIL_OPEN,
        llm_explanation_enabled=False,
        max_concurrency=32,
    )
)
```

This makes behavior deterministic when one process hosts multiple applications,
tenants, graphs, or runtime instances. Providers are injected into the runtime
rather than selected by string configuration.

LLM explanation is disabled by default. Enabling it also requires an explicitly
injected compatible LangChain model; it never activates merely because provider
credentials exist in the environment.

Optional provider SDKs may use their conventional environment variables for
credentials and endpoints, including `LANGSMITH_*`, `LANGFUSE_*`, and
`OTEL_EXPORTER_OTLP_ENDPOINT`. A PostgreSQL store may similarly receive a DSN
loaded by the host application. `langgraph-xai` does not load these values into
its core configuration or store credentials in canonical artifacts.

