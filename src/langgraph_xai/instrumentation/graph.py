"""Transparent public-API graph instrumentation."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from langchain_core.runnables.config import RunnableConfig, merge_configs
from langgraph.types import Command

from langgraph_xai.core.models import HumanInteractionType
from langgraph_xai.runtime import Run, XAIRuntime

from .callbacks import AsyncXAICallbackHandler, XAICallbackHandler

Input = TypeVar("Input")
Output = TypeVar("Output")
logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator


def _configs(
    config: RunnableConfig | list[RunnableConfig] | None, count: int
) -> list[RunnableConfig | None]:
    if isinstance(config, list):
        if len(config) != count:
            raise ValueError("config must be a single config or a list matching inputs")
        return list(config)
    return [config] * count


def _is_resume(value: Any) -> bool:
    """A ``Command(resume=...)`` input continues a previously interrupted run."""
    return isinstance(value, Command) and value.resume is not None


def _extract_interrupts(output: Any) -> list[Any] | None:
    """LangGraph reports a pause as an ``__interrupt__`` key, not an exception."""
    if isinstance(output, Mapping):
        raw = output.get("__interrupt__")
        if raw:
            return list(raw)
    return None


class InstrumentedGraph[Input, Output]:
    """A proxy preserving the graph's standard execution methods and outputs."""

    def __init__(self, graph: Any, runtime: XAIRuntime) -> None:
        self.__wrapped__ = graph
        self.runtime = runtime

    def __getattr__(self, name: str) -> Any:
        return getattr(self.__wrapped__, name)

    def with_config(self, config: RunnableConfig | None = None, **kwargs: Any) -> InstrumentedGraph:
        return type(self)(self.__wrapped__.with_config(config, **kwargs), self.runtime)

    def invoke(self, input: Input, config: RunnableConfig | None = None, **kwargs: Any) -> Output:
        if self.runtime.is_instrumenting():
            return self.__wrapped__.invoke(input, config, **kwargs)
        run = self.runtime.run_sync(self.runtime.start_run(config))
        tokens = self.runtime.enter(run)
        try:
            if _is_resume(input):
                self.runtime.run_sync(
                    self.runtime.record_human_interaction(HumanInteractionType.RESUME, run=run)
                )
            output = self.__wrapped__.invoke(input, self._sync_config(config, run), **kwargs)
        except BaseException as error:
            self._finish_sync(run, error)
            raise
        else:
            self.runtime.run_sync(
                self.runtime.finish_run(run, interrupts=_extract_interrupts(output))
            )
            return output
        finally:
            self.runtime.exit(tokens)

    async def ainvoke(
        self, input: Input, config: RunnableConfig | None = None, **kwargs: Any
    ) -> Output:
        if self.runtime.is_instrumenting():
            return await self.__wrapped__.ainvoke(input, config, **kwargs)
        run = await self.runtime.start_run(config)
        tokens = self.runtime.enter(run)
        try:
            if _is_resume(input):
                await self.runtime.record_human_interaction(HumanInteractionType.RESUME, run=run)
            output = await self.__wrapped__.ainvoke(
                input, self._async_config(config, run), **kwargs
            )
        except asyncio.CancelledError as error:
            await self.runtime.finish_run(run, error, cancelled=True)
            raise
        except BaseException as error:
            await self._finish_async(run, error)
            raise
        else:
            await self.runtime.finish_run(run, interrupts=_extract_interrupts(output))
            return output
        finally:
            self.runtime.exit(tokens)

    def stream(
        self, input: Input, config: RunnableConfig | None = None, **kwargs: Any
    ) -> Iterator[Output]:
        if self.runtime.is_instrumenting():
            yield from self.__wrapped__.stream(input, config, **kwargs)
            return
        run = self.runtime.run_sync(self.runtime.start_run(config))
        tokens = self.runtime.enter(run)
        last_chunk: Any = None
        try:
            if _is_resume(input):
                self.runtime.run_sync(
                    self.runtime.record_human_interaction(HumanInteractionType.RESUME, run=run)
                )
            for chunk in self.__wrapped__.stream(input, self._sync_config(config, run), **kwargs):
                last_chunk = chunk
                yield chunk
        except GeneratorExit as error:
            self._finish_sync(run, error, cancelled=True)
            raise
        except BaseException as error:
            self._finish_sync(run, error)
            raise
        else:
            self.runtime.run_sync(
                self.runtime.finish_run(run, interrupts=_extract_interrupts(last_chunk))
            )
        finally:
            self.runtime.exit(tokens)

    async def astream(
        self, input: Input, config: RunnableConfig | None = None, **kwargs: Any
    ) -> AsyncIterator[Output]:
        if self.runtime.is_instrumenting():
            async for item in self.__wrapped__.astream(input, config, **kwargs):
                yield item
            return
        run = await self.runtime.start_run(config)
        tokens = self.runtime.enter(run)
        last_chunk: Any = None
        try:
            if _is_resume(input):
                await self.runtime.record_human_interaction(HumanInteractionType.RESUME, run=run)
            async for item in self.__wrapped__.astream(
                input, self._async_config(config, run), **kwargs
            ):
                last_chunk = item
                yield item
        except (GeneratorExit, asyncio.CancelledError) as error:
            await self.runtime.finish_run(run, error, cancelled=True)
            raise
        except BaseException as error:
            await self._finish_async(run, error)
            raise
        else:
            await self.runtime.finish_run(run, interrupts=_extract_interrupts(last_chunk))
        finally:
            self.runtime.exit(tokens)

    def batch(
        self,
        inputs: list[Input],
        config: RunnableConfig | list[RunnableConfig] | None = None,
        *,
        return_exceptions: bool = False,
        **kwargs: Any,
    ) -> list[Output]:
        if self.runtime.is_instrumenting():
            return self.__wrapped__.batch(
                inputs, config, return_exceptions=return_exceptions, **kwargs
            )
        configs = _configs(config, len(inputs))
        runs = [self.runtime.run_sync(self.runtime.start_run(item)) for item in configs]
        for item, run in zip(inputs, runs, strict=True):
            if _is_resume(item):
                self.runtime.run_sync(
                    self.runtime.record_human_interaction(HumanInteractionType.RESUME, run=run)
                )
        prepared = [self._sync_config(item, run) for item, run in zip(configs, runs, strict=True)]
        try:
            outputs = self.__wrapped__.batch(
                inputs, prepared, return_exceptions=return_exceptions, **kwargs
            )
        except BaseException as error:
            for run in runs:
                self._finish_sync(run, error)
            raise
        for run, output in zip(runs, outputs, strict=True):
            self.runtime.run_sync(
                self.runtime.finish_run(
                    run,
                    output if isinstance(output, BaseException) else None,
                    interrupts=_extract_interrupts(output),
                )
            )
        return outputs

    async def abatch(
        self,
        inputs: list[Input],
        config: RunnableConfig | list[RunnableConfig] | None = None,
        *,
        return_exceptions: bool = False,
        **kwargs: Any,
    ) -> list[Output]:
        if self.runtime.is_instrumenting():
            return await self.__wrapped__.abatch(
                inputs, config, return_exceptions=return_exceptions, **kwargs
            )
        configs = _configs(config, len(inputs))
        runs = list(await asyncio.gather(*(self.runtime.start_run(item) for item in configs)))
        await asyncio.gather(
            *(
                self.runtime.record_human_interaction(HumanInteractionType.RESUME, run=run)
                for item, run in zip(inputs, runs, strict=True)
                if _is_resume(item)
            )
        )
        prepared = [self._async_config(item, run) for item, run in zip(configs, runs, strict=True)]
        try:
            outputs = await self.__wrapped__.abatch(
                inputs, prepared, return_exceptions=return_exceptions, **kwargs
            )
        except asyncio.CancelledError as error:
            await asyncio.gather(
                *(self.runtime.finish_run(run, error, cancelled=True) for run in runs)
            )
            raise
        except BaseException as error:
            await asyncio.gather(*(self._finish_async(run, error) for run in runs))
            raise
        await asyncio.gather(
            *(
                self.runtime.finish_run(
                    run,
                    output if isinstance(output, BaseException) else None,
                    interrupts=_extract_interrupts(output),
                )
                for run, output in zip(runs, outputs, strict=True)
            )
        )
        return outputs

    def _sync_config(self, config: RunnableConfig | None, run: Run) -> RunnableConfig:
        return merge_configs(config, {"callbacks": [XAICallbackHandler(self.runtime, run)]})

    def _async_config(self, config: RunnableConfig | None, run: Run) -> RunnableConfig:
        return merge_configs(config, {"callbacks": [AsyncXAICallbackHandler(self.runtime, run)]})

    def _finish_sync(self, run: Run, original: BaseException, *, cancelled: bool = False) -> None:
        try:
            self.runtime.run_sync(self.runtime.finish_run(run, original, cancelled=cancelled))
        except BaseException:
            logger.exception("Failed to finalize xAI instrumentation after business failure")

    async def _finish_async(self, run: Run, original: BaseException) -> None:
        try:
            await self.runtime.finish_run(run, original)
        except BaseException:
            logger.exception("Failed to finalize xAI instrumentation after business failure")


def instrument(
    graph: Any, runtime: XAIRuntime | None = None, **runtime_kwargs: Any
) -> InstrumentedGraph:
    """Wrap a graph without patching LangGraph internals."""
    if isinstance(graph, InstrumentedGraph):
        if runtime is None or graph.runtime is runtime:
            return graph
        graph = graph.__wrapped__
    return InstrumentedGraph(graph, runtime or XAIRuntime(**runtime_kwargs))
