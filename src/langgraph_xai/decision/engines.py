"""Small provider-neutral decision helpers built on core models."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

from ..core.models import (
    Decision,
    DecisionFactor,
    DecisionType,
    ExplanationContext,
    PolicyAction,
    PolicyDecision,
)


class DecisionEngine:
    """Create an immutable, auditable decision from explicit inputs."""

    def decide(
        self,
        context: ExplanationContext,
        *,
        decision_type: DecisionType | str,
        selected_action: str,
        candidate_actions: Iterable[str] = (),
        factors: Iterable[DecisionFactor] = (),
        confidence: float | None = None,
        uncertainty: float | None = None,
    ) -> Decision:
        return Decision(
            context=context.execution.context,
            decision_type=decision_type,
            selected_action=selected_action,
            candidate_actions=list(candidate_actions),
            factors=list(factors),
            confidence=confidence,
            uncertainty=uncertainty,
        )


class RuleBasedDecisionEngine(DecisionEngine):
    """Compatibility name for explicit, non-LLM decision construction."""


class PolicyDecisionEngine:
    """Evaluate exposure policy using an explicit allow/deny field set."""

    def __init__(
        self,
        policy_id: str = "default",
        *,
        allowed_fields: set[str] | None = None,
        denied_fields: set[str] | None = None,
    ) -> None:
        self.policy_id = policy_id
        self.allowed_fields = allowed_fields
        self.denied_fields = denied_fields or set()

    async def evaluate(self, context: ExplanationContext, action: PolicyAction) -> PolicyDecision:
        allowed = not self.denied_fields and (
            self.allowed_fields is None or action.value in self.allowed_fields
        )
        return PolicyDecision(
            context=context.execution.context,
            policy_id=self.policy_id,
            action=action,
            allowed=allowed,
            allowed_fields=self.allowed_fields or set(),
            denied_fields=self.denied_fields,
            reason="Allowed by policy." if allowed else "Denied by policy.",
        )
