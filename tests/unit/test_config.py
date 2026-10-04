import pytest
from pydantic import ValidationError

from langgraph_xai import CaptureMode, FailureMode, XAIConfig


def test_defaults() -> None:
    config = XAIConfig()

    assert config.capture_state is CaptureMode.DELTA
    assert config.capture_fields == frozenset()
    assert config.failure_mode is FailureMode.FAIL_OPEN
    assert config.llm_explanation_enabled is False
    assert config.max_concurrency == 32
    assert config.operation_timeout_seconds == 10.0


def test_explicit_values_and_string_enums_are_accepted() -> None:
    config = XAIConfig(
        capture_state="selective",
        capture_fields=frozenset({"risk"}),
        failure_mode="strict",
        llm_explanation_enabled=True,
        max_concurrency=8,
        operation_timeout_seconds=0.5,
    )

    assert config.capture_state is CaptureMode.SELECTIVE
    assert config.failure_mode is FailureMode.STRICT
    assert config.capture_fields == {"risk"}


def test_config_is_immutable() -> None:
    config = XAIConfig()

    with pytest.raises(ValidationError):
        config.max_concurrency = 1  # pyrefly: ignore[read-only] - the point of the test


@pytest.mark.parametrize(
    "values",
    [
        {"max_concurrency": 0},
        {"operation_timeout_seconds": 0},
        {"capture_state": "everything"},
        {"event_queue_size": 10},
    ],
)
def test_invalid_or_unknown_settings_are_rejected(values: dict) -> None:
    with pytest.raises(ValidationError):
        XAIConfig.model_validate(values)
