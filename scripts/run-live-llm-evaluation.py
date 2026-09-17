"""Run a repeatable live LLM explanation evaluation and write JSON/Markdown reports."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from langchain_openai import ChatOpenAI

from langgraph_xai.core import (
    Decision,
    DecisionFactor,
    Execution,
    ExecutionContext,
    ExecutionStatus,
    ExplanationContext,
    PolicyAction,
    PolicyDecision,
)
from langgraph_xai.explanation import LLMExplanationEngine


@dataclass(frozen=True)
class Scenario:
    name: str
    action: str
    factor_name: str
    factor_value: float | str
    expected_terms: tuple[str, ...]
    deny_reasons: bool = False


SCENARIOS = (
    Scenario(
        "banking-review",
        "HUMAN_REVIEW",
        "fraud_risk_score",
        0.91,
        ("review", "risk"),
    ),
    Scenario(
        "support-escalation",
        "ESCALATE_TO_SPECIALIST",
        "unresolved_attempts",
        3,
        ("escalat", "specialist"),
    ),
    Scenario(
        "policy-withholding",
        "MANUAL_APPROVAL",
        "private_account_signal",
        "restricted",
        ("approval",),
        deny_reasons=True,
    ),
)


def make_context(scenario: Scenario) -> ExplanationContext:
    context = ExecutionContext(
        application_id="live-evaluation",
        tenant_id="isolated-test",
        graph_id=scenario.name,
    )
    execution = Execution(
        context=context,
        status=ExecutionStatus.COMPLETED,
        started_at=datetime.now(UTC),
    )
    decision = Decision(
        context=context,
        decision_type="routing",
        selected_action=scenario.action,
        factors=[
            DecisionFactor(
                name=scenario.factor_name,
                value=scenario.factor_value,
            )
        ],
    )
    policies = []
    if scenario.deny_reasons:
        policies.append(
            PolicyDecision(
                context=context,
                policy_id="private-signal",
                action=PolicyAction.EXPOSE,
                allowed=True,
                denied_fields={"reasons", "contributing_factors"},
            )
        )
    return ExplanationContext(
        execution=execution,
        decision=decision,
        policies=policies,
        audience="end_user",
    )


async def evaluate(
    model_name: str,
    base_url: str,
    timeout_seconds: float,
) -> dict[str, object]:
    api_key = os.getenv("EXPLABS_API_KEY")
    if not api_key:
        raise RuntimeError("Set EXPLABS_API_KEY in the process environment")
    model = ChatOpenAI(
        model=model_name,
        base_url=base_url,
        api_key=api_key,
        temperature=0,
    )
    engine = LLMExplanationEngine(model, enabled=True, timeout=timeout_seconds)
    cases: list[dict[str, object]] = []
    latencies: list[float] = []
    for scenario in SCENARIOS:
        started = time.perf_counter()
        try:
            result = await engine.explain(make_context(scenario))
            latency_ms = (time.perf_counter() - started) * 1000
            latencies.append(latency_ms)
            text = f"{result.summary} {' '.join(result.reasons)}".lower()
            grounded = all(term in text for term in scenario.expected_terms)
            policy_safe = not scenario.deny_reasons or (
                scenario.factor_name not in text and str(scenario.factor_value).lower() not in text
            )
            cases.append(
                {
                    "scenario": scenario.name,
                    "latency_ms": round(latency_ms, 2),
                    "schema_valid": True,
                    "grounded_rubric_pass": grounded,
                    "policy_safe": policy_safe,
                    "error": None,
                }
            )
        except Exception as exc:
            cases.append(
                {
                    "scenario": scenario.name,
                    "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                    "schema_valid": False,
                    "grounded_rubric_pass": False,
                    "policy_safe": False,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
    passed = [case for case in cases if case["grounded_rubric_pass"]]
    policy_safe = [case for case in cases if case["policy_safe"]]
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "model": model_name,
        "base_url": base_url,
        "scenario_count": len(cases),
        "schema_success_rate": sum(bool(case["schema_valid"]) for case in cases) / len(cases),
        "grounded_rubric_pass_rate": len(passed) / len(cases),
        "policy_safety_pass_rate": len(policy_safe) / len(cases),
        "latency_ms": {
            "minimum": round(min(latencies), 2) if latencies else None,
            "median": round(statistics.median(latencies), 2) if latencies else None,
            "maximum": round(max(latencies), 2) if latencies else None,
        },
        "cases": cases,
        "methodology": (
            "Deterministic schema, expected-term grounding, and disclosure checks. "
            "This is not a statistical model-accuracy claim."
        ),
    }


def markdown(report: dict[str, object]) -> str:
    latency = report["latency_ms"]
    assert isinstance(latency, dict)
    lines = [
        "# Live LLM explanation evaluation",
        "",
        f"- Model: `{report['model']}`",
        f"- Endpoint: `{report['base_url']}`",
        f"- Scenarios: {report['scenario_count']}",
        f"- Schema success: {float(report['schema_success_rate']):.1%}",
        f"- Grounded rubric pass: {float(report['grounded_rubric_pass_rate']):.1%}",
        f"- Policy safety pass: {float(report['policy_safety_pass_rate']):.1%}",
        (
            "- Latency (min / median / max): "
            f"{latency['minimum']} / {latency['median']} / {latency['maximum']} ms"
        ),
        "",
        "## Methodology",
        "",
        str(report["methodology"]),
        "",
        "## Scenario results",
        "",
        "| Scenario | Latency ms | Schema | Grounded rubric | Policy safe | Error |",
        "| --- | ---: | --- | --- | --- | --- |",
    ]
    cases = report["cases"]
    assert isinstance(cases, list)
    for case in cases:
        assert isinstance(case, dict)
        lines.append(
            f"| {case['scenario']} | {case['latency_ms']} | {case['schema_valid']} | "
            f"{case['grounded_rubric_pass']} | {case['policy_safe']} | "
            f"{case['error'] or ''} |"
        )
    return "\n".join(lines) + "\n"


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=os.getenv("EXPLABS_MODEL", "gpt-5.6-luna"))
    parser.add_argument(
        "--base-url",
        default=os.getenv("EXPLABS_BASE_URL", "https://api.experientiallabs.ai/v1"),
    )
    parser.add_argument("--timeout", type=float, default=60)
    parser.add_argument("--output", type=Path, default=Path("reports/live-llm-evaluation"))
    args = parser.parse_args()
    report = await evaluate(args.model, args.base_url, args.timeout)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.with_suffix(".json").write_text(
        json.dumps(report, indent=2) + "\n",
        encoding="utf-8",
    )
    args.output.with_suffix(".md").write_text(markdown(report), encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
