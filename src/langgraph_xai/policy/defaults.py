"""Conservative default capture and exposure policies."""

from __future__ import annotations

import dataclasses
import math
import re
from collections.abc import Mapping
from datetime import date, datetime, time
from decimal import Decimal
from enum import Enum
from functools import lru_cache
from pathlib import PurePath
from uuid import UUID

from pydantic import BaseModel, JsonValue

from ..core.models import CanonicalEvent, ExplanationContext, PolicyAction, PolicyDecision

REDACTED = "[not captured]"
"""The value recorded in place of a credential-named key's value."""
_MAX_DEPTH = 32
_SENSITIVE_NAMES = frozenset(
    {
        "access_token",
        "api_key",
        "apikey",
        "auth",
        "auth_token",
        "authorization",
        "bearer",
        "client_secret",
        "connection_string",
        "cookie",
        "credential",
        "credentials",
        "dsn",
        "jwt",
        "passphrase",
        "passwd",
        "password",
        "private_key",
        "refresh_token",
        "secret",
        "secret_key",
        "session_token",
        "set_cookie",
        "token",
    }
)
_SENSITIVE_SUFFIXES = tuple(f"_{name}" for name in _SENSITIVE_NAMES)
_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


@lru_cache(maxsize=4096)
def is_sensitive_key(key: str) -> bool:
    """Return whether a mapping key names an obvious credential.

    Keys are normalized (camelCase, ``-``, and spaces become ``_``; case is
    ignored) and every dot-separated segment is checked: a segment matches when
    it equals a credential name or ends with ``_<name>``. ``Set-Cookie``,
    ``x-api-key``, ``OPENAI_API_KEY``, ``accessToken``, ``basic_auth``, and
    ``headers.authorization`` all match; ``token_usage``, ``max_tokens``,
    ``author``, and ``oauth_provider`` do not.
    """
    normalized = _CAMEL_BOUNDARY.sub("_", key).casefold().replace("-", "_").replace(" ", "_")
    return any(
        segment in _SENSITIVE_NAMES or segment.endswith(_SENSITIVE_SUFFIXES)
        for segment in normalized.split(".")
    )


def sanitize_value(value: object) -> JsonValue:
    """Convert a value to JSON-safe data while withholding obvious credentials.

    Mappings, sequences, sets, Pydantic models, and dataclasses are converted
    recursively, and any key accepted by `is_sensitive_key` has its value
    replaced with ``"[not captured]"``. Datetimes, UUIDs, enums, decimals, and
    paths become strings or their JSON value; non-finite floats become
    ``"nan"``/``"inf"``/``"-inf"``; raw bytes are summarized by length; cycles
    and nesting deeper than 32 levels are replaced with a marker. Anything else
    is captured as its ``repr``.

    This is credential minimization, not PII detection or a general redaction
    engine.
    """
    return _sanitize(value, 0, set())


def sanitize_mapping[Key](value: Mapping[Key, object]) -> dict[str, JsonValue]:
    """Sanitize a mapping with `sanitize_value`, returning string keys."""
    return _sanitize_mapping(value, 0, set())


def _sanitize_mapping[Key](
    value: Mapping[Key, object], depth: int, active: set[int]
) -> dict[str, JsonValue]:
    result: dict[str, JsonValue] = {}
    for key, item in value.items():
        name = str(key)
        result[name] = REDACTED if is_sensitive_key(name) else _sanitize(item, depth + 1, active)
    return result


def _sanitize(value: object, depth: int, active: set[int]) -> JsonValue:
    if isinstance(value, Enum):
        value = value.value
    if value is None or isinstance(value, str | bool | int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else repr(value)
    if isinstance(value, datetime | date | time):
        return value.isoformat()
    if isinstance(value, UUID | Decimal | PurePath):
        return str(value)
    if isinstance(value, bytes | bytearray | memoryview):
        return f"<{len(value)} bytes>"
    if depth >= _MAX_DEPTH:
        return "[max depth exceeded]"
    if id(value) in active:
        return "[circular reference]"
    active.add(id(value))
    try:
        return _sanitize_container(value, depth, active)
    finally:
        active.discard(id(value))


def _sanitize_container(value: object, depth: int, active: set[int]) -> JsonValue:
    if isinstance(value, Mapping):
        return _sanitize_mapping(value, depth, active)
    if isinstance(value, list | tuple):
        return [_sanitize(item, depth + 1, active) for item in value]
    if isinstance(value, set | frozenset):
        return sorted((_sanitize(item, depth + 1, active) for item in value), key=repr)
    if isinstance(value, BaseModel):
        try:
            dumped = value.model_dump(mode="json")
        except Exception:
            return repr(value)
        return _sanitize_mapping(dumped, depth, active)
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        fields = {field.name: getattr(value, field.name) for field in dataclasses.fields(value)}
        return _sanitize_mapping(fields, depth, active)
    return repr(value)


class DefaultCapturePolicy:
    """Allow every canonical event; values are credential-minimized before capture."""

    async def evaluate(self, event: CanonicalEvent) -> PolicyDecision:
        """Allow ``event`` to be stored and emitted."""
        return PolicyDecision(
            context=event.context,
            policy_id="default-capture",
            action=PolicyAction.CAPTURE,
            allowed=True,
            reason="Canonical metadata capture is allowed after credential minimization.",
        )


class DefaultPolicyProvider:
    """Record that private memory and raw content are never exposed.

    The built-in explanation engines never read raw content or private memory,
    so the denied fields document that guarantee in every `PolicyDecision`. To
    withhold whole explanation sections from an audience, deny ``reasons``,
    ``contributing_factors``, or ``supporting_evidence`` in your own provider.
    """

    async def evaluate(
        self,
        context: ExplanationContext,
        action: PolicyAction,
    ) -> PolicyDecision:
        """Allow ``action``; for exposure, also deny raw and private fields."""
        exposing = action is PolicyAction.EXPOSE
        return PolicyDecision(
            context=context.execution.context,
            policy_id="default-exposure",
            action=action,
            allowed=True,
            audience=context.audience,
            denied_fields={"private_memory", "raw_content", "content_reference"}
            if exposing
            else set(),
            reason="Private memory and raw content are withheld by default."
            if exposing
            else "Allowed; only exposure is restricted by default.",
        )
