"""Compare the three failure modes against the same unavailable storage backend.

``XAIConfig.failure_mode`` decides what happens when explainability infrastructure
fails: ``fail_open`` keeps the application running and records the error,
``fail_closed`` raises ``XAIInstrumentationError`` from the graph call, and
``strict`` does the same while also requiring a plugin for semantic artifacts.

Run with:

    uv run python examples/failure_modes.py
"""

import asyncio
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from langgraph_xai import (
    FailureMode,
    InMemoryProvenanceStore,
    ProvenanceStore,
    XAIConfig,
    XAIInstrumentationError,
    XAIRuntime,
)


class State(TypedDict):
    value: int


class UnavailableStore(InMemoryProvenanceStore):
    """A store whose backend is down."""

    async def write(self, item: object) -> None:
        raise ConnectionError("storage backend unavailable")


def build_graph():
    builder = StateGraph(State)
    builder.add_node("increment", lambda state: {"value": state["value"] + 1})
    builder.add_edge(START, "increment")
    builder.add_edge("increment", END)
    return builder.compile()


async def run_with(mode: FailureMode) -> None:
    xai = XAIRuntime(config=XAIConfig(failure_mode=mode), graph_id="failure-modes")
    xai.register(ProvenanceStore, UnavailableStore())
    print(f"\n--- failure_mode={mode.value} ---")
    try:
        result = await xai.instrument(build_graph()).ainvoke({"value": 1})
    except XAIInstrumentationError as error:
        print(f"graph call raised {type(error).__name__}: {error}")
    else:
        print(f"graph call returned {result}")
    print(f"runtime.errors holds {len(xai.errors)} error(s); first: {xai.errors[0]!r}")


async def main() -> None:
    for mode in FailureMode:
        await run_with(mode)


if __name__ == "__main__":
    asyncio.run(main())
