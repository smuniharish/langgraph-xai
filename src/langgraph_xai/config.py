"""Programmatic, instance-scoped runtime configuration."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from .core.models import CaptureMode, FailureMode


class XAIConfig(BaseModel):
    """Configuration owned by one runtime instance.

    ``XAIConfig`` is passed once to `XAIRuntime` at construction time and is
    immutable (``frozen=True``): to change a setting, build a new ``XAIConfig``
    and a new ``XAIRuntime``. Providers and credentials (storage, observability,
    attribution, explanation, policy) are injected separately through
    `XAIRuntime.register`, never through this object, and ``XAIConfig`` never
    reads environment variables — so two runtimes in one process (one per
    tenant, or one per test) can never share configuration by accident.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    capture_state: CaptureMode = Field(
        default=CaptureMode.DELTA,
        description=(
            "How much of a node's state change is recorded. `DELTA` (default) "
            "records only keys whose value changed. `FULL` records every key "
            "present before or after the node, even if unchanged. `SELECTIVE` "
            "records only the changed keys named in `capture_fields`. `CUSTOM` "
            "delegates selection to the `custom_state_capture` callable passed "
            "to `XAIRuntime`. `NONE` disables state-transition capture."
        ),
    )
    capture_fields: frozenset[str] = Field(
        default=frozenset(),
        description=(
            "State keys recorded when `capture_state` is `SELECTIVE`; ignored "
            "otherwise. The empty default means `SELECTIVE` records nothing "
            "until fields are named."
        ),
    )
    capture_checkpoints: bool = Field(
        default=True,
        description=(
            "Whether instrumented calls of a graph compiled with a checkpointer, "
            "and given a `thread_id`, read the thread's state to link the run to "
            "LangGraph checkpoints: the checkpoint each run wrote last, the "
            "checkpoint a resumed run continued from (with "
            "`Execution.continuation_of` naming the run that wrote it), and "
            "static breakpoints. Each call costs one state read, plus one more "
            "when the input is `None` or a `Command`. Set `False` to skip the "
            "reads; interrupts are still recorded."
        ),
    )
    failure_mode: FailureMode = Field(
        default=FailureMode.FAIL_OPEN,
        description=(
            "What happens when an instrumentation operation fails (a storage "
            "write raises, an exporter times out, a policy provider errors). "
            "`FAIL_OPEN` (default) records the error in `XAIRuntime.errors` and "
            "lets the application continue. `FAIL_CLOSED` re-raises it as "
            "`XAIInstrumentationError`, including from inside an instrumented "
            "graph call. `STRICT` behaves like `FAIL_CLOSED` and also refuses to "
            "drop records silently: semantic artifacts (evidence, decisions, "
            "memory references) require at least one registered plugin, and "
            "execution records require a `ProvenanceStore` or an "
            "`ObservabilityProvider`."
        ),
    )
    llm_explanation_enabled: bool = Field(
        default=False,
        description=(
            "Whether an `ExplanationEngine` with `requires_llm = True` may run. "
            "When `False` (default), `XAIRuntime.explain` raises "
            "`XAIInstrumentationError` before any policy evaluation, attribution, "
            "or model call happens. The default `StructuredExplanationEngine` "
            "never calls a model and is unaffected by this flag."
        ),
    )
    max_concurrency: int = Field(
        default=32,
        ge=1,
        description=(
            "Maximum number of instrumentation operations (store writes, event "
            "emission, policy evaluation, plugin dispatch) in flight at once "
            "across every thread and event loop using this runtime. Raise it "
            "when the backend sustains more concurrent writes; lower it to bound "
            "load on a rate-limited backend."
        ),
    )
    operation_timeout_seconds: float = Field(
        default=10.0,
        gt=0,
        description=(
            "Upper bound, in seconds, for one instrumentation operation, "
            "including time spent waiting for a `max_concurrency` slot. An "
            "operation that exceeds it fails with `TimeoutError` and is handled "
            "according to `failure_mode`, so a slow provider cannot stall a "
            "graph run indefinitely."
        ),
    )
