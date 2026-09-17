"""Errors raised by observability adapters."""

from __future__ import annotations


class ObservabilityAdapterError(RuntimeError):
    """Base error for an observability adapter."""


class OptionalDependencyError(ObservabilityAdapterError):
    """Raised when an adapter's optional SDK is unavailable."""


class AdapterClosedError(ObservabilityAdapterError):
    """Raised when an adapter is used after it has been closed."""
