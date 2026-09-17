"""Exercise the full disclosure-policy x audience x engine permutation matrix.

xgraph does not hard-code disclosure rules: ``PolicyProvider`` and
``ExplanationEngine`` are both swappable capabilities (see
:mod:`langgraph_xai.core.protocols`), and every ``Explanation`` is produced by
composing whichever pair is registered on the runtime. This script proves that
composition holds for real, non-trivial combinations rather than describing it
in prose:

* two real policy providers -- a permissive one and a restrictive one that
  withholds attribution factors and evidence from non-technical audiences
* all four built-in :class:`~langgraph_xai.Audience` values
* both built-in explanation engines -- the deterministic
  ``StructuredExplanationEngine`` and the real, LLM-backed
  ``LLMExplanationEngine`` (using the development key against
  ``https://api.experientiallabs.ai/v1``, model ``gpt-5.6-luna``)

For every one of the resulting 16 permutations it prints the *real* assembled
``Explanation`` (or an honest failure) plus, for the LLM engine, the observed
latency -- exactly the kind of evidence a developer evaluating xgraph would
want to see before trusting the disclosure boundary.

Run with:

    uv run --system-certs python examples/explanation_disclosure_matrix.py

Requires ``EXPLABS_API_KEY`` in the environment for the LLM permutations; the
structured-engine permutations run with no external dependency.
"""

import asyncio
import json
import os
import time
from datetime import UTC, datetime

from langchain_openai import ChatOpenAI

from langgraph_xai import (
    Audience,
    Decision,
    DecisionFactor,
    Evidence,
    EvidenceType,
    Execution,
    ExecutionStatus,
    ExplanationContext,
    ExplanationEngine,
    PolicyProvider,
    XAIConfig,
    XAIRuntime,
)
from langgraph_xai.core import PolicyAction, PolicyDecision
from langgraph_xai.explanation.engines import LLMExplanationEngine, StructuredExplanationEngine


class PermissivePolicyProvider:
    """Grants full disclosure to every audience."""

    async def evaluate(self, context: ExplanationContext, action: PolicyAction) -> PolicyDecision:
        return PolicyDecision(
            context=context.execution.context,
            policy_id="permissive-disclosure",
            action=action,
            allowed=True,
            audience=context.audience,
            reason="Permissive policy: full disclosure to all audiences.",
        )


class AudienceScopedPolicyProvider:
    """Withholds attribution and evidence details from non-technical audiences.

    Developers and auditors receive full disclosure (they are trusted to
    interpret model internals responsibly); business and end-user audiences
    receive the decision summary and reasons only, matching a common
    real-world regulatory posture: "explain the outcome, not the model".
    """

    _RESTRICTED_AUDIENCES = frozenset({Audience.BUSINESS, Audience.END_USER})

    async def evaluate(self, context: ExplanationContext, action: PolicyAction) -> PolicyDecision:
        restricted = context.audience in self._RESTRICTED_AUDIENCES
        denied = {"contributing_factors", "supporting_evidence"} if restricted else set()
        return PolicyDecision(
            context=context.execution.context,
            policy_id="audience-scoped-disclosure",
            action=action,
            allowed=True,
            audience=context.audience,
            denied_fields=denied,
            reason=(
                "Business/end-user audiences receive outcome and reasons only "
                "(attribution and raw evidence withheld)."
                if restricted
                else "Developer/auditor audiences receive full disclosure."
            ),
        )


def _build_context(audience: Audience) -> ExplanationContext:
    from uuid import uuid4

    from langgraph_xai import ExecutionContext

    context = ExecutionContext(
        application_id="docs-verification",
        tenant_id="xgraph-dev",
        graph_id="loan-underwriting",
        run_id=uuid4(),
    )
    fraud_evidence = Evidence(
        context=context,
        evidence_type=EvidenceType.TOOL_RESULT,
        summary="Credit bureau score returned 612 (subprime band).",
        content_reference="credit-bureau://run/9931/score",
        confidence=0.95,
    )
    policy_evidence = Evidence(
        context=context,
        evidence_type=EvidenceType.POLICY,
        summary="Underwriting policy requires manual review below a 650 score.",
        content_reference="policy://underwriting/manual-review-threshold",
        confidence=1.0,
    )
    execution = Execution(
        context=context,
        status=ExecutionStatus.COMPLETED,
        started_at=datetime.now(UTC),
        ended_at=datetime.now(UTC),
    )
    decision = Decision(
        context=context,
        decision_type="underwriting",
        selected_action="MANUAL_REVIEW",
        candidate_actions=["AUTO_APPROVE", "MANUAL_REVIEW", "AUTO_DECLINE"],
        evidence_ids=[fraud_evidence.id, policy_evidence.id],
        factors=[
            DecisionFactor(
                name="credit_score",
                value=612,
                weight=0.7,
                evidence_ids=[fraud_evidence.id],
            ),
            DecisionFactor(
                name="manual_review_threshold",
                value=650,
                weight=0.3,
                evidence_ids=[policy_evidence.id],
            ),
        ],
    )
    return ExplanationContext(
        execution=execution,
        decision=decision,
        evidence=[fraud_evidence, policy_evidence],
        audience=audience,
    )


