import pytest
from pydantic import ValidationError

from langgraph_xai.config import XAIConfig
from langgraph_xai.core import CaptureMode, FailureMode


def test_config_is_explicit_and_instance_scoped() -> None:
    config = XAIConfig(
        capture_state=CaptureMode.SELECTIVE,
        failure_mode=FailureMode.STRICT,
        llm_explanation_enabled=True,
        max_concurrency=8,
    )

    assert config.capture_state is CaptureMode.SELECTIVE
    assert config.failure_mode is FailureMode.STRICT
    assert config.llm_explanation_enabled is True
    assert config.max_concurrency == 8


def test_config_defaults() -> None:
    config = XAIConfig()

    assert config.capture_state is CaptureMode.DELTA
    assert config.failure_mode is FailureMode.FAIL_OPEN
    assert config.llm_explanation_enabled is False


def test_config_rejects_unbounded_concurrency() -> None:
    with pytest.raises(ValidationError):
        XAIConfig.model_validate({"max_concurrency": 0})
