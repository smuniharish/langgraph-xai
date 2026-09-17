"""Conservative default capture and exposure policies."""

from __future__ import annotations

from collections.abc import Mapping

from ..core.models import (
    CanonicalEvent,
    ExplanationContext,
    JsonValue,
    PolicyAction,
    PolicyDecision,
)

_SENSITIVE_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "authorization",
        "auth_token",
        "bearer",
        "client_secret",
        "cookie",
        "password",
        "private_key",
        "secret",
        "set-cookie",
        "token",
    }
)
_REDACTED = "[not captured]"


def _is_sensitive(key: str) -> bool:
    normalized = key.casefold().replace("-", "_")
    return any(part in _SENSITIVE_KEYS for part in normalized.split("."))


def sanitize_value(value: object) -> JsonValue:
    """Convert a value to JSON while minimizing obvious credential fields.

    This is intentionally not PII detection or a general redaction engine.
    """
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, Mapping):
        return sanitize_mapping(value)
    if isinstance(value, list | tuple):
        return [sanitize_value(item) for item in value]
    return repr(value)


def sanitize_mapping[Key](value: Mapping[Key, object]) -> dict[str, JsonValue]:
    return {
        str(key): _REDACTED if _is_sensitive(str(key)) else sanitize_value(item)
        for key, item in value.items()
    }


class DefaultCapturePolicy:
    """Allow canonical events after their values have been minimized."""

    async def evaluate(self, event: CanonicalEvent) -> PolicyDecision:
        return PolicyDecision(
            context=event.context,
            policy_id="default-capture",
            action=PolicyAction.CAPTURE,
            allowed=True,
            reason="Canonical metadata capture is allowed after credential minimization.",
        )


class DefaultPolicyProvider:
    """Deny private memory and raw content exposure by default."""

    async def evaluate(
        self,
        context: ExplanationContext,
        action: PolicyAction,
    ) -> PolicyDecision:
        denied = {"private_memory", "raw_content", "content_reference"}
        if action is not PolicyAction.EXPOSE:
            denied = set()
        return PolicyDecision(
            context=context.execution.context,
            policy_id="default-exposure",
            action=action,
            allowed=True,
            audience=context.audience,
            denied_fields=denied,
            reason="Private memory and raw content are withheld by default."
            if denied
            else "Structured processing is allowed.",
        )
