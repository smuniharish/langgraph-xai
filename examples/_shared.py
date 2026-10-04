"""Helpers shared by the example scripts."""

from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from langchain_openai import ChatOpenAI


@asynccontextmanager
async def chat_model() -> AsyncGenerator[ChatOpenAI, None]:
    """Yield the chat model used by the LLM-backed examples, closing its connections on exit.

    Configuration comes from the standard OpenAI environment variables, so any
    OpenAI-compatible endpoint works:

    - ``OPENAI_API_KEY`` (required)
    - ``OPENAI_BASE_URL`` (optional, for OpenAI-compatible gateways)
    - ``OPENAI_MODEL`` (optional, defaults to ``gpt-4o-mini``)
    """
    if not os.getenv("OPENAI_API_KEY"):
        raise SystemExit("Set OPENAI_API_KEY (and optionally OPENAI_BASE_URL and OPENAI_MODEL).")
    import openai
    from langchain_openai import ChatOpenAI

    async with openai.DefaultAsyncHttpxClient() as http_client:
        yield ChatOpenAI(
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"), http_async_client=http_client
        )


def show(title: str, payload: Any) -> None:
    """Print a titled, indented JSON block."""
    print(f"\n--- {title} ---")
    print(json.dumps(payload, indent=2, default=str))
