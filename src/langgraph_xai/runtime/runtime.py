"""Async-first, instance-scoped XAI runtime."""

from __future__ import annotations

import asyncio
import contextvars
import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, TypeVar
from uuid import UUID, uuid4

from langgraph_xai.attribution import HybridAttribution
from langgraph_xai.config import XAIConfig
from langgraph_xai.core.models import (
    AttributionResult,
    CanonicalEvent,
    CaptureMode,
    Decision,
    DecisionFactor,
    DecisionType,
    Evidence,
    EvidenceType,
    ExceptionEvent,
    Execution,
    ExecutionCompletedEvent,
    ExecutionContext,
    ExecutionFailedEvent,
    ExecutionStartedEvent,
    ExecutionStatus,
    Explanation,
    ExplanationContext,
    HumanInteraction,
    HumanInteractionType,
    InterruptEvent,
    MemoryOperation,
    MemoryReference,
    PolicyAction,
    ProvenanceLink,
    RetrievalExecution,
    RetrievalExecutionEvent,
    RetrievedDocument,
    StateChange,
    StateTransition,
    StateTransitionEvent,
    ToolExecution,
    ToolExecutionEvent,
    ToolStatus,
)
from langgraph_xai.core.protocols import (
    AttributionEngine,
    CapturePolicy,
    ExplanationEngine,
    ObservabilityProvider,
    PolicyProvider,
    ProvenanceStore,
)
from langgraph_xai.explanation import StructuredExplanationEngine
from langgraph_xai.observability import NoOpObservability
from langgraph_xai.plugins import PluginManager, SemanticArtifact, XAIPlugin
from langgraph_xai.policy import (
    DefaultCapturePolicy,
    DefaultPolicyProvider,
    sanitize_mapping,
    sanitize_value,
)
from langgraph_xai.storage import InMemoryProvenanceStore

from .registry import Registry

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping, Sequence

T = TypeVar("T")
Jsonish = str | int | float | bool | None | list["Jsonish"] | dict[str, "Jsonish"]


class XAIInstrumentationError(RuntimeError):
    """Raised when configured instrumentation guarantees cannot be met."""


@dataclass(slots=True)
class Run:
    execution: Execution
    sequence: int = 0
    artifacts: list[SemanticArtifact] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def next_sequence(self) -> int:
        with self.lock:
            value = self.sequence
            self.sequence += 1
            return value


_active_run: contextvars.ContextVar[tuple[XAIRuntime, Run] | None] = contextvars.ContextVar(
    "langgraph_xai_active_run", default=None
)
_active_runtimes: contextvars.ContextVar[frozenset[int]] = contextvars.ContextVar(
    "langgraph_xai_active_runtimes", default=frozenset()
)


def _json_value(value: Any) -> Jsonish:
    return sanitize_value(value)


def _optional_string(value: Any) -> str | None:
    return None if value is None else str(value)


def _json_mapping(value: Mapping[str, Any] | None) -> dict[str, Any]:
    return sanitize_mapping(value or {})


