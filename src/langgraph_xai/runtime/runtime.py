"""Async-first, instance-scoped explainability runtime."""

from __future__ import annotations

import asyncio
import contextlib
import contextvars
import threading
import weakref
from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, TypeVar
from uuid import UUID, uuid4

from langgraph_xai.attribution import HybridAttribution
from langgraph_xai.config import XAIConfig
from langgraph_xai.core.models import (
    AttributionResult,
    Audience,
    CanonicalEvent,
    CaptureMode,
    CheckpointEvent,
    CheckpointReference,
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
    FailureMode,
    HumanInteraction,
    HumanInteractionType,
    InterruptEvent,
    MemoryOperation,
    MemoryReference,
    NodeExecution,
    NodeExecutionEvent,
    PolicyAction,
    ProvenanceLink,
    RetrievalExecution,
    RetrievalExecutionEvent,
    RetrievedDocument,
    SourceReference,
    StateChange,
    StateTransition,
    StateTransitionEvent,
    ToolExecution,
    ToolExecutionEvent,
    ToolStatus,
    utc_now,
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
    REDACTED,
    DefaultCapturePolicy,
    DefaultPolicyProvider,
    is_sensitive_key,
    sanitize_mapping,
    sanitize_value,
)
from langgraph_xai.storage import InMemoryProvenanceStore

from .registry import Registry

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Coroutine, Generator, Mapping, Sequence
    from datetime import datetime

    from langchain_core.runnables import Runnable
    from langgraph.types import Interrupt

    from langgraph_xai.instrumentation import InstrumentedGraph

T = TypeVar("T")

RUN_ID_METADATA_KEY = "langgraph_xai_run_id"
"""The ``RunnableConfig`` metadata key that carries a run's ID into the graph.

Instrumented calls add it to the config the wrapped graph receives, so the
graph's nodes, tracing callbacks, and every checkpoint the call writes carry
the ``run_id`` under this key.
"""


class XAIInstrumentationError(RuntimeError):
    """Raised when an instrumentation guarantee cannot be met.

    Raised for every instrumentation failure when the failure mode is
    ``FAIL_CLOSED`` or ``STRICT``, and by `XAIRuntime.explain` in every mode when
    an explanation cannot be produced safely. The underlying error is chained
    as ``__cause__``.
    """


