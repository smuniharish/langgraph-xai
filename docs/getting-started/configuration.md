# Configuration constraints

Configuration is per runtime. There is no process-wide `XAI_*` environment
configuration and no global enable/disable switch.

## Kid-level view

Each graph gets its own labeled control panel. Turning a knob for one graph
must not secretly turn it for another.

## Production view

Pass `XAIConfig` to each `XAIRuntime`; inject model, storage, exporter, and
policy implementations rather than selecting them by string name. Optional
SDKs may read their own documented credential variables, but the core does not
read them or copy credentials into artifacts.

| Setting | Guidance |
| --- | --- |
| Capture mode | Prefer the smallest useful delta or explicit event set. |
| Failure mode | Choose and test fail-open or fail-closed per boundary. |
| LLM explanation | Off by default; requires an explicitly injected model. |
| Concurrency | Bound work per runtime and account for exporter limits. |
| Secrets | Keep in the host secret manager, never canonical artifacts. |

## Common mistakes

Do not add `XAI_*` variables, a global singleton, or an implicit provider
factory. Do not confuse `LANGSMITH_*`, `LANGFUSE_*`, or OTLP endpoint
variables used by optional SDKs with core configuration.

