"""Transparent instrumentation of LangGraph graphs through their public Runnable API."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from concurrent.futures import FIRST_COMPLETED, wait
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, overload
from uuid import UUID

from langchain_core.runnables.config import (
    get_config_list,
    get_executor_for_config,
    merge_configs,
)
from langchain_core.runnables.utils import gather_with_concurrency
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.pregel import Pregel
from langgraph.types import Command

from langgraph_xai.core.models import HumanInteractionType
from langgraph_xai.runtime.runtime import RUN_ID_METADATA_KEY, XAIInstrumentationError

from .callbacks import _AsyncXAICallbackHandler, _XAICallbackHandler

if TYPE_CHECKING:
    from collections.abc import (
        AsyncGenerator,
        AsyncIterator,
        Awaitable,
        Callable,
        Generator,
        Iterator,
        Sequence,
    )

    from langchain_core.runnables import Runnable
    from langchain_core.runnables.config import RunnableConfig
    from langchain_core.runnables.schema import StreamEvent
    from langgraph.types import Interrupt, StateSnapshot

    from langgraph_xai.runtime import Run, XAIRuntime

    from .callbacks import _Capture

logger = logging.getLogger(__name__)

_CANCELLATIONS = (GeneratorExit, KeyboardInterrupt, asyncio.CancelledError)
# Checkpoints written by update_state() or a fork belong to no run; their parents lead to one.
_EDIT_SOURCES = frozenset({"update", "fork"})
_NO_INPUT: Any = object()


def _combine(final: Any, chunk: Any) -> Any:
    """Add an input chunk to the chunks before it, as ``Runnable.transform`` does."""
    try:
        return final + chunk
    except TypeError:
        return chunk


def _checkpoint_id(config: RunnableConfig | None) -> str | None:
    return None if config is None else config.get("configurable", {}).get("checkpoint_id")


def _writer(snapshot: StateSnapshot) -> UUID | None:
    """The ID of the run that wrote this checkpoint, from its metadata."""
    value = (snapshot.metadata or {}).get(RUN_ID_METADATA_KEY)
    try:
        return None if value is None else UUID(str(value))
    except ValueError:
        return None


@dataclass(frozen=True, slots=True)
class _Thread:
    """The thread of a checkpointed graph, read through the graph's public state API."""

    graph: Pregel
    configurable: dict[str, Any]
    sync: bool

    @property
    def requested(self) -> RunnableConfig:
        """The state the call starts from: the latest, or the checkpoint it names."""
        return {"configurable": self.configurable}

    @property
    def pinned(self) -> bool:
        """Whether the call names a checkpoint to replay or fork from."""
        return self.configurable.get("checkpoint_id") is not None

    @property
    def latest(self) -> RunnableConfig:
        configurable = {
            key: value for key, value in self.configurable.items() if key != "checkpoint_id"
        }
        return {"configurable": configurable}

    async def read(self, config: RunnableConfig) -> StateSnapshot:
        if self.sync:
            return await asyncio.to_thread(self.graph.get_state, config)
        return await self.graph.aget_state(config)


@dataclass(frozen=True, slots=True)
class _Call:
    """One recorded top-level call."""

    run: Run
    capture: _Capture
    config: RunnableConfig
    thread: _Thread | None