@dataclass(slots=True, eq=False)
class Run:
    """Handle on one execution: its live `Execution` record and its semantic artifacts.

    Runs compare and hash by identity.
    """

    execution: Execution
    artifacts: list[SemanticArtifact] = field(default_factory=list)
    _sequence: int = field(default=0, init=False, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    @property
    def run_id(self) -> UUID:
        """The run's ID, shared by every artifact it produced."""
        return self.execution.context.run_id

    @property
    def evidence(self) -> list[Evidence]:
        """Evidence recorded during this run, in recording order."""
        return [artifact for artifact in self.artifacts if isinstance(artifact, Evidence)]

    @property
    def decisions(self) -> list[Decision]:
        """Decisions recorded during this run, in recording order."""
        return [artifact for artifact in self.artifacts if isinstance(artifact, Decision)]

    def _next_sequence(self) -> int:
        with self._lock:
            value = self._sequence
            self._sequence += 1
            return value


_active_run: contextvars.ContextVar[tuple[XAIRuntime, Run] | None] = contextvars.ContextVar(
    "langgraph_xai_active_run", default=None
)
_active_runtimes: contextvars.ContextVar[frozenset[int]] = contextvars.ContextVar(
    "langgraph_xai_active_runtimes", default=frozenset()
)
_run_collector: contextvars.ContextVar[tuple[XAIRuntime, list[Run]] | None] = (
    contextvars.ContextVar("langgraph_xai_run_collector", default=None)
)


class _ThreadLoop:
    """One reusable event loop per thread for `XAIRuntime.run_sync`."""

    __slots__ = ("loop", "runner")

    def __init__(self) -> None:
        loop = asyncio.new_event_loop()
        self.loop = loop
        self.runner = asyncio.Runner(loop_factory=lambda: loop)

    def __del__(self) -> None:
        if not self.loop.is_running() and not self.loop.is_closed():
            self.loop.close()


_thread_loops = threading.local()


def _thread_runner() -> asyncio.Runner:
    holder: _ThreadLoop | None = getattr(_thread_loops, "holder", None)
    if holder is None:
        holder = _ThreadLoop()
        _thread_loops.holder = holder
    return holder.runner


class _HelperLoop:
    """A background event loop serving `XAIRuntime.run_sync` for one thread whose loop is busy.

    A thread that already runs an event loop cannot run another one, so its
    `run_sync` calls are executed here. Reusing one helper per thread avoids
    creating a thread and an event loop for every call. The helper stops when
    the calling thread releases it, and closes its loop in its own thread.
    """

    __slots__ = ("__weakref__", "loop")

    def __init__(self) -> None:
        loop = asyncio.new_event_loop()
        thread = threading.Thread(target=_serve, args=(loop,), name="langgraph-xai-sync")
        thread.daemon = True
        thread.start()
        self.loop = loop
        weakref.finalize(self, _stop, loop)

    def run[Result](
        self, coroutine: Coroutine[Any, Any, Result], context: contextvars.Context
    ) -> Result:
        # Scheduling inside `context` makes the task run with a copy of it.
        future = context.run(asyncio.run_coroutine_threadsafe, coroutine, self.loop)
        return future.result()


def _serve(loop: asyncio.AbstractEventLoop) -> None:
    try:
        loop.run_forever()
    finally:
        loop.close()


def _stop(loop: asyncio.AbstractEventLoop) -> None:
    with contextlib.suppress(RuntimeError):  # the loop is already closed
        loop.call_soon_threadsafe(loop.stop)


def _thread_helper() -> _HelperLoop:
    helper: _HelperLoop | None = getattr(_thread_loops, "helper", None)
    if helper is None:
        helper = _HelperLoop()
        _thread_loops.helper = helper
    return helper


class _Slots:
    """A counting semaphore shared by every thread and event loop of one runtime.

    Waiters queue in FIFO order and are woken on their own loop as soon as a
    slot is released, so no waiter polls. A slot granted to a waiter that has
    already given up (timed out or cancelled) is passed on to the next one.
    """

    __slots__ = ("_free", "_lock", "_waiters")

    def __init__(self, size: int) -> None:
        self._free = size
        self._lock = threading.Lock()
        self._waiters: deque[tuple[asyncio.AbstractEventLoop, asyncio.Future[None]]] = deque()

    async def acquire(self) -> None:
        loop = asyncio.get_running_loop()
        with self._lock:
            if self._free and not self._waiters:
                self._free -= 1
                return
            waiter: asyncio.Future[None] = loop.create_future()
            self._waiters.append((loop, waiter))
        try:
            await waiter
        except BaseException:
            with self._lock:
                granted = waiter.done() and not waiter.cancelled()
                if not granted:
                    with contextlib.suppress(ValueError):  # already handed a slot
                        self._waiters.remove((loop, waiter))
            if granted:
                self.release()
            raise

    def release(self) -> None:
        with self._lock:
            while self._waiters:
                loop, waiter = self._waiters.popleft()
                try:
                    loop.call_soon_threadsafe(self._grant, waiter)
                except RuntimeError:  # the waiter's loop is closed
                    continue
                return
            self._free += 1

    def _grant(self, waiter: asyncio.Future[None]) -> None:
        if waiter.done():
            self.release()
        else:
            waiter.set_result(None)


def _optional_string(value: Any) -> str | None:
    return None if value is None else str(value)


def _json_mapping(value: Mapping[str, Any] | None) -> dict[str, Any]:
    return sanitize_mapping(value or {})


def _redacted_factor(factor: DecisionFactor) -> DecisionFactor:
    # A factor is a named value, so a credential-named factor never keeps its value.
    value = REDACTED if is_sensitive_key(factor.name) else sanitize_value(factor.value)
    return factor.model_copy(update={"value": value, "metadata": _json_mapping(factor.metadata)})


def _equal(left: Any, right: Any) -> bool:
    try:
        return bool(left == right)
    except Exception:
        return False


def _state_change(
    key: Any, before: Mapping[Any, Any], after: Mapping[Any, Any], *, full: bool
) -> StateChange | None:
    path = str(key)
    if is_sensitive_key(path):
        return StateChange(path=path, before=REDACTED, after=REDACTED) if full else None
    old, new = before.get(key), after.get(key)
    if not full and (old is new or _equal(old, new)):
        return None
    old_value, new_value = sanitize_value(old), sanitize_value(new)
    if not full and old_value == new_value:
        return None
    return StateChange(path=path, before=old_value, after=new_value)


class XAIRuntime:
    """Coordinate capture, storage, attribution, policy, and explanation for one application.

    A runtime owns its configuration and capability registry; nothing is
    process-global, so independent runtimes (per tenant, per graph, per test)
    can coexist in one process.
    """

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
        """Build a runtime with working in-memory defaults for every capability.

        Args:
            config: Capture, failure, and concurrency settings. Defaults to
                ``XAIConfig()`` (delta capture, fail-open, 32 concurrent
                operations); see `XAIConfig`.
            registry: The capability registry backing `register`. Defaults to a
                new, empty `Registry`; pass one only to share providers between
                runtimes.
            application_id: Default application identifier for every recorded
                `ExecutionContext`; override per call with the
                ``xai_application_id`` key of a LangChain config's ``metadata``.
            tenant_id: Default tenant identifier (override: ``xai_tenant_id``).
            graph_id: Default graph identifier (override: ``xai_graph_id``).
            plugins: `XAIPlugin` instances that receive every semantic artifact
                (evidence, decision, memory reference) as it is recorded.
            custom_state_capture: Required when ``config.capture_state`` is
                ``CaptureMode.CUSTOM``. Given a node's state before and after it
                ran, returns the mapping of fields to record.

        Raises:
            ValueError: If ``CaptureMode.CUSTOM`` is configured without
                ``custom_state_capture``.

        Note:
            Every capability that is not already in ``registry`` is
            pre-registered with a default — `InMemoryProvenanceStore`,
            `NoOpObservability`, `HybridAttribution`,
            `StructuredExplanationEngine`, `DefaultPolicyProvider`, and
            `DefaultCapturePolicy` — so the runtime works with zero
            configuration. Call `register` to replace any of them.
        """
        self.config = config or XAIConfig()
        if self.config.capture_state is CaptureMode.CUSTOM and custom_state_capture is None:
            raise ValueError("CaptureMode.CUSTOM requires custom_state_capture")
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
        self.plugins = PluginManager(plugins)
        self._slots = _Slots(self.config.max_concurrency)
        self._errors: deque[Exception] = deque(maxlen=100)
        self._closed = False

    @property
    def errors(self) -> tuple[Exception, ...]:
        """The most recent instrumentation failures (up to 100), oldest first.

        Populated in every failure mode, including when an error is re-raised.
        """
        return tuple(self._errors)

    @property
    def current_run(self) -> Run | None:
        """The run of the instrumented call executing in the current context, if any."""
        active = _active_run.get()
        return active[1] if active is not None and active[0] is self else None

    def register(self, capability: type[T], provider: T) -> T:
        """Register or replace the provider of one capability protocol."""
        return self.registry.register(capability, provider)

    def instrument[Input, Output](
        self, graph: Runnable[Input, Output] | InstrumentedGraph[Input, Output]
    ) -> InstrumentedGraph[Input, Output]:
        """Wrap a compiled LangGraph graph (or any Runnable) for automatic capture.

        The returned `InstrumentedGraph` preserves the inputs, outputs, and
        behavior of every execution method and proxies every other attribute to
        ``graph``. Instrumenting a graph this runtime already instruments returns
        it unchanged; a graph instrumented by another runtime is re-wrapped for
        this one.
        """
        from langgraph_xai.instrumentation import InstrumentedGraph

        if isinstance(graph, InstrumentedGraph):
            if graph.runtime is self:
                return graph
            graph = graph.__wrapped__
        return InstrumentedGraph(graph, self)

    @contextlib.contextmanager
    def collect_runs(self) -> Generator[list[Run], None, None]:
        """Collect every `Run` this runtime starts within the ``with`` block.

        Use it to keep a handle on runs started by instrumented calls, so you
        can read their artifacts or call `explain_decision` after the call
        returns. Collection follows context variables, so it includes runs
        started by tasks spawned inside the block (``asyncio.gather``, batch
        calls) and excludes runs started concurrently elsewhere. An inner
        ``collect_runs`` block takes precedence over an outer one.

        Example:
            ```python
            with runtime.collect_runs() as runs:
                await graph.ainvoke({"amount": 9200})
            (run,) = runs
            explanation = await runtime.explain_decision(run.decisions[-1], run=run)
            ```
        """
        runs: list[Run] = []
        token = _run_collector.set((self, runs))
        try:
            yield runs
        finally:
            _run_collector.reset(token)

    def _is_instrumenting(self) -> bool:
        return id(self) in _active_runtimes.get()

    def _enter(self, run: Run) -> tuple[contextvars.Token[Any], contextvars.Token[Any]]:
        return (
            _active_run.set((self, run)),
            _active_runtimes.set(_active_runtimes.get() | {id(self)}),
        )

    @staticmethod
    def _exit(tokens: tuple[contextvars.Token[Any], contextvars.Token[Any]]) -> None:
        # A token created in another context (e.g. a generator resumed elsewhere) cannot reset.
        for variable, token in zip((_active_run, _active_runtimes), tokens, strict=True):
            with contextlib.suppress(ValueError, RuntimeError):
                variable.reset(token)

    def context_from_config(self, config: Mapping[str, Any] | None = None) -> ExecutionContext:
        """Build the `ExecutionContext` for a LangChain ``RunnableConfig``.

        ``metadata`` keys ``xai_application_id``, ``xai_tenant_id``,
        ``xai_graph_id``, and ``xai_run_id`` override the runtime defaults (a
        new random run ID otherwise); ``metadata["trace_id"]`` becomes the trace
        ID; ``configurable`` ``thread_id`` and ``checkpoint_id`` are recorded.
        Remaining metadata, except `RUN_ID_METADATA_KEY`, is sanitized and kept
        as context metadata.

        Raises:
            ValueError: If ``xai_run_id`` is not a UUID.
        """
        metadata = dict((config or {}).get("metadata") or {})
        configurable = dict((config or {}).get("configurable") or {})
        run_id = metadata.get("xai_run_id")
        try:
            resolved_run_id = UUID(str(run_id)) if run_id else uuid4()
        except ValueError as exc:
            raise ValueError("metadata['xai_run_id'] must be a UUID") from exc
        return ExecutionContext(
            application_id=str(metadata.get("xai_application_id", self.application_id)),
            tenant_id=str(metadata.get("xai_tenant_id", self.tenant_id)),
            graph_id=str(metadata.get("xai_graph_id", self.graph_id)),
            run_id=resolved_run_id,
            thread_id=_optional_string(configurable.get("thread_id")),
            trace_id=_optional_string(metadata.get("trace_id")),
            checkpoint_id=_optional_string(configurable.get("checkpoint_id")),
            metadata=sanitize_mapping(
                {
                    key: value
                    for key, value in metadata.items()
                    if not str(key).startswith("xai_") and key != RUN_ID_METADATA_KEY
                }
            ),
        )

    async def start_run(
        self, config: Mapping[str, Any] | None = None, *, continuation_of: UUID | None = None
    ) -> Run:
        """Start a run: record a ``RUNNING`` `Execution` and an ``execution.started`` event.

        Instrumented calls do this for you. Call it directly only to record
        artifacts for work that does not go through an instrumented graph.

        Args:
            config: The LangChain ``RunnableConfig`` of the call; see
                `context_from_config`.
            continuation_of: The ``run_id`` of the earlier run this run
                continues, stored as `Execution.continuation_of`. Ignored when
                it equals this run's own ID.

        Raises:
            RuntimeError: If the runtime is closed.
        """
        self._ensure_open()
        context = self.context_from_config(config)
        execution = Execution(
            context=context,
            status=ExecutionStatus.RUNNING,
            started_at=utc_now(),
            continuation_of=None if continuation_of == context.run_id else continuation_of,
        )
        run = Run(execution)
        collector = _run_collector.get()
        if collector is not None and collector[0] is self:
            collector[1].append(run)
        await self._write(execution)
        await self._event(
            ExecutionStartedEvent(context=execution.context, sequence=run._next_sequence())
        )
        return run

    async def finish_run(
        self,
        run: Run,
        error: BaseException | None = None,
        *,
        cancelled: bool = False,
        interrupts: Sequence[Interrupt] = (),
        pending_nodes: Sequence[str] = (),
    ) -> None:
        """Finish a run as completed, failed, cancelled, or interrupted, and persist it.

        Instrumented calls do this for you.

        Args:
            run: The run to finish.
            error: The exception the run failed with; the run becomes
                ``FAILED`` and an `ExceptionEvent` is recorded.
            cancelled: Whether the run was cancelled; it becomes ``CANCELLED``.
            interrupts: The LangGraph ``Interrupt`` objects the run paused on.
                Unless ``error`` or ``cancelled`` is set, the run becomes
                ``INTERRUPTED`` and one ``INTERRUPT`` `HumanInteraction` is
                recorded per interrupt, with the interrupt's ``id`` as
                ``request_reference`` and its ``value`` in the metadata.
            pending_nodes: The nodes a static breakpoint (``interrupt_before``
                or ``interrupt_after``) paused before. Without ``interrupts``,
                the run becomes ``INTERRUPTED`` and one ``INTERRUPT`` interaction
                lists them as ``pending_nodes`` in its metadata.
        """
        if error is None and not cancelled and (interrupts or pending_nodes):
            if interrupts:
                for item in interrupts:
                    await self.record_human_interaction(
                        HumanInteractionType.INTERRUPT,
                        request_reference=item.id,
                        metadata={"value": item.value},
                        run=run,
                    )
            else:
                await self.record_human_interaction(
                    HumanInteractionType.INTERRUPT,
                    metadata={"pending_nodes": list(pending_nodes)},
                    run=run,
                )
            run.execution.status = ExecutionStatus.INTERRUPTED
            run.execution.ended_at = utc_now()
            await self._write(run.execution)
            return
        run.execution.ended_at = utc_now()
        if error is None and not cancelled:
            run.execution.status = ExecutionStatus.COMPLETED
            event: CanonicalEvent = ExecutionCompletedEvent(
                context=run.execution.context, sequence=run._next_sequence()
            )
        else:
            run.execution.status = (
                ExecutionStatus.CANCELLED if cancelled else ExecutionStatus.FAILED
            )
            exception = ExceptionEvent(
                context=run.execution.context,
                exception_type=type(error).__name__ if error else "CancelledError",
                message=(str(error) if error else "")
                or ("execution cancelled" if cancelled else "execution failed"),
            )
            run.execution.exceptions.append(exception)
            event = ExecutionFailedEvent(
                context=run.execution.context,
                sequence=run._next_sequence(),
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
        metadata: Mapping[str, Any] | None = None,
        run: Run | None = None,
    ) -> HumanInteraction:
        """Record a human-in-the-loop interrupt, approval, rejection, edit, or resume.

        Instrumented calls record LangGraph ``interrupt()`` pauses and
        ``Command(resume=...)`` continuations automatically; call this for
        approvals or edits made outside the graph.
        """
        target = self._require_run(run)
        interaction = HumanInteraction(
            context=target.execution.context,
            interaction_type=interaction_type,
            actor_reference=actor_reference,
            request_reference=request_reference,
            response_reference=response_reference,
            metadata=_json_mapping(metadata),
        )
        await self._record(
            target,
            target.execution.human_interactions,
            interaction,
            InterruptEvent(
                context=target.execution.context,
                sequence=target._next_sequence(),
                interaction=interaction,
            ),
        )
        return interaction

    async def record_state_delta(
        self,
        node_id: str,
        before: Mapping[str, Any] | None,
        after: Mapping[str, Any] | None,
        *,
        metadata: Mapping[str, Any] | None = None,
        run: Run | None = None,
    ) -> StateTransition | None:
        """Record a node's state change, filtered by ``config.capture_state``.

        Keys are compared in state order. Values are sanitized with
        `sanitize_value`, and credential-named keys are never recorded with
        their values. Instrumented graphs call this automatically, passing the
        node's input state as ``before`` and that state updated with the node's
        output as ``after``; for reducer channels such as ``messages``, ``after``
        is the value the node wrote, not the reduced channel value.

        Args:
            node_id: The node whose state changed.
            before: The state observed before the node ran.
            after: The state observed after the node ran.
            metadata: Additional JSON-safe fields; sanitized before storage.
            run: The run to record into; defaults to the current run.

        Returns:
            The recorded `StateTransition`, or ``None`` when there is no active
            run, ``capture_state`` is ``NONE``, or nothing was selected to record.
        """
        target = self._resolve_run(run)
        mode = self.config.capture_state
        if target is None or mode is CaptureMode.NONE:
            return None
        before_state: Mapping[str, Any] = before or {}
        after_state: Mapping[str, Any] = after or {}
        if mode is CaptureMode.CUSTOM:
            selected = self._custom_selection(before_state, after_state)
            if selected is None:
                return None
            after_state = selected
            keys: list[Any] = list(selected)
        else:
            keys = list(dict.fromkeys([*before_state, *after_state]))
            if mode is CaptureMode.SELECTIVE:
                keys = [key for key in keys if str(key) in self.config.capture_fields]
        full = mode is CaptureMode.FULL
        changes = [
            change
            for key in keys
            if (change := _state_change(key, before_state, after_state, full=full)) is not None
        ]
        if not changes:
            return None
        transition = StateTransition(
            context=target.execution.context,
            node_id=node_id,
            changes=changes,
            capture_mode=mode,
            metadata=_json_mapping(metadata),
        )
        await self._record(
            target,
            target.execution.state_transitions,
            transition,
            StateTransitionEvent(
                context=target.execution.context,
                sequence=target._next_sequence(),
                transition=transition,
            ),
        )
        return transition

    async def record_node(
        self,
        node_id: str,
        *,
        status: ExecutionStatus,
        started_at: datetime,
        ended_at: datetime | None = None,
        attempt: int = 1,
        parent_node_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        run: Run | None = None,
    ) -> NodeExecution:
        """Record the timing and outcome of one node execution.

        Instrumented graphs record every LangGraph node automatically.
        """
        target = self._require_run(run)
        node = NodeExecution(
            context=target.execution.context,
            node_id=node_id,
            parent_node_id=parent_node_id,
            status=status,
            started_at=started_at,
            ended_at=ended_at or utc_now(),
            attempt=attempt,
            metadata=_json_mapping(metadata),
        )
        await self._record(
            target,
            target.execution.nodes,
            node,
            NodeExecutionEvent(
                context=target.execution.context,
                sequence=target._next_sequence(),
                node=node,
            ),
        )
        return node

    async def record_evidence(
        self,
        evidence_type: EvidenceType | str,
        *,
        summary: str | None = None,
        content_reference: str | None = None,
        source: SourceReference | None = None,
        confidence: float | None = None,
        quality: float | None = None,
        metadata: Mapping[str, Any] | None = None,
        run: Run | None = None,
    ) -> Evidence:
        """Record material that supports an upcoming decision.

        See [Concepts: Evidence](../concepts/evidence.md). Raw content is
        referenced through ``content_reference``, never embedded.

        Args:
            evidence_type: The kind of evidence, e.g. ``EvidenceType.TOOL_RESULT``.
            summary: A short, human-readable description of what it shows.
            content_reference: An opaque pointer to the full content (a document
                ID, a URI), not the content itself.
            source: Where the evidence came from.
            confidence: Optional 0-1 confidence in the evidence itself.
            quality: Optional 0-1 quality of the evidence; `EvidenceAttribution`
                scores evidence as ``confidence * quality``.
            metadata: Additional JSON-safe fields; sanitized before storage.
            run: The run to record into; defaults to the current run.

        Returns:
            The recorded `Evidence`.
        """
        target = self._require_run(run)
        artifact = Evidence(
            context=target.execution.context,
            evidence_type=evidence_type,
            summary=summary,
            content_reference=content_reference,
            source=None
            if source is None
            else source.model_copy(update={"metadata": _json_mapping(source.metadata)}),
            confidence=confidence,
            quality=quality,
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
        provenance_ids: list[UUID] | None = None,
        factors: list[DecisionFactor] | None = None,
        policy_references: list[str] | None = None,
        confidence: float | None = None,
        uncertainty: float | None = None,
        metadata: Mapping[str, Any] | None = None,
        run: Run | None = None,
    ) -> Decision:
        """Record the action an application selected, and on what basis.

        See [Concepts: Decisions](../concepts/decisions.md) and
        [Concepts: Attribution](../concepts/attribution.md) for how ``factors``
        and ``evidence_ids`` feed attribution.

        Args:
            selected_action: The action that was taken.
            decision_type: The kind of decision, e.g. ``DecisionType.ROUTING``.
            candidate_actions: Every action that was considered, including the
                selected one.
            evidence_ids: IDs of `Evidence` that supported the decision.
            provenance_ids: IDs of `ProvenanceLink`s relevant to the decision.
            factors: Named, optionally weighted inputs (see `DecisionFactor`).
            policy_references: Identifiers of business rules or policies applied.
            confidence: Optional 0-1 confidence in the decision.
            uncertainty: Optional 0-1 uncertainty of the decision.
            metadata: Additional JSON-safe fields; sanitized before storage.
            run: The run to record into; defaults to the current run.

        Returns:
            The recorded `Decision`.
        """
        target = self._require_run(run)
        artifact = Decision(
            context=target.execution.context,
            decision_type=decision_type,
            selected_action=selected_action,
            candidate_actions=candidate_actions or [],
            evidence_ids=evidence_ids or [],
            provenance_ids=provenance_ids or [],
            factors=[_redacted_factor(factor) for factor in factors or []],
            policy_references=policy_references or [],
            confidence=confidence,
            uncertainty=uncertainty,
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
        """Record one tool invocation; instrumented graphs record tool calls automatically."""
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
        await self._record(
            target,
            target.execution.tools,
            tool,
            ToolExecutionEvent(
                context=target.execution.context,
                sequence=target._next_sequence(),
                tool=tool,
            ),
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
        """Record one retriever call; instrumented graphs record retrievers automatically."""
        target = self._require_run(run)
        retrieval = RetrievalExecution(
            context=target.execution.context,
            retriever_id=retriever_id,
            documents=[
                document.model_copy(update={"metadata": _json_mapping(document.metadata)})
                for document in documents or []
            ],
            query_reference=query_reference,
            reranker=reranker,
            metadata=_json_mapping(metadata),
        )
        await self._record(
            target,
            target.execution.retrievals,
            retrieval,
            RetrievalExecutionEvent(
                context=target.execution.context,
                sequence=target._next_sequence(),
                retrieval=retrieval,
            ),
        )
        return retrieval

    async def record_checkpoint(
        self,
        checkpoint_id: str,
        *,
        parent_checkpoint_id: str | None = None,
        restored: bool = False,
        metadata: Mapping[str, Any] | None = None,
        run: Run | None = None,
    ) -> CheckpointReference:
        """Link the run to a LangGraph checkpoint, e.g. the one a decision can be replayed from.

        Instrumented calls of a checkpointed graph record their checkpoints
        automatically (see `XAIConfig.capture_checkpoints`). Call this for
        checkpoints read elsewhere, from ``graph.get_state(config).config`` (and
        ``.parent_config``).

        Args:
            checkpoint_id: The ``configurable["checkpoint_id"]`` of the checkpoint.
            parent_checkpoint_id: The checkpoint it was derived from, if known.
            restored: Whether the run resumed from this checkpoint rather than
                producing it.
            metadata: Additional JSON-safe fields; sanitized before storage.
            run: The run to record into; defaults to the current run.

        Returns:
            The recorded `CheckpointReference`.
        """
        target = self._require_run(run)
        checkpoint = CheckpointReference(
            context=target.execution.context,
            checkpoint_id=checkpoint_id,
            parent_checkpoint_id=parent_checkpoint_id,
            restored=restored,
            metadata=_json_mapping(metadata),
        )
        await self._record(
            target,
            target.execution.checkpoints,
            checkpoint,
            CheckpointEvent(
                context=target.execution.context,
                sequence=target._next_sequence(),
                checkpoint=checkpoint,
            ),
        )
        return checkpoint

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
        """Record a read from or write to long-term memory, by reference."""
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
        await self._persist_if_finished(target)
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
        """Record a provenance edge from an upstream ``source`` to a downstream ``target``.

        See [Concepts: Provenance](../concepts/provenance.md); walk the edges
        later with ``store.parents``, ``store.children``, and ``store.lineage``.

        Args:
            source_id: The upstream entity (e.g. a raw API response ID).
            target_id: The downstream entity derived from it.
            relation: How the target relates to the source, read
                ``target relation source``, e.g. ``"DERIVED_FROM"``.
            metadata: Additional JSON-safe fields; sanitized before storage.
            run: The run to record into; defaults to the current run.

        Returns:
            The recorded `ProvenanceLink`.
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

    async def record_artifact(
        self, artifact: SemanticArtifact, *, run: Run | None = None
    ) -> SemanticArtifact:
        """Record a semantic artifact built elsewhere and deliver it to plugins.

        The artifact is delivered as built: unlike the values passed to the
        ``record_*`` methods, it is not redacted again.

        Raises:
            ValueError: If the artifact belongs to a different run.
        """
        target = self._require_run(run)
        if artifact.context.run_id != target.execution.context.run_id:
            raise ValueError("artifact context does not match the active execution")
        await self._semantic(target, artifact)
        return artifact

    async def attribute(self, context: ExplanationContext) -> AttributionResult:
        """Run the registered `AttributionEngine` on ``context``.

        `explain` calls this when ``context.attribution`` is ``None``.

        Raises:
            XAIInstrumentationError: If the engine fails.
        """
        engine = self.registry.require(AttributionEngine)
        result = await self._run_operation(lambda: engine.attribute(context))
        if result is None:
            raise XAIInstrumentationError("attribution failed; see XAIRuntime.errors")
        return result

    async def explain(self, context: ExplanationContext) -> Explanation:
        """Assemble a policy-filtered explanation of ``context`` for ``context.audience``.

        The runtime (1) refuses an LLM-backed engine unless
        ``config.llm_explanation_enabled`` is set, (2) evaluates the registered
        `PolicyProvider` for ``PolicyAction.EXPOSE``, (3) runs `attribute` if
        ``context.attribution`` is ``None``, and (4) renders the result with the
        registered `ExplanationEngine`. See
        [Concepts: Explanations](../concepts/explanations.md).

        Raises:
            XAIInstrumentationError: If the LLM gate is closed, or the exposure
                policy, attribution, or explanation fails — in every failure
                mode, because an unfiltered or partial explanation is never
                returned.
        """
        engine = self.registry.require(ExplanationEngine)
        if engine.requires_llm and not self.config.llm_explanation_enabled:
            raise XAIInstrumentationError(
                "LLM explanation engine is registered but disabled in XAIConfig"
            )
        policy = self.registry.require(PolicyProvider)
        decision = await self._run_operation(lambda: policy.evaluate(context, PolicyAction.EXPOSE))
        if decision is None:
            raise XAIInstrumentationError(
                "exposure policy evaluation failed; see XAIRuntime.errors"
            )
        prepared = context.model_copy(update={"policies": [*context.policies, decision]})
        if prepared.attribution is None:
            prepared = prepared.model_copy(update={"attribution": await self.attribute(prepared)})
        explanation = await self._run_operation(lambda: engine.explain(prepared))
        if explanation is None:
            raise XAIInstrumentationError("explanation failed; see XAIRuntime.errors")
        return explanation

    async def explain_decision(
        self,
        decision: Decision,
        *,
        audience: Audience | str = Audience.DEVELOPER,
        run: Run | None = None,
    ) -> Explanation:
        """Explain a recorded decision using the evidence captured in its run.

        Builds the `ExplanationContext` from the run's live `Execution` and the
        evidence the decision (or its factors) references — or all of the run's
        evidence when it references none — then calls `explain`.

        Args:
            decision: A decision recorded with `record_decision`.
            audience: Who the explanation is for.
            run: The decision's run; defaults to the current run. Pass it
                explicitly after an instrumented call has returned (see
                `collect_runs`).

        Raises:
            ValueError: If ``decision`` belongs to a different run.
        """
        target = self._require_run(run)
        if decision.context.run_id != target.run_id:
            raise ValueError("decision does not belong to the given run")
        referenced = set(decision.evidence_ids)
        for factor in decision.factors:
            referenced.update(factor.evidence_ids)
        evidence = [item for item in target.evidence if not referenced or item.id in referenced]
        return await self.explain(
            ExplanationContext(
                execution=target.execution,
                decision=decision,
                evidence=evidence,
                audience=audience,
            )
        )

    async def flush(self) -> None:
        """Flush the observability provider and every plugin.

        Call this at natural checkpoints when a provider buffers events.
        """
        await self._call_optional(ObservabilityProvider, "flush")
        await self._run_operation(self.plugins.flush)

    async def close(self) -> None:
        """Flush, then close the store, the observability provider, and every plugin.

        Idempotent. Every step is attempted even if an earlier one fails; in
        ``FAIL_CLOSED``/``STRICT`` mode the first failure is raised afterwards.
        """
        if self._closed:
            return
        self._closed = True
        steps: tuple[Callable[[], Awaitable[object]], ...] = (
            lambda: self._call_optional(ObservabilityProvider, "flush"),
            lambda: self._run_operation(self.plugins.flush),
            lambda: self._call_optional(ProvenanceStore, "close"),
            lambda: self._call_optional(ObservabilityProvider, "close"),
            lambda: self._run_operation(self.plugins.close),
        )
        first_failure: XAIInstrumentationError | None = None
        for step in steps:
            try:
                await step()
            except XAIInstrumentationError as error:
                first_failure = first_failure or error
        if first_failure is not None:
            raise first_failure

    def run_sync[Result](self, coroutine: Coroutine[Any, Any, Result]) -> Result:
        """Run ``coroutine`` to completion from synchronous code.

        Reuses one event loop per thread and runs the coroutine in a copy of the
        caller's context, so context variables (for example an active
        OpenTelemetry span) propagate. When the calling thread is already
        running an event loop, the coroutine runs on a background loop that is
        kept for that thread and reused by later calls.
        """
        context = contextvars.copy_context()
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return _thread_runner().run(coroutine, context=context)
        return _thread_helper().run(coroutine, context)

    def _custom_selection(
        self, before: Mapping[str, Any], after: Mapping[str, Any]
    ) -> Mapping[str, Any] | None:
        capture = self.custom_state_capture
        if capture is None:
            raise ValueError("CaptureMode.CUSTOM requires custom_state_capture")
        try:
            return capture(before, after)
        except Exception as error:
            self._handle_failure(error)
            return None

    async def _event(self, event: CanonicalEvent) -> None:
        if await self._captured(event):
            await self._publish(event)

    async def _record(self, run: Run, records: list[Any], item: Any, event: CanonicalEvent) -> None:
        # A record the capture policy drops is kept nowhere, not even in the
        # Execution, so it cannot reach the store through the final snapshot.
        if not await self._captured(event):
            return
        records.append(item)
        await self._publish(event)
        await self._persist_if_finished(run)

    async def _captured(self, event: CanonicalEvent) -> bool:
        capture = self.registry.get(CapturePolicy)
        # The default policy allows every event, so it is not evaluated.
        if capture is None or type(capture) is DefaultCapturePolicy:
            return True
        decision = await self._run_operation(lambda: capture.evaluate(event))
        # An event whose policy could not be evaluated is not captured.
        return decision is not None and decision.allowed

    async def _publish(self, event: CanonicalEvent) -> None:
        await self._write(event)
        observer = self.registry.get(ObservabilityProvider)
        # The default provider discards every event, so nothing is sent to it.
        if observer is not None and type(observer) is not NoOpObservability:
            await self._run_operation(lambda: observer.emit(event))

    async def _write(self, item: Execution | ProvenanceLink | CanonicalEvent) -> None:
        store = self.registry.get(ProvenanceStore)
        if store is not None:
            await self._run_operation(lambda: store.write(item))
        elif (
            self.config.failure_mode is FailureMode.STRICT
            and self.registry.get(ObservabilityProvider) is None
        ):
            raise XAIInstrumentationError("strict mode requires a provenance or observability sink")

    async def _semantic(self, run: Run, artifact: SemanticArtifact) -> None:
        if not self.plugins.plugins and self.config.failure_mode is FailureMode.STRICT:
            raise XAIInstrumentationError("strict mode requires a plugin for semantic artifacts")
        run.artifacts.append(artifact)
        if self.plugins.plugins:
            await self._run_operation(lambda: self.plugins.record(artifact))

    async def _persist_if_finished(self, run: Run) -> None:
        # Records added after `finish_run` (e.g. an approval made outside the graph)
        # must not leave the stored Execution behind the in-memory one.
        if run.execution.ended_at is not None:
            await self._write(run.execution)

    async def _call_optional(self, capability: type[Any], method: str) -> None:
        provider = self.registry.get(capability)
        if provider is not None:
            await self._run_operation(lambda: getattr(provider, method)())

    async def _run_operation(self, operation: Callable[[], Awaitable[T]]) -> T | None:
        deadline = asyncio.get_running_loop().time() + self.config.operation_timeout_seconds
        acquired = False
        try:
            async with asyncio.timeout_at(deadline):
                await self._slots.acquire()
                acquired = True
                return await operation()
        except Exception as error:
            if isinstance(error, TimeoutError) and not acquired:
                error = TimeoutError("timed out waiting for an instrumentation slot")
            self._handle_failure(error)
            return None
        finally:
            if acquired:
                self._slots.release()

    def _handle_failure(self, error: Exception) -> None:
        self._errors.append(error)
        if self.config.failure_mode is not FailureMode.FAIL_OPEN:
            raise XAIInstrumentationError(
                f"instrumentation operation failed: {type(error).__name__}: {error}"
            ) from error

    def _resolve_run(self, run: Run | None) -> Run | None:
        return run or self.current_run

    def _require_run(self, run: Run | None) -> Run:
        target = self._resolve_run(run)
        if target is None:
            raise RuntimeError(
                "no active run: call this inside an instrumented graph call or pass run="
            )
        return target

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("runtime is closed")