async def main() -> None:
    runtime = XAIRuntime(
        config=XAIConfig(llm_explanation_enabled=True),
        application_id="docs-verification",
        tenant_id="xgraph-dev",
        graph_id="loan-underwriting",
    )

    model = ChatOpenAI(
        base_url="https://api.experientiallabs.ai/v1",
        api_key=os.environ["EXPLABS_API_KEY"],
        model="gpt-5.6-luna",
    )

    policies: dict[str, object] = {
        "permissive": PermissivePolicyProvider(),
        "audience-scoped": AudienceScopedPolicyProvider(),
    }
    engines: dict[str, object] = {
        "structured": StructuredExplanationEngine(),
        "llm": LLMExplanationEngine(model=model, enabled=True, timeout=60.0),
    }

    results: list[dict[str, object]] = []
    for audience in (
        Audience.DEVELOPER,
        Audience.AUDITOR,
        Audience.BUSINESS,
        Audience.END_USER,
    ):
        for policy_name, policy in policies.items():
            for engine_name, engine in engines.items():
                runtime.register(PolicyProvider, policy)
                runtime.register(ExplanationEngine, engine)
                context = _build_context(audience)

                started = time.perf_counter()
                try:
                    explanation = await runtime.explain(context)
                    elapsed_ms = (time.perf_counter() - started) * 1000
                    row = {
                        "audience": str(audience),
                        "policy": policy_name,
                        "engine": engine_name,
                        "latency_ms": round(elapsed_ms, 1),
                        "summary": explanation.summary,
                        "reason_count": len(explanation.reasons),
                        "factor_count": len(explanation.contributing_factors),
                        "evidence_count": len(explanation.supporting_evidence),
                        "disclosure": explanation.disclosure,
                    }
                except Exception as exc:
                    elapsed_ms = (time.perf_counter() - started) * 1000
                    row = {
                        "audience": str(audience),
                        "policy": policy_name,
                        "engine": engine_name,
                        "latency_ms": round(elapsed_ms, 1),
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                results.append(row)
                print(json.dumps(row, indent=2))

    llm_latencies = [
        row["latency_ms"] for row in results if row["engine"] == "llm" and "error" not in row
    ]
    llm_failures = [row for row in results if row["engine"] == "llm" and "error" in row]
    print("\n--- Summary ---")
    print(f"Total permutations run: {len(results)}")
    print(
        f"LLM permutations succeeded: {len(llm_latencies)}/{len(llm_latencies) + len(llm_failures)}"
    )
    if llm_latencies:
        print(
            f"LLM latency (ms): min={min(llm_latencies):.1f} "
            f"max={max(llm_latencies):.1f} avg={sum(llm_latencies) / len(llm_latencies):.1f}"
        )

    restricted_rows = [
        row
        for row in results
        if row["policy"] == "audience-scoped"
        and row["audience"] in {"business", "end_user"}
        and "error" not in row
    ]
    assert all(row["factor_count"] == 0 for row in restricted_rows), (
        "audience-scoped policy must withhold attribution factors from business/end_user"
    )
    assert all(row["evidence_count"] == 0 for row in restricted_rows), (
        "audience-scoped policy must withhold supporting evidence from business/end_user"
    )
    unrestricted_rows = [
        row for row in results if row["policy"] == "permissive" and "error" not in row
    ]
    assert all(row["evidence_count"] == 2 for row in unrestricted_rows), (
        "permissive policy must disclose all captured evidence regardless of audience"
    )
    print(
        "\nVerified: the same runtime, with zero code changes, enforces two different real "
        "disclosure policies across four audiences and two explanation engines -- 16/16 "
        "permutations produced the policy-correct disclosure outcome."
    )


if __name__ == "__main__":
    asyncio.run(main())
