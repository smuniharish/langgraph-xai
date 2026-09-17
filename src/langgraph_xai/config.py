"""Programmatic, instance-scoped runtime configuration."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from .core.models import CaptureMode, FailureMode


class XAIConfig(BaseModel):
    """Configuration owned by one runtime instance.

    ``XAIConfig`` is passed once to `XAIRuntime`
    at construction time. It is immutable (``frozen=True``): to change a
    setting, build a new ``XAIConfig`` and a new ``XAIRuntime`` rather than
    mutating one in place. This keeps the runtime's behavior fully
    determined by its constructor arguments, with no hidden mutable state to
    reason about across a long-lived process.

    Provider implementations and credentials (storage, observability,
    attribution, explanation, policy) are injected separately via
    `register`, not through this
    object. ``XAIConfig`` intentionally does not read process-wide
    environment variables — every setting is an explicit constructor
    argument, so two runtimes in the same process (e.g. one per tenant, or
    one per test) can never accidentally share configuration.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    capture_state: CaptureMode = Field(
        default=CaptureMode.DELTA,
        description=(
            "Controls how much of a node's state change is recorded on each "
            "`record_state_delta` call. `FULL` records every key present in "
            "either the before/after state, even if unchanged. `DELTA` "
            "(default) records only keys whose value actually changed — the "
            "right choice for most applications, since it avoids recording "
            "unrelated state on every node. `SELECTIVE` narrows further to "
            "only the changed keys named in `capture_fields` — use this "
            "when a node's state contains fields that must never be recorded "
            "(e.g. secrets, full documents) even if they change. `CUSTOM` "
            "delegates the selection to the `custom_state_capture` callable "
            "passed to `XAIRuntime`, for logic that a static field list "
            "cannot express. `NONE` disables state-transition capture "
            "entirely."
        ),
    )
    capture_fields: frozenset[str] = Field(
        default=frozenset(),
        description=(
            "The set of state keys recorded when `capture_state` is "
            "`SELECTIVE`. Ignored for every other `capture_state` value. "
            "Defaults to an empty set, which means `SELECTIVE` mode records "
            "nothing until you name the fields you want."
        ),
    )
    failure_mode: FailureMode = Field(
        default=FailureMode.FAIL_OPEN,
        description=(
            "What happens when an instrumentation operation itself fails "
            "(a storage write raises, an observability call times out, a "
            "policy provider errors). `FAIL_OPEN` (default) logs the error "
            "internally, makes it available via `XAIRuntime.errors`, and "
            "lets the wrapped LangGraph application continue running "
            "unaffected — the right default for production, since an "
            "explainability failure should never take down the agent it is "
            "observing. `FAIL_CLOSED` and `STRICT` re-raise instrumentation "
            "failures as `XAIInstrumentationError`, and `STRICT` additionally "
            "requires that a real `ProvenanceStore`/`ObservabilityProvider`/"
            "plugin is registered for every artifact kind being recorded — "
            "use one of these in tests or CI to fail loudly instead of "
            "silently under-capturing. See "
            "[Configure failure modes](../how-to/failure-modes.md) for the "
            "full behavior matrix."
        ),
    )
    llm_explanation_enabled: bool = Field(
        default=False,
        description=(
            "Whether an `ExplanationEngine` that requires a live LLM call "
            "(`engine.requires_llm`) is permitted to run. Defaults to "
            "`False` so that calling `runtime.explain(...)` is deterministic "
            "and free by default — the built-in `StructuredExplanationEngine` "
            "does not require this flag at all, since it renders explanations "
            "from canonical fields without calling a model. Set this to "
            "`True` only when you have deliberately registered an "
            "`ExplanationEngine` implementation that calls an LLM to phrase "
            "an already-approved explanation payload; otherwise "
            "`runtime.explain(...)` raises `XAIInstrumentationError`."
        ),
    )
    max_concurrency: int = Field(
        default=32,
        ge=1,
        description=(
            "The maximum number of instrumentation operations (writes, "
            "events, plugin dispatch) this runtime allows to run "
            "concurrently, enforced with an internal semaphore. Bounds "
            "memory and connection usage under bursty graph execution "
            "(e.g. many parallel tool calls fanning out at once) without "
            "requiring you to configure a separate connection pool. Raise "
            "it if your storage/observability backend can sustain more "
            "concurrent writes; lower it to bound load against a "
            "rate-limited backend."
        ),
    )
    operation_timeout_seconds: float = Field(
        default=10.0,
        gt=0,
        description=(
            "The per-operation timeout applied to each instrumentation call "
            "(a single storage write, a single observability emit, a single "
            "policy evaluation). A slow or hung provider cannot stall the "
            "graph run indefinitely; once the timeout elapses the operation "
            "is treated as a failure and handled according to "
            "`failure_mode`. Lower it for latency-sensitive production "
            "paths talking to fast backends; raise it for slower network "
            "storage or observability providers."
        ),
    )
    event_queue_size: int = Field(
        default=1024,
        ge=1,
        description=(
            "Reserved for a future bounded, asynchronous event-dispatch "
            "queue. The current runtime dispatches instrumentation "
            "operations directly (bounded only by `max_concurrency`), so "
            "this value is accepted and validated but not yet consumed. It "
            "is kept in `XAIConfig` now so that enabling a queued dispatch "
            "path later does not require a breaking configuration change."
        ),
    )


Config = XAIConfig