class XAIRuntime:
    """Coordinates capture capabilities without process-global runtime state."""

    def __init__(
        self,
        config: XAIConfig | None = None,
        registry: Registry | None = None,
        *,
        application_id: str = "application",
        tenant_id: str = "default",
        graph_id: str = "graph",
        plugins: tuple[XAIPlugin, ...] = (),
        custom_state_capture: Callable[[Mapping[str, Any], Mapping[str, Any]], Mapping[str, Any]]
        | None = None,
    ) -> None:
        """Build a runtime with sensible in-memory defaults for every capability.

        Args:
            config: Capture/failure/concurrency settings. Defaults to
                ``XAIConfig()`` (delta-capture, fail-open, 32-way
                concurrency). See `XAIConfig`
                for every field.
            registry: The capability registry backing ``register``/
                ``instrument``. Defaults to a new, empty
                `Registry`. Pass one in only
                when you need to share a registry across multiple runtimes.
            application_id: Identifies the owning application in every
                recorded `ExecutionContext`,
                unless overridden per call via the ``xai_application_id``
                key in a LangChain config's ``metadata``.
            tenant_id: Identifies the tenant, for the same purpose as
                ``application_id`` (overridable via ``xai_tenant_id``).
            graph_id: Identifies the LangGraph graph being instrumented
                (overridable via ``xai_graph_id``).
            plugins: `XAIPlugin` instances that
                receive every semantic artifact (evidence, decision,
                memory reference) as it is recorded — see
                [Architecture: plugins](../architecture/plugins.md).
            custom_state_capture: Required only when
                ``config.capture_state`` is ``CaptureMode.CUSTOM``. Given the
                node's before/after state, returns the exact mapping of
                fields to record.

        Note:
            The runtime pre-registers a working, in-memory/no-op default for
            every capability (`InMemoryProvenanceStore`,
            `NoOpObservability`,
            `HybridAttribution`,
            `StructuredExplanationEngine`,
            `DefaultPolicyProvider`,
            `DefaultCapturePolicy`) so a runtime
            is immediately usable with zero configuration. Call
            `register` afterwards to replace any of them with a real
            backend.
        """
        self.config = config or XAIConfig()
        self.registry = registry or Registry()
        defaults: tuple[tuple[type[object], object], ...] = (
            (ProvenanceStore, InMemoryProvenanceStore()),
            (ObservabilityProvider, NoOpObservability()),
            (AttributionEngine, HybridAttribution()),
            (ExplanationEngine, StructuredExplanationEngine()),
            (PolicyProvider, DefaultPolicyProvider()),
            (CapturePolicy, DefaultCapturePolicy()),
        )
        for capability, provider in defaults:
            if self.registry.get(capability) is None:
                self.registry.register(capability, provider)
        self.application_id = application_id
        self.tenant_id = tenant_id
        self.graph_id = graph_id
        self.custom_state_capture = custom_state_capture
        self.max_concurrency = self.config.max_concurrency
        self.timeout = self.config.operation_timeout_seconds
        self.plugins = PluginManager(plugins)
        self._slots = threading.BoundedSemaphore(self.max_concurrency)
        self._errors: deque[BaseException] = deque(maxlen=100)
        self._closed = False

    @property
    def errors(self) -> tuple[BaseException, ...]:
        return tuple(self._errors)

    @property
    def current_run(self) -> Run | None:
        active = _active_run.get()
        return active[1] if active is not None and active[0] is self else None

    def is_instrumenting(self) -> bool:
        return id(self) in _active_runtimes.get()

    def register(self, capability: type[T], provider: T) -> T:
        """Register or replace one runtime capability."""
        return self.registry.register(capability, provider)

    def instrument(self, graph: Any) -> Any:
        """Wrap a public LangGraph/LangChain Runnable."""
        from langgraph_xai.instrumentation import InstrumentedGraph

        return InstrumentedGraph(graph, self)

    def enter(self, run: Run) -> tuple[contextvars.Token[Any], contextvars.Token[Any]]:
        return (
            _active_run.set((self, run)),
            _active_runtimes.set(_active_runtimes.get() | {id(self)}),
        )

    @staticmethod
    def exit(tokens: tuple[contextvars.Token[Any], contextvars.Token[Any]]) -> None:
        _active_run.reset(tokens[0])
        _active_runtimes.reset(tokens[1])

    def context_from_config(self, config: Mapping[str, Any] | None = None) -> ExecutionContext:
        metadata = dict((config or {}).get("metadata") or {})
        configurable = dict((config or {}).get("configurable") or {})
        run_id = metadata.get("xai_run_id")
        return ExecutionContext(
            application_id=str(metadata.get("xai_application_id", self.application_id)),
            tenant_id=str(metadata.get("xai_tenant_id", self.tenant_id)),
            graph_id=str(metadata.get("xai_graph_id", self.graph_id)),
            run_id=UUID(str(run_id)) if run_id else uuid4(),
            thread_id=_optional_string(configurable.get("thread_id")),
            trace_id=_optional_string(metadata.get("trace_id")),
            metadata=sanitize_mapping(
                {key: value for key, value in metadata.items() if not str(key).startswith("xai_")}
            ),
        )

    async def start_run(self, config: Mapping[str, Any] | None = None) -> Run:
        self._ensure_open()
        execution = Execution(
            context=self.context_from_config(config),
            status=ExecutionStatus.RUNNING,
            started_at=datetime.now(UTC),
        )
        run = Run(execution)
        await self._write(execution)
        await self._event(
            ExecutionStartedEvent(context=execution.context, sequence=run.next_sequence())
        )
        return run

    async def finish_run(
        self,
        run: Run,
        error: BaseException | None = None,
        *,
        cancelled: bool = False,
        interrupts: Sequence[Any] | None = None,
    ) -> None:
        run.execution.ended_at = datetime.now(UTC)
        if interrupts:
            run.execution.status = ExecutionStatus.INTERRUPTED
            for item in interrupts:
                await self.record_human_interaction(
                    HumanInteractionType.INTERRUPT,
                    request_reference=_optional_string(getattr(item, "id", None)),
                    metadata={"value": getattr(item, "value", item)},
                    run=run,
                )
            await self._write(run.execution)
            return
        if error is None and not cancelled:
            run.execution.status = ExecutionStatus.COMPLETED
            event: CanonicalEvent = ExecutionCompletedEvent(
                context=run.execution.context, sequence=run.next_sequence()
            )
        else:
            run.execution.status = (
                ExecutionStatus.CANCELLED if cancelled else ExecutionStatus.FAILED
            )
            exception = ExceptionEvent(
                context=run.execution.context,
                exception_type=type(error).__name__ if error else "CancelledError",
                message=str(error) if error else "execution cancelled",
            )
            run.execution.exceptions.append(exception)
            event = ExecutionFailedEvent(
                context=run.execution.context,
                sequence=run.next_sequence(),
                error=exception,
            )
        await self._event(event)
        await self._write(run.execution)

    async def record_human_interaction(
        self,
        interaction_type: HumanInteractionType | str,
        *,
        actor_reference: str | None = None,
        request_reference: str | None = None,
        response_reference: str | None = None,
        continuation_run_id: UUID | None = None,
        metadata: Mapping[str, Any] | None = None,
        run: Run | None = None,
    ) -> HumanInteraction:
        """Record a human-in-the-loop checkpoint: an interrupt, approval, or resume.

        LangGraph's ``interrupt()``/``Command(resume=...)`` boundary does not
        travel through LangChain's callback system, so it cannot be captured
        automatically the way tool or chain events are. Instrumentation calls
        this explicitly when it detects ``__interrupt__`` in graph output or a
        ``Command(resume=...)`` input; applications may also call it directly
        for approval/rejection/edit decisions made outside the graph itself.
        """
        target = self._require_run(run)
        interaction = HumanInteraction(
            context=target.execution.context,
            interaction_type=interaction_type,
            actor_reference=actor_reference,
            request_reference=request_reference,
            response_reference=response_reference,
            continuation_run_id=continuation_run_id,
            metadata=_json_mapping(metadata),
        )
        target.execution.human_interactions.append(interaction)
        await self._event(
            InterruptEvent(
                context=target.execution.context,
                sequence=target.next_sequence(),
                interaction=interaction,
            )
        )
        return interaction

    async def record_state_delta(
        self,
        node_id: str,
        before: Mapping[str, Any] | None,
        after: Mapping[str, Any] | None,
        *,
        run: Run | None = None,
    ) -> StateTransition | None:
        """Record a node's state change, filtered by ``config.capture_state``.

        Args:
            node_id: The LangGraph node whose state changed.
            before: The state mapping observed before the node ran.
            after: The state mapping observed after the node ran.
            run: The active `Run`; defaults to the run bound to the
                current async context (set by ``instrument``/``enter``).

        Returns:
            The recorded `StateTransition`,
            or ``None`` when there is no active run or
            ``config.capture_state`` is ``CaptureMode.NONE``.
        """
        target = self._resolve_run(run)
        if target is None or self.config.capture_state == CaptureMode.NONE:
            return None
        before_values = sanitize_mapping(before or {})
        after_values = sanitize_mapping(after or {})
        keys = before_values.keys() | after_values.keys()
        if self.config.capture_state is CaptureMode.SELECTIVE:
            keys &= self.config.capture_fields
        elif self.config.capture_state is CaptureMode.CUSTOM:
            if self.custom_state_capture is None:
                raise ValueError("CUSTOM capture mode requires custom_state_capture")
            selected = sanitize_mapping(self.custom_state_capture(before or {}, after or {}))
            keys = selected.keys()
            after_values = selected
        changes = [
            StateChange(
                path=str(key),
                before=_json_value(before_values.get(key)),
                after=_json_value(after_values.get(key)),
            )
            for key in keys
            if self.config.capture_state is CaptureMode.FULL
            or before_values.get(key) != after_values.get(key)
        ]
        transition = StateTransition(
            context=target.execution.context,
            node_id=node_id,
            changes=changes,
            capture_mode=self.config.capture_state,
        )
        target.execution.state_transitions.append(transition)
        await self._event(
            StateTransitionEvent(
                context=target.execution.context,
                sequence=target.next_sequence(),
                transition=transition,
            )
        )
        return transition

    async def record_evidence(
        self,
        evidence_type: EvidenceType | str,
        *,
        summary: str | None = None,
        content_reference: str | None = None,
        confidence: float | None = None,
        metadata: Mapping[str, Any] | None = None,
        run: Run | None = None,
    ) -> Evidence:
        """Record material that supports an upcoming decision.

        Records an `Evidence` artifact —
        see [Concepts: Evidence](../concepts/evidence.md) for the
        distinction between evidence and provenance, and what fields this
        method deliberately does not accept (raw content is referenced via
        ``content_reference``, never embedded).

        Args:
            evidence_type: The kind of evidence, e.g. ``"tool_result"``,
                ``"retrieved_document"``, ``"model_output"``.
            summary: A short, human-readable description of what the
                evidence shows.
            content_reference: An opaque pointer to the full content (a
                document ID, a URI), not the content itself.
            confidence: An optional 0-1 confidence score for the evidence
                itself, independent of how it is later weighted by
                attribution.
            metadata: Additional JSON-safe fields; sanitized before storage.
            run: The active `Run`; defaults to the current context.

        Returns:
            The recorded ``Evidence`` artifact.
        """
        target = self._require_run(run)
        artifact = Evidence(
            context=target.execution.context,
            evidence_type=evidence_type,
            summary=summary,
            content_reference=content_reference,
            confidence=confidence,
            metadata=_json_mapping(metadata),
        )
        await self._semantic(target, artifact)
        return artifact

    async def record_decision(
        self,
        selected_action: str,
        *,
        decision_type: DecisionType | str = DecisionType.CUSTOM,
        candidate_actions: list[str] | None = None,
        evidence_ids: list[UUID] | None = None,
        factors: list[DecisionFactor] | None = None,
        confidence: float | None = None,
        metadata: Mapping[str, Any] | None = None,
        run: Run | None = None,
    ) -> Decision:
        """Record the action an application selected, and why.

        Records a `Decision` artifact —
        see [Concepts: Decisions](../concepts/decisions.md) for its
        relationship to evidence and factors, and
        [Concepts: Attribution](../concepts/attribution.md) for how
        ``factors`` later feeds ``HybridAttribution``'s rule-based score.

        Args:
            selected_action: The action that was actually taken.
            decision_type: The kind of decision, e.g. ``"routing"``,
                ``"tool_selection"``, ``"final_response"``.
            candidate_actions: Other actions that were considered but not
                selected.
            evidence_ids: IDs of `Evidence` artifacts that supported
                this decision.
            factors: Named, weighted inputs to the decision (see
                `DecisionFactor`).
            confidence: An optional 0-1 confidence score for the decision.
            metadata: Additional JSON-safe fields; sanitized before storage.
            run: The active `Run`; defaults to the current context.

        Returns:
            The recorded ``Decision`` artifact.
        """
        target = self._require_run(run)
        artifact = Decision(
            context=target.execution.context,
            decision_type=decision_type,
            selected_action=selected_action,
            candidate_actions=candidate_actions or [],
            evidence_ids=evidence_ids or [],
            factors=factors or [],
            confidence=confidence,
            metadata=_json_mapping(metadata),
        )
        await self._semantic(target, artifact)
        return artifact

    async def record_tool(
        self,
        tool_name: str,
        *,
        tool_id: str | None = None,
        status: ToolStatus = ToolStatus.SUCCEEDED,
        tool_call_id: str | None = None,
        input_reference: str | None = None,
        output_reference: str | None = None,
        latency_ms: float | None = None,
        metadata: Mapping[str, Any] | None = None,
        run: Run | None = None,
    ) -> ToolExecution:
        target = self._require_run(run)
        tool = ToolExecution(
            context=target.execution.context,
            tool_id=tool_id or tool_name,
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            status=status,
            input_reference=input_reference,
            output_reference=output_reference,
            latency_ms=latency_ms,
            metadata=_json_mapping(metadata),
        )
        target.execution.tools.append(tool)
        await self._event(
            ToolExecutionEvent(
                context=target.execution.context,
                sequence=target.next_sequence(),
                tool=tool,
            )
        )
        return tool

    async def record_retrieval(
        self,
        retriever_id: str,
        *,
        documents: list[RetrievedDocument] | None = None,
        query_reference: str | None = None,
        reranker: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        run: Run | None = None,
    ) -> RetrievalExecution:
        target = self._require_run(run)
        retrieval = RetrievalExecution(
            context=target.execution.context,
            retriever_id=retriever_id,
            documents=documents or [],
            query_reference=query_reference,
            reranker=reranker,
            metadata=_json_mapping(metadata),
        )
        target.execution.retrievals.append(retrieval)
        await self._event(
            RetrievalExecutionEvent(
                context=target.execution.context,
                sequence=target.next_sequence(),
                retrieval=retrieval,
            )
        )
        return retrieval

    async def record_memory(
        self,
        memory_id: str,
        operation: MemoryOperation,
        *,
        namespace: str | None = None,
        content_reference: str | None = None,
        private: bool = True,
        metadata: Mapping[str, Any] | None = None,
        run: Run | None = None,
    ) -> MemoryReference:
        target = self._require_run(run)
        artifact = MemoryReference(
            context=target.execution.context,
            memory_id=memory_id,
            operation=operation,
            namespace=namespace,
            content_reference=content_reference,
            private=private,
            metadata=_json_mapping(metadata),
        )
        target.execution.memory.append(artifact)
        await self._semantic(target, artifact)
        return artifact

    async def record_provenance(
        self,
        source_id: str | UUID,
        target_id: str | UUID,
        relation: str,
        *,
        metadata: Mapping[str, Any] | None = None,
        run: Run | None = None,
    ) -> ProvenanceLink:
        """Record a ``source -> relation -> target`` provenance edge.

        Writes directly to the registered
        `ProvenanceStore` (not to the
        execution record) — see
        [Concepts: Provenance](../concepts/provenance.md) for the relation
        vocabulary (``DERIVED_FROM``, ``PRODUCED_BY``, ``SUPPORTED_BY``, …)
        and how ``store.lineage(...)`` later walks these edges.

        Args:
            source_id: The upstream entity (e.g. a raw API response ID).
            target_id: The downstream entity this edge points to (e.g. a
                transaction record derived from it).
            relation: The relationship name, e.g. ``"derived_from"``.
            metadata: Additional JSON-safe fields; sanitized before storage.
            run: The active `Run`; defaults to the current context.

        Returns:
            The recorded ``ProvenanceLink``.
        """
        target = self._require_run(run)
        link = ProvenanceLink(
            source_id=source_id,
            target_id=target_id,
            relation=relation,
            context=target.execution.context,
            metadata=_json_mapping(metadata),
        )
        await self._write(link)
        return link

    async def attribute(self, context: ExplanationContext) -> AttributionResult:
        """Run the registered `AttributionEngine`.

        Usually called implicitly by `explain` when
        ``context.attribution`` is ``None`` — call it directly only when you
        need the `AttributionResult` on
        its own, without assembling a full explanation.
        """
        engine = self.registry.require(AttributionEngine)
        result = await self._run_operation(lambda: engine.attribute(context))
        if result is None:
            raise XAIInstrumentationError("attribution failed in fail-open mode")
        return result

    async def explain(self, context: ExplanationContext) -> Explanation:
        """Assemble a policy-filtered explanation for one audience.

        This is the method most applications call directly. It (1) asks the
        registered `PolicyProvider` to
        evaluate ``context.audience`` against ``PolicyAction.EXPOSE``, (2)
        runs `attribute` if ``context.attribution`` was not already
        supplied, and (3) hands the policy-augmented context to the
        registered `ExplanationEngine`.
        See [Concepts: Explanations](../concepts/explanations.md) for a
        real, complete input/output example.

        Raises:
            XAIInstrumentationError: If the registered engine requires an
                LLM call (``engine.requires_llm``) but
                ``config.llm_explanation_enabled`` is ``False``, or if the
                engine fails while ``config.failure_mode`` is fail-open.
        """
        policy = self.registry.require(PolicyProvider)
        decision = await self._run_operation(lambda: policy.evaluate(context, PolicyAction.EXPOSE))
        policies = list(context.policies)
        if decision is not None:
            policies.append(decision)
        attributed = context.attribution
        prepared = context.model_copy(update={"policies": policies})
        if attributed is None:
            attributed = await self.attribute(prepared)
            prepared = prepared.model_copy(update={"attribution": attributed})
        engine = self.registry.require(ExplanationEngine)
        if engine.requires_llm and not self.config.llm_explanation_enabled:
            raise XAIInstrumentationError(
                "LLM explanation engine is registered but disabled in XAIConfig"
            )
        explanation = await self._run_operation(lambda: engine.explain(prepared))
        if explanation is None:
            raise XAIInstrumentationError("explanation failed in fail-open mode")
        return explanation

    async def record_artifact(
        self, artifact: SemanticArtifact, *, run: Run | None = None
    ) -> SemanticArtifact:
        target = self._require_run(run)
        if artifact.context.run_id != target.execution.context.run_id:
            raise ValueError("artifact context does not match the active execution")
        await self._semantic(target, artifact)
        return artifact

    async def flush(self) -> None:
        """Flush the registered observability provider and every plugin.

        Call this at natural checkpoints (e.g. after a batch of runs) when
        a provider buffers writes internally, such as
        `LangfuseObservability`.
        """
        await self._call_optional(ObservabilityProvider, "flush")
        await self._run_operation(self.plugins.flush)

    async def close(self) -> None:
        """Flush and release the provenance store, observability provider, and plugins.

        Idempotent — calling ``close`` more than once is a no-op after the
        first call. Call this once when the runtime's owning application
        (not an individual run) is shutting down.
        """
        if self._closed:
            return
        try:
            await self.flush()
            await self._call_optional(ProvenanceStore, "close")
            await self._call_optional(ObservabilityProvider, "close")
            await self._run_operation(self.plugins.close)
        finally:
            self._closed = True

    def run_sync(self, awaitable: Awaitable[T]) -> T:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(awaitable)
        result: list[T] = []
        failure: list[BaseException] = []

        def execute() -> None:
            try:
                result.append(asyncio.run(awaitable))
            except BaseException as error:
                failure.append(error)

        thread = threading.Thread(target=execute, daemon=True)
        thread.start()
        thread.join()
        if failure:
            raise failure[0]
        return result[0]

    async def _event(self, event: CanonicalEvent) -> None:
        capture = self.registry.get(CapturePolicy)
        if capture is not None:
            decision = await self._run_operation(lambda: capture.evaluate(event))
            if decision is not None and not decision.allowed:
                return
        await self._write(event)
        observer = self.registry.get(ObservabilityProvider)
        if observer is not None:
            await self._run_operation(lambda: observer.emit(event))
        elif (
            self.config.failure_mode.value == "strict"
            and self.registry.get(ProvenanceStore) is None
        ):
            raise XAIInstrumentationError("strict mode requires a provenance or observability sink")

    async def _write(self, item: Execution | ProvenanceLink | CanonicalEvent) -> None:
        store = self.registry.get(ProvenanceStore)
        if store is not None:
            await self._run_operation(lambda: store.write(item))
        elif (
            self.config.failure_mode.value == "strict"
            and self.registry.get(ObservabilityProvider) is None
        ):
            raise XAIInstrumentationError("strict mode requires a provenance or observability sink")

    async def _semantic(self, run: Run, artifact: SemanticArtifact) -> None:
        run.artifacts.append(artifact)
        if self.plugins.plugins:
            await self._run_operation(lambda: self.plugins.record(artifact))
        elif self.config.failure_mode.value == "strict":
            raise XAIInstrumentationError("strict mode requires a plugin for semantic artifacts")

    async def _call_optional(self, capability: type[Any], method: str) -> None:
        provider = self.registry.get(capability)
        if provider is not None:
            await self._run_operation(lambda: getattr(provider, method)())

    async def _run_operation(self, operation: Callable[[], Awaitable[T]]) -> T | None:
        acquired = False
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.timeout
        try:
            while not (acquired := self._slots.acquire(blocking=False)):
                if loop.time() >= deadline:
                    raise TimeoutError("timed out waiting for an instrumentation slot")
                await asyncio.sleep(min(0.01, max(0, deadline - loop.time())))
            async with asyncio.timeout(self.timeout):
                return await operation()
        except asyncio.CancelledError:
            raise
        except BaseException as error:
            self._errors.append(error)
            if self.config.failure_mode.value != "fail_open":
                raise XAIInstrumentationError("instrumentation operation failed") from error
            return None
        finally:
            if acquired:
                self._slots.release()

    def _resolve_run(self, run: Run | None) -> Run | None:
        return run or self.current_run

    def _require_run(self, run: Run | None) -> Run:
        target = self._resolve_run(run)
        if target is None:
            raise RuntimeError("semantic recording requires an active run or explicit run")
        return target

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("runtime is closed")
