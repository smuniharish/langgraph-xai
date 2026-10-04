import asyncio
import contextvars
import threading

import pytest

from langgraph_xai import XAIRuntime
from langgraph_xai.runtime import runtime as runtime_module

marker: contextvars.ContextVar[str] = contextvars.ContextVar("marker", default="unset")


async def current_loop() -> asyncio.AbstractEventLoop:
    return asyncio.get_running_loop()


async def read_marker() -> str:
    return marker.get()


async def fail() -> None:
    raise LookupError("boom")


def test_run_sync_reuses_one_loop_per_thread() -> None:
    xai = XAIRuntime()

    first, second = xai.run_sync(current_loop()), xai.run_sync(current_loop())
    other: list[asyncio.AbstractEventLoop] = []
    thread = threading.Thread(target=lambda: other.append(xai.run_sync(current_loop())))
    thread.start()
    thread.join()

    assert first is second
    assert other[0] is not first


def test_run_sync_propagates_context_variables_and_errors() -> None:
    xai = XAIRuntime()
    token = marker.set("caller")
    try:
        assert xai.run_sync(read_marker()) == "caller"
    finally:
        marker.reset(token)

    with pytest.raises(LookupError, match="boom"):
        xai.run_sync(fail())


async def test_run_sync_inside_a_running_loop_reuses_one_helper_loop_per_thread() -> None:
    xai = XAIRuntime()
    token = marker.set("async-caller")
    try:
        assert xai.run_sync(read_marker()) == "async-caller"
        helper = xai.run_sync(current_loop())
        assert helper is not asyncio.get_running_loop()
        assert xai.run_sync(current_loop()) is helper
        with pytest.raises(LookupError, match="boom"):
            xai.run_sync(fail())
    finally:
        marker.reset(token)


async def test_run_sync_can_be_nested_inside_the_helper_loop() -> None:
    xai = XAIRuntime()

    async def nested() -> str:
        return xai.run_sync(read_marker())

    token = marker.set("outer")
    try:
        assert xai.run_sync(nested()) == "outer"
    finally:
        marker.reset(token)


def test_helper_loops_stop_and_close_when_released() -> None:
    helper = runtime_module._HelperLoop()
    loop = helper.loop

    del helper
    for _ in range(500):
        if loop.is_closed():
            break
        threading.Event().wait(0.01)

    assert loop.is_closed()
    runtime_module._stop(loop)


def test_thread_loops_are_closed_when_released() -> None:
    holder = runtime_module._ThreadLoop()
    loop = holder.loop

    del holder

    assert loop.is_closed()

    already_closed = runtime_module._ThreadLoop()
    already_closed.loop.close()
    already_closed.__del__()

    assert already_closed.loop.is_closed()


def test_exit_tolerates_tokens_from_another_context() -> None:
    xai = XAIRuntime()
    run = xai.run_sync(xai.start_run())
    tokens = contextvars.copy_context().run(xai._enter, run)

    xai._exit(tokens)
    tokens = xai._enter(run)
    xai._exit(tokens)
    xai._exit(tokens)

    assert xai.current_run is None
    assert not xai._is_instrumenting()
