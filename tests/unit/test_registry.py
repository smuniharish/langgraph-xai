import pytest

from langgraph_xai.core import ObservabilityProvider
from langgraph_xai.runtime import Registry


class TestObservability:
    async def emit(self, event: object) -> None:
        return None

    async def flush(self) -> None:
        return None

    async def close(self) -> None:
        return None


def test_registry_is_instance_scoped() -> None:
    first = Registry()
    second = Registry()
    provider = TestObservability()

    first.register(ObservabilityProvider, provider)

    assert first.get(ObservabilityProvider) is provider
    assert second.get(ObservabilityProvider) is None


def test_registry_requires_registered_capability() -> None:
    registry = Registry()

    with pytest.raises(LookupError):
        registry.require(ObservabilityProvider)


def test_registry_rejects_nonconforming_provider() -> None:
    registry = Registry()

    with pytest.raises(TypeError):
        registry.register(ObservabilityProvider, object())
