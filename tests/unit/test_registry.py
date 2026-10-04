import pytest

from langgraph_xai import ObservabilityProvider, ProvenanceStore, Registry
from tests.helpers import RecordingObservability


def test_registry_is_instance_scoped() -> None:
    first, second = Registry(), Registry()
    provider = RecordingObservability()

    assert first.register(ObservabilityProvider, provider) is provider
    assert first.get(ObservabilityProvider) is provider
    assert first.require(ObservabilityProvider) is provider
    assert second.get(ObservabilityProvider) is None
    assert first.capabilities() == (ObservabilityProvider,)


def test_require_and_register_validate_providers() -> None:
    registry = Registry()

    with pytest.raises(LookupError, match="ObservabilityProvider"):
        registry.require(ObservabilityProvider)
    with pytest.raises(TypeError, match="does not implement ProvenanceStore"):
        registry.register(ProvenanceStore, object())


def test_remove_returns_the_provider() -> None:
    registry = Registry()
    provider = registry.register(ObservabilityProvider, RecordingObservability())

    assert registry.remove(ObservabilityProvider) is provider
    assert registry.remove(ObservabilityProvider) is None
    assert registry.get(ObservabilityProvider) is None


def test_provider_that_stops_conforming_is_detected() -> None:
    registry = Registry()
    registry.register(ObservabilityProvider, RecordingObservability())

    class Partial:
        async def emit(self, event: object) -> None: ...

    registry._providers[ObservabilityProvider] = Partial()

    with pytest.raises(TypeError, match="no longer implements"):
        registry.get(ObservabilityProvider)
