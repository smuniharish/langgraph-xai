"""Verify the real behavioral difference between the three failure modes.

xgraph's own instrumentation can fail (a storage write times out, an
observability exporter is unreachable, ...). ``XAIConfig.failure_mode``
controls what happens next -- and this script proves each mode's real,
distinct behavior against the same broken ``ProvenanceStore`` rather than
describing it in prose.

Run with:

    uv run python examples/failure_modes_real.py
"""

import asyncio

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel

from langgraph_xai import XAIConfig, XAIRuntime
from langgraph_xai.core import CanonicalEvent, Execution, ProvenanceStore
from langgraph_xai.runtime.runtime import XAIInstrumentationError


class State(BaseModel):
    value: int


def graph():
    builder = StateGraph(State)
    builder.add_node("increment", lambda state: {"value": state.value + 1})
    builder.add_edge(START, "increment")
    builder.add_edge("increment", END)
    return builder.compile()


class BrokenStore:
    """A ProvenanceStore that always fails, to exercise failure modes for real."""

    async def write(self, item: Execution | CanonicalEvent) -> None:
        raise ConnectionError("simulated storage outage")

    async def get(self, entity_id: str) -> None:  # pragma: no cover - unused
        return None

    async def query(self, *args: object, **kwargs: object):  # pragma: no cover - unused
        return
        yield  # pragma: no cover

    async def parents(self, *args: object, **kwargs: object) -> list[object]:  # pragma: no cover
        return []

    async def children(self, *args: object, **kwargs: object) -> list[object]:  # pragma: no cover
        return []

    async def lineage(self, *args: object, **kwargs: object) -> list[object]:  # pragma: no cover
        return []

    async def close(self) -> None:  # pragma: no cover - unused
        return None


async def run_with(mode: str) -> None:
    runtime = XAIRuntime(config=XAIConfig(failure_mode=mode), graph_id="failure-mode-demo")
    runtime.register(ProvenanceStore, BrokenStore())

    print(f"\n--- failure_mode={mode!r} ---")
    try:
        result = await runtime.instrument(graph()).ainvoke({"value": 1})
        print(f"ainvoke succeeded despite the broken store: {result}")
        print(f"runtime captured {len(runtime.errors)} suppressed error(s):")
        for error in runtime.errors:
            print(f"  - {type(error).__name__}: {error}")
    except XAIInstrumentationError as exc:
        print(f"ainvoke raised as expected: {type(exc).__name__}: {exc}")
        print(f"__cause__: {type(exc.__cause__).__name__}: {exc.__cause__}")


async def main() -> None:
    await run_with("fail_open")
    await run_with("fail_closed")
    await run_with("strict")


if __name__ == "__main__":
    asyncio.run(main())
