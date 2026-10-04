"""Execute the example scripts so the documented workflows keep working."""

from __future__ import annotations

import os
import runpy
import subprocess
import sys
from pathlib import Path

import pytest

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"

pytestmark = pytest.mark.examples

OFFLINE = {
    "minimal_langgraph.py": ["answer: answer None -> 'Echo: Why?'"],
    "fraud_review.py": [
        "Route: HUMAN_REVIEW",
        "The routing decision selected 'HUMAN_REVIEW'.",
        "Contributing factors are withheld by policy.",
        " DERIVED_FROM transactions://txn-8841",
    ],
    "retrieval_and_tools.py": ['"retriever": "policy-index"', '"tool_call_id": "call_7Qk2"'],
    "canonical_model_gallery.py": [
        "========== Explanation (auditor) ==========",
        '"method": "hybrid"',
    ],
    "failure_modes.py": [
        "graph call returned {'value': 2}",
        "graph call raised XAIInstrumentationError",
    ],
    "human_in_the_loop.py": [
        '"status": "interrupted"',
        '"type": "resume"',
        '"restored": true',
        '"continuation_of": "',
        '"actor": "reviewer:ana"',
        '"approval"\n',
    ],
    "multi_agent_retry_correlation.py": ['"status": "timed_out"', '"status": "succeeded"'],
    "explanation_disclosure_matrix.py": ["8 combinations checked"],
}


def run_example(
    name: str, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> str:
    monkeypatch.syspath_prepend(str(EXAMPLES))
    runpy.run_path(str(EXAMPLES / name), run_name="__main__")
    return capsys.readouterr().out


@pytest.mark.parametrize(("name", "expected"), OFFLINE.items(), ids=list(OFFLINE))
def test_offline_examples_run(
    name: str,
    expected: list[str],
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    output = run_example(name, capsys, monkeypatch)

    for text in expected:
        assert text in output


def test_every_example_is_covered() -> None:
    scripts = {path.name for path in EXAMPLES.glob("*.py") if not path.name.startswith("_")}

    assert scripts == set(OFFLINE) | set(LIVE) | {
        "mcp_playwright_tool_agent.py",
        "postgres_store.py",
    }


LIVE = {
    "create_agent_decision_explanation.py": ["The escalation decision selected"],
    "create_agent_inside_node.py": ['"intake"', '"check_fraud_risk"'],
    "deepagents_agent.py": ['"word_count: succeeded"'],
}


@pytest.mark.live
@pytest.mark.parametrize(("name", "expected"), LIVE.items(), ids=list(LIVE))
def test_llm_examples_run(name: str, expected: list[str]) -> None:
    api_key = os.getenv("XAI_TEST_LLM_API_KEY")
    if not api_key:
        pytest.skip("XAI_TEST_LLM_API_KEY is not configured")
    pytest.importorskip("langchain_openai")
    if name == "deepagents_agent.py":
        pytest.importorskip("deepagents")
    environment = {**os.environ, "OPENAI_API_KEY": api_key, "PYTHONIOENCODING": "utf-8"}
    for source, target in (
        ("XAI_TEST_LLM_BASE_URL", "OPENAI_BASE_URL"),
        ("XAI_TEST_LLM_MODEL", "OPENAI_MODEL"),
    ):
        if value := os.getenv(source):
            environment[target] = value

    # Each example runs in its own process, as users run them: LLM SDKs cache HTTP
    # clients per process, which must not outlive one example's event loop.
    completed = subprocess.run(  # noqa: S603 - fixed interpreter and example path
        [sys.executable, str(EXAMPLES / name)],
        cwd=EXAMPLES,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=600,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    for text in expected:
        assert text in completed.stdout
