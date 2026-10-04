"""Run one recorded decision through every policy x audience x engine combination.

Two exposure policies (permissive, and audience-scoped: business and end-user audiences
get the outcome and reasons only) are combined with the four built-in audiences and
both explanation engines. The deterministic engine always runs; the LLM engine runs
when ``OPENAI_API_KEY`` is set (optionally ``OPENAI_BASE_URL`` and ``OPENAI_MODEL``).
Every row is checked against the policy, so a disclosure regression fails the script.

Run with:

    uv run --extra llm-openai python examples/explanation_disclosure_matrix.py
"""

import asyncio
import os
import time
from contextlib import AsyncExitStack

from _shared import chat_model

from langgraph_xai import (
    Audience,
    DecisionFactor,
    DecisionType,
    EvidenceType,
    ExplanationContext,
    ExplanationEngine,
    LLMExplanationEngine,
    PolicyAction,
    PolicyDecision,
    PolicyProvider,
    StructuredExplanationEngine,
    XAIConfig,
    XAIRuntime,
)

RESTRICTED = frozenset({Audience.BUSINESS, Audience.END_USER})


class PermissivePolicy:
    async def evaluate(self, context: ExplanationContext, action: PolicyAction) -> PolicyDecision:
        return PolicyDecision(
            context=context.execution.context,
            policy_id="permissive",
            action=action,
            allowed=True,
            audience=context.audience,
            reason="Full disclosure to every audience.",
        )


class AudienceScopedPolicy:
    async def evaluate(self, context: ExplanationContext, action: PolicyAction) -> PolicyDecision:
        restricted = context.audience in RESTRICTED
        return PolicyDecision(
            context=context.execution.context,
            policy_id="audience-scoped",
            action=action,
            allowed=True,
            audience=context.audience,
            denied_fields={"contributing_factors", "supporting_evidence"} if restricted else set(),
            reason="Outcome and reasons only." if restricted else "Full disclosure.",
        )


async def record_underwriting_decision(xai: XAIRuntime):
    run = await xai.start_run()
    bureau = await xai.record_evidence(
        EvidenceType.TOOL_RESULT,
        summary="Credit bureau score 612 (subprime band).",
        content_reference="credit-bureau://reports/9931",
        confidence=0.95,
        run=run,
    )
    rule = await xai.record_evidence(
        EvidenceType.POLICY,
        summary="Underwriting policy requires manual review below a 650 score.",
        content_reference="policy://underwriting/manual-review",
        confidence=1.0,
        run=run,
    )
    decision = await xai.record_decision(
        "MANUAL_REVIEW",
        decision_type=DecisionType.ROUTING,
        candidate_actions=["AUTO_APPROVE", "MANUAL_REVIEW", "AUTO_DECLINE"],
        evidence_ids=[bureau.id, rule.id],
        factors=[
            DecisionFactor(name="credit_score", value=612, weight=0.7, evidence_ids=[bureau.id]),
            DecisionFactor(name="review_threshold", value=650, weight=0.3, evidence_ids=[rule.id]),
        ],
        run=run,
    )
    await xai.finish_run(run)
    return run, decision


async def main() -> None:
    use_llm = bool(os.getenv("OPENAI_API_KEY"))
    xai = XAIRuntime(config=XAIConfig(llm_explanation_enabled=use_llm), graph_id="underwriting")
    run, decision = await record_underwriting_decision(xai)
    engines: dict[str, ExplanationEngine] = {"structured": StructuredExplanationEngine()}
    policies = {"permissive": PermissivePolicy(), "audience-scoped": AudienceScopedPolicy()}

    print(f"{'audience':<10} {'policy':<16} {'engine':<10} {'factors':>7} {'evidence':>8}  summary")
    rows = 0
    async with AsyncExitStack() as resources:
        if use_llm:
            model = await resources.enter_async_context(chat_model())
            engines["llm"] = LLMExplanationEngine(model, enabled=True, timeout=60)
        for audience in Audience:
            for policy_name, policy in policies.items():
                for engine_name, engine in engines.items():
                    xai.register(PolicyProvider, policy)
                    xai.register(ExplanationEngine, engine)
                    started = time.perf_counter()
                    explanation = await xai.explain_decision(decision, audience=audience, run=run)
                    elapsed = time.perf_counter() - started
                    withheld = policy_name == "audience-scoped" and audience in RESTRICTED
                    assert bool(explanation.contributing_factors) is not withheld
                    assert len(explanation.supporting_evidence) == (0 if withheld else 2)
                    rows += 1
                    print(
                        f"{audience:<10} {policy_name:<16} {engine_name:<10} "
                        f"{len(explanation.contributing_factors):>7} "
                        f"{len(explanation.supporting_evidence):>8}  "
                        f"{explanation.summary}  [{elapsed:.2f}s]"
                    )
    print(f"\n{rows} combinations checked; every row matched its disclosure policy.")


if __name__ == "__main__":
    asyncio.run(main())