class InstrumentedGraph[Input, Output]:
    """A transparent proxy that records every run of the wrapped graph.

    ``invoke``, ``ainvoke``, ``stream``, ``astream``, ``astream_events``,
    ``batch``, ``abatch``, ``batch_as_completed``, ``abatch_as_completed``,
    ``transform``, and ``atransform`` return exactly what the wrapped graph
    returns. Each top-level call (each input, for batches) records one
    `Execution` with its nodes, state changes, tool calls, retrievals,
    interrupts, and, for a checkpointed graph, its checkpoints. While a call
    runs, `XAIRuntime.current_run` returns its `Run` inside the graph's nodes,
    tools, and middleware. A call made while another call of the same runtime
    is active is treated as nested and passes straight through.

    LangGraph's experimental v3 streaming protocol (``stream_events`` and
    ``astream_events(version="v3")``) and LangChain's deprecated
    ``astream_log`` cannot be recorded. They reach the wrapped graph unchanged
    and count as failed instrumentation operations, handled by
    `XAIConfig.failure_mode`.

    The wrapped graph receives the run's ID in its config metadata under
    `RUN_ID_METADATA_KEY`. Every other attribute (``get_state``,
    ``update_state``, ``get_graph``, ...) is proxied to the wrapped graph
    without instrumentation; `with_config` returns a new instrumented proxy.
    """

    def __init__(self, graph: Runnable[Input, Output], runtime: XAIRuntime) -> None:
        self.__wrapped__ = graph
        self.runtime = runtime

    def __getattr__(self, name: str) -> Any:
        return getattr(self.__wrapped__, name)

    def with_config(
        self, config: RunnableConfig | None = None, **kwargs: Any
    ) -> InstrumentedGraph[Input, Output]:
        """Return an instrumented proxy of ``graph.with_config(...)``."""
        return type(self)(self.__wrapped__.with_config(config, **kwargs), self.runtime)

    def invoke(self, input: Input, config: RunnableConfig | None = None, **kwargs: Any) -> Output:
        """Run the graph synchronously and record the run."""
        if self.runtime._is_instrumenting():
            return self.__wrapped__.invoke(input, config, **kwargs)
        with self._recorded(input, config) as call:
            return self._within(call.run, self.__wrapped__.invoke, input, call.config, **kwargs)

    async def ainvoke(
        self, input: Input, config: RunnableConfig | None = None, **kwargs: Any
    ) -> Output:
        """Run the graph asynchronously and record the run."""
        if self.runtime._is_instrumenting():
            return await self.__wrapped__.ainvoke(input, config, **kwargs)
        async with self._arecorded(input, config) as call:
            tokens = self.runtime._enter(call.run)
            try:
                return await self.__wrapped__.ainvoke(input, call.config, **kwargs)
            finally:
                self.runtime._exit(tokens)

    def stream(
        self, input: Input, config: RunnableConfig | None = None, **kwargs: Any
    ) -> Generator[Output, None, None]:
        """Stream the graph synchronously and record the run.

        Chunks are yielded unchanged, for every ``stream_mode``. Closing the
        stream before it is exhausted records the run as cancelled.
        """
        if self.runtime._is_instrumenting():
            yield from self.__wrapped__.stream(input, config, **kwargs)
            return
        with self._recorded(input, config) as call:
            chunks = self._within(call.run, self.__wrapped__.stream, input, call.config, **kwargs)
            try:
                while True:
                    try:
                        chunk = self._within(call.run, next, chunks)
                    except StopIteration:
                        break
                    yield chunk
            finally:
                if (close := getattr(chunks, "close", None)) is not None:
                    close()

    def astream(
        self, input: Input, config: RunnableConfig | None = None, **kwargs: Any
    ) -> AsyncGenerator[Output, None]:
        """Stream the graph asynchronously and record the run.

        Chunks are yielded unchanged, for every ``stream_mode``. Closing the
        stream before it is exhausted, or cancelling the consuming task,
        records the run as cancelled.
        """
        return self._arecorded_stream(self.__wrapped__.astream, input, config, kwargs)

    @overload
    def astream_events(
        self,
        input: Input,
        config: RunnableConfig | None = None,
        *,
        version: Literal["v1", "v2"] = "v2",
        **kwargs: Any,
    ) -> AsyncGenerator[StreamEvent, None]: ...

    @overload
    def astream_events(
        self,
        input: Input,
        config: RunnableConfig | None = None,
        *,
        version: Literal["v3"],
        **kwargs: Any,
    ) -> Awaitable[Any]: ...

    def astream_events(
        self,
        input: Input,
        config: RunnableConfig | None = None,
        *,
        version: Literal["v1", "v2", "v3"] = "v2",
        **kwargs: Any,
    ) -> AsyncGenerator[StreamEvent, None] | Awaitable[Any]:
        """Stream the graph's events asynchronously and record the run.

        For ``version="v1"`` and ``"v2"``, events are yielded unchanged, and
        closing the stream before it is exhausted, or cancelling the consuming
        task, records the run as cancelled. ``version="v3"``, LangGraph's
        experimental streaming protocol, runs inside LangGraph where it cannot
        be recorded; it is handled like `stream_events`.
        """
        if version == "v3":
            self._unrecorded("astream_events(version='v3')", "version='v2'")
            return self.__wrapped__.astream_events(input, config, version=version, **kwargs)
        return self._arecorded_stream(
            self.__wrapped__.astream_events, input, config, {"version": version, **kwargs}
        )

    def stream_events(
        self, input: Input, config: RunnableConfig | None = None, **kwargs: Any
    ) -> Any:
        """Pass the call to the wrapped graph without recording it.

        A LangGraph graph implements ``stream_events`` only for the experimental
        ``version="v3"`` protocol, which runs inside LangGraph where it cannot be
        recorded. The unrecorded call is a failed instrumentation operation:
        under ``FAIL_OPEN`` it is kept in `XAIRuntime.errors` and the graph
        runs; under ``FAIL_CLOSED`` and ``STRICT`` it raises
        `XAIInstrumentationError` and the graph does not run. To record the
        run, use `stream` or `astream_events`.
        """
        self._unrecorded("stream_events", "stream() or astream_events()")
        return self.__wrapped__.stream_events(input, config, **kwargs)

    def astream_log(self, input: Input, config: RunnableConfig | None = None, **kwargs: Any) -> Any:
        """Pass the call to the wrapped graph without recording it.

        LangChain deprecates ``astream_log``. The call is handled like
        `stream_events`; use `astream` or `astream_events` to record the run.
        """
        self._unrecorded("astream_log", "astream() or astream_events()")
        return self.__wrapped__.astream_log(input, config, **kwargs)

    def transform(
        self, input: Iterator[Input], config: RunnableConfig | None = None, **kwargs: Any
    ) -> Generator[Output, None, None]:
        """Combine the input chunks and stream the graph through `stream`, recording the run.

        Like ``Runnable.transform``, chunks are combined with ``+``, and a chunk
        that cannot be added replaces the chunks before it. An empty input runs
        nothing.
        """
        chunks = iter(input)
        if (final := next(chunks, _NO_INPUT)) is _NO_INPUT:
            return
        for chunk in chunks:
            final = _combine(final, chunk)
        yield from self.stream(final, config, **kwargs)

    async def atransform(
        self, input: AsyncIterator[Input], config: RunnableConfig | None = None, **kwargs: Any
    ) -> AsyncGenerator[Output, None]:
        """Combine the input chunks and stream the graph through `astream`, recording the run.

        Chunks are combined like `transform`. An empty input runs nothing.
        """
        final: Any = _NO_INPUT
        async for chunk in input:
            final = chunk if final is _NO_INPUT else _combine(final, chunk)
        if final is _NO_INPUT:
            return
        outputs = self.astream(final, config, **kwargs)
        try:
            async for output in outputs:
                yield output
        finally:
            await outputs.aclose()

    def batch(
        self,
        inputs: list[Input],
        config: RunnableConfig | list[RunnableConfig] | None = None,
        *,
        return_exceptions: bool = False,
        **kwargs: Any,
    ) -> list[Output]:
        """Run every input through the instrumented `invoke`, like ``Runnable.batch``.

        Each input gets its own recorded run. ``max_concurrency`` in the config
        is honored.
        """
        if self.runtime._is_instrumenting():
            return self.__wrapped__.batch(
                inputs, config, return_exceptions=return_exceptions, **kwargs
            )
        if not inputs:
            return []
        configs = get_config_list(config, len(inputs))
        invoke = self._invoker(return_exceptions=return_exceptions, kwargs=kwargs)
        if len(inputs) == 1:
            return [invoke(inputs[0], configs[0])]
        with get_executor_for_config(configs[0]) as executor:
            return list(executor.map(invoke, inputs, configs))

    async def abatch(
        self,
        inputs: list[Input],
        config: RunnableConfig | list[RunnableConfig] | None = None,
        *,
        return_exceptions: bool = False,
        **kwargs: Any,
    ) -> list[Output]:
        """Run every input through the instrumented `ainvoke`, like ``Runnable.abatch``.

        Each input gets its own recorded run. ``max_concurrency`` in the config
        is honored.
        """
        if self.runtime._is_instrumenting():
            return await self.__wrapped__.abatch(
                inputs, config, return_exceptions=return_exceptions, **kwargs
            )
        if not inputs:
            return []
        configs = get_config_list(config, len(inputs))
        ainvoke = self._ainvoker(return_exceptions=return_exceptions, kwargs=kwargs)
        return await gather_with_concurrency(
            configs[0].get("max_concurrency"), *map(ainvoke, inputs, configs)
        )

    def batch_as_completed(
        self,
        inputs: Sequence[Input],
        config: RunnableConfig | Sequence[RunnableConfig] | None = None,
        *,
        return_exceptions: bool = False,
        **kwargs: Any,
    ) -> Generator[tuple[int, Output | Exception], None, None]:
        """Run every input through the instrumented `invoke`, yielding ``(index, output)`` pairs.

        Pairs are yielded as runs finish, like ``Runnable.batch_as_completed``.
        Each input gets its own recorded run. Closing the generator early
        cancels the inputs that have not started.
        """
        if self.runtime._is_instrumenting():
            yield from self.__wrapped__.batch_as_completed(
                inputs, config, return_exceptions=return_exceptions, **kwargs
            )
            return
        if not inputs:
            return
        configs = get_config_list(config, len(inputs))
        invoke = self._invoker(return_exceptions=return_exceptions, kwargs=kwargs)
        if len(inputs) == 1:
            yield 0, invoke(inputs[0], configs[0])
            return
        with get_executor_for_config(configs[0]) as executor:
            futures = {
                executor.submit(invoke, item, item_config): index
                for index, (item, item_config) in enumerate(zip(inputs, configs, strict=True))
            }
            pending = set(futures)
            try:
                while pending:
                    done, pending = wait(pending, return_when=FIRST_COMPLETED)
                    for future in done:
                        yield futures[future], future.result()
            finally:
                for future in pending:
                    future.cancel()

    async def abatch_as_completed(
        self,
        inputs: Sequence[Input],
        config: RunnableConfig | Sequence[RunnableConfig] | None = None,
        *,
        return_exceptions: bool = False,
        **kwargs: Any,
    ) -> AsyncGenerator[tuple[int, Output | Exception], None]:
        """Run every input through the instrumented `ainvoke`, yielding ``(index, output)`` pairs.

        Pairs are yielded as runs finish, like ``Runnable.abatch_as_completed``.
        Each input gets its own recorded run, and ``max_concurrency`` in the
        config is honored. Closing the generator early cancels the remaining
        runs, which are recorded as cancelled.
        """
        if self.runtime._is_instrumenting():
            async for pair in self.__wrapped__.abatch_as_completed(
                inputs, config, return_exceptions=return_exceptions, **kwargs
            ):
                yield pair
            return
        if not inputs:
            return
        configs = get_config_list(config, len(inputs))
        ainvoke = self._ainvoker(return_exceptions=return_exceptions, kwargs=kwargs)
        limit = configs[0].get("max_concurrency")
        slots = asyncio.Semaphore(limit) if limit else contextlib.nullcontext()

        async def indexed(
            index: int, item: Input, item_config: RunnableConfig
        ) -> tuple[int, Output | Exception]:
            async with slots:
                return index, await ainvoke(item, item_config)

        tasks = [
            asyncio.ensure_future(indexed(index, item, item_config))
            for index, (item, item_config) in enumerate(zip(inputs, configs, strict=True))
        ]
        try:
            for finished in asyncio.as_completed(tasks):
                yield await finished
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _arecorded_stream(
        self,
        stream: Callable[..., AsyncIterator[Any]],
        input: Input,
        config: RunnableConfig | None,
        kwargs: dict[str, Any],
    ) -> AsyncGenerator[Any, None]:
        if self.runtime._is_instrumenting():
            async for item in stream(input, config, **kwargs):
                yield item
            return
        async with self._arecorded(input, config) as call:
            items = self._within(call.run, stream, input, call.config, **kwargs)
            try:
                while True:
                    tokens = self.runtime._enter(call.run)
                    try:
                        item = await anext(items)
                    except StopAsyncIteration:
                        break
                    finally:
                        self.runtime._exit(tokens)
                    yield item
            finally:
                if (aclose := getattr(items, "aclose", None)) is not None:
                    await aclose()

    def _unrecorded(self, call: str, alternative: str) -> None:
        """Treat a top-level call that cannot be recorded as a failed instrumentation operation."""
        if not self.runtime._is_instrumenting():
            self.runtime._handle_failure(
                NotImplementedError(f"{call} is not recorded by langgraph-xai; use {alternative}")
            )

    def _invoker(
        self, *, return_exceptions: bool, kwargs: dict[str, Any]
    ) -> Callable[[Input, RunnableConfig], Any]:
        def invoke(item: Input, item_config: RunnableConfig) -> Any:
            if not return_exceptions:
                return self.invoke(item, item_config, **kwargs)
            try:
                return self.invoke(item, item_config, **kwargs)
            except Exception as error:
                return error

        return invoke

    def _ainvoker(
        self, *, return_exceptions: bool, kwargs: dict[str, Any]
    ) -> Callable[[Input, RunnableConfig], Any]:
        async def ainvoke(item: Input, item_config: RunnableConfig) -> Any:
            if not return_exceptions:
                return await self.ainvoke(item, item_config, **kwargs)
            try:
                return await self.ainvoke(item, item_config, **kwargs)
            except Exception as error:
                return error

        return ainvoke

    @contextlib.contextmanager
    def _recorded(self, input: Any, config: RunnableConfig | None) -> Generator[_Call, None, None]:
        call, snapshot = self.runtime.run_sync(self._begin(input, config, sync=True))
        try:
            self.runtime.run_sync(self._continued(call, input, snapshot))
            yield call
        except BaseException as error:
            try:
                self.runtime.run_sync(
                    self._end(call, error, cancelled=isinstance(error, _CANCELLATIONS))
                )
            except Exception:
                logger.exception("Failed to record the outcome of a failed graph run")
            raise
        self.runtime.run_sync(self._end(call))

    @contextlib.asynccontextmanager
    async def _arecorded(
        self, input: Any, config: RunnableConfig | None
    ) -> AsyncGenerator[_Call, None]:
        call, snapshot = await self._begin(input, config, sync=False)
        try:
            await self._continued(call, input, snapshot)
            yield call
        except BaseException as error:
            try:
                await self._end(call, error, cancelled=isinstance(error, _CANCELLATIONS))
            except Exception:
                logger.exception("Failed to record the outcome of a failed graph run")
            raise
        await self._end(call)

    async def _begin(
        self, input: Any, config: RunnableConfig | None, *, sync: bool
    ) -> tuple[_Call, StateSnapshot | None]:
        thread = self._thread(config, sync=sync)
        snapshot: StateSnapshot | None = None
        origin: UUID | None = None
        # Like LangGraph, treat None or a Command as continuing the thread's saved state.
        if thread is not None and (input is None or isinstance(input, Command)):
            snapshot = await self._read(thread, thread.requested)
            if snapshot is not None and snapshot.metadata is not None:
                origin = await self._origin(thread, snapshot)
        run = await self.runtime.start_run(config, continuation_of=origin)
        handler = (
            _XAICallbackHandler(self.runtime, run)
            if sync
            else _AsyncXAICallbackHandler(self.runtime, run)
        )
        graph_config = merge_configs(
            config,
            {"callbacks": [handler], "metadata": {RUN_ID_METADATA_KEY: str(run.run_id)}},
        )
        return _Call(run, handler.capture, graph_config, thread), snapshot

    async def _continued(self, call: _Call, input: Any, snapshot: StateSnapshot | None) -> None:
        # A snapshot without metadata means the thread has no checkpoint to continue.
        restored = None if snapshot is None or snapshot.metadata is None else snapshot
        if restored is not None:
            await self._checkpoint(call.run, restored, restored=True)
        if isinstance(input, Command) and input.resume is not None:
            if snapshot is not None and restored is None:
                return
            pending = () if restored is None else restored.interrupts
            await self.runtime.record_human_interaction(
                HumanInteractionType.RESUME,
                request_reference=pending[0].id if len(pending) == 1 else None,
                metadata={"value": input.resume},
                run=call.run,
            )
        elif (
            input is None
            and restored is not None
            and call.thread is not None
            and not call.thread.pinned
            and restored.next
            and not restored.interrupts
            and not any(task.error for task in restored.tasks)
        ):
            # Continuing the latest checkpoint past a static breakpoint
            # (interrupt_before/interrupt_after), not retrying a failure or replaying history.
            await self.runtime.record_human_interaction(
                HumanInteractionType.RESUME,
                metadata={"pending_nodes": list(restored.next)},
                run=call.run,
            )

    async def _end(
        self, call: _Call, error: BaseException | None = None, *, cancelled: bool = False
    ) -> None:
        interrupts: list[Interrupt] = list(call.capture.interrupts.values())
        pending: Sequence[str] = ()
        failure: XAIInstrumentationError | None = None
        if call.thread is not None and not cancelled:
            try:
                latest = await self._read(call.thread, call.thread.latest)
            except XAIInstrumentationError as exc:
                latest, failure = None, exc
            if latest is not None:
                if _writer(latest) == call.run.run_id:
                    await self._checkpoint(call.run, latest, restored=False)
                interrupts.extend(
                    item for item in latest.interrupts if item.id not in call.capture.interrupts
                )
                pending = latest.next
        await self.runtime.finish_run(
            call.run, error, cancelled=cancelled, interrupts=interrupts, pending_nodes=pending
        )
        if failure is not None:
            raise failure

    def _thread(self, config: RunnableConfig | None, *, sync: bool) -> _Thread | None:
        graph = self.__wrapped__
        if not (
            self.runtime.config.capture_checkpoints
            and isinstance(graph, Pregel)
            and isinstance(graph.checkpointer, BaseCheckpointSaver)
        ):
            return None
        configurable = merge_configs(graph.config, config).get("configurable", {})
        if configurable.get("thread_id") is None:
            return None
        return _Thread(graph, dict(configurable), sync)

    async def _read(self, thread: _Thread, config: RunnableConfig) -> StateSnapshot | None:
        return await self.runtime._run_operation(lambda: thread.read(config))

    async def _origin(self, thread: _Thread, snapshot: StateSnapshot) -> UUID | None:
        current: StateSnapshot | None = snapshot
        visited: set[str | None] = set()
        while current is not None and current.metadata is not None:
            if (writer := _writer(current)) is not None:
                return writer
            parent = current.parent_config
            # Stop at a run's own checkpoint, the first checkpoint, or a (corrupt) cycle.
            if (
                current.metadata.get("source") not in _EDIT_SOURCES
                or not parent
                or _checkpoint_id(parent) in visited
            ):
                return None
            visited.add(_checkpoint_id(parent))
            current = await self._read(thread, parent)
        return None

    async def _checkpoint(self, run: Run, snapshot: StateSnapshot, *, restored: bool) -> None:
        # A saved checkpoint's snapshot always names it in its config.
        metadata = snapshot.metadata or {}
        await self.runtime.record_checkpoint(
            snapshot.config["configurable"]["checkpoint_id"],
            parent_checkpoint_id=_checkpoint_id(snapshot.parent_config),
            restored=restored,
            metadata={key: metadata[key] for key in ("source", "step") if key in metadata},
            run=run,
        )

    def _within[Result](
        self, run: Run, function: Callable[..., Result], *args: Any, **kwargs: Any
    ) -> Result:
        tokens = self.runtime._enter(run)
        try:
            return function(*args, **kwargs)
        finally:
            self.runtime._exit(tokens)
