"""Explanation engines with explicit disclosure and model boundaries."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..core.models import (
    AttributionContribution,
    EvidenceReference,
    Explanation,
    ExplanationContext,
    PolicyAction,
)

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel
    from langchain_core.runnables import Runnable


class ExplanationDraft(BaseModel):
    """The only output shape accepted from an LLM explanation model."""

    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1)
    reasons: list[str] = Field(default_factory=list)
    disclosure: list[str] = Field(default_factory=list)


def _policy_denies(context: ExplanationContext, field: str) -> bool:
    for policy in context.policies:
        if policy.action is PolicyAction.EXPOSE and (
            not policy.allowed or field in policy.denied_fields
        ):
            return True
    return False


class StructuredExplanationEngine:
    """Build a deterministic explanation without generating hidden reasoning."""

    requires_llm = False

    async def explain(self, context: ExplanationContext) -> Explanation:
        decision = context.decision
        audience = str(context.audience)
        reasons: list[str] = []
        factors: list[AttributionContribution] = []
        evidence: list[EvidenceReference] = []
        disclosure: list[str] = []

        if decision is not None:
            reasons.append(f"Selected action: {decision.selected_action}.")
            reasons.extend(
                self._factor_reason(factor.name, factor.value)
                for factor in sorted(decision.factors, key=lambda item: item.name)
            )

        if context.attribution is not None:
            factors = sorted(
                context.attribution.contributions,
                key=lambda item: (-abs(item.score), str(item.factor_id)),
            )
        if decision is not None:
            evidence = [
                EvidenceReference(evidence_id=evidence_id)
                for evidence_id in sorted(set(decision.evidence_ids), key=str)
            ]

        if _policy_denies(context, "reasons"):
            reasons = []
            disclosure.append("Decision reasons are withheld by policy.")
        if _policy_denies(context, "contributing_factors"):
            factors = []
            disclosure.append("Attribution factors are withheld by policy.")
        if _policy_denies(context, "supporting_evidence"):
            evidence = []
            disclosure.append("Supporting evidence is withheld by policy.")

        if not reasons:
            reasons.append("No decision details were captured.")
        summary = self._summary(context, audience)
        disclosure.extend(
            policy.reason
            for policy in context.policies
            if policy.action is PolicyAction.EXPOSE and policy.reason
        )

        return Explanation(
            context=context.execution.context,
            audience=context.audience,
            summary=summary,
            reasons=reasons,
            supporting_evidence=evidence,
            contributing_factors=factors,
            disclosure=list(dict.fromkeys(disclosure)),
            metadata={"engine": "structured"},
        )

    @staticmethod
    def _factor_reason(name: str, value: object) -> str:
        return f"Factor {name} was {value!r}."

    @staticmethod
    def _summary(context: ExplanationContext, audience: str) -> str:
        if context.decision is None:
            return f"Execution completed; no decision was recorded for {audience}."
        return (
            f"The {audience} explanation is based on the selected action "
            f"'{context.decision.selected_action}'."
        )


class LLMExplanationEngine(StructuredExplanationEngine):
    """Opt-in explanation generation through an injected LangChain runnable."""

    requires_llm = True

    def __init__(
        self,
        model: BaseChatModel | Runnable[str, str] | None = None,
        *,
        enabled: bool = False,
        timeout: float = 30.0,
    ) -> None:
        if timeout <= 0:
            raise ValueError("timeout must be greater than zero")
        self.model = model
        self.enabled = enabled
        self.timeout = timeout

    async def explain(self, context: ExplanationContext) -> Explanation:
        if not self.enabled:
            raise RuntimeError("LLM explanations are disabled; construct with enabled=True")
        if self.model is None:
            raise RuntimeError("LLM explanations require an injected LangChain model")

        prompt = self._prompt(context)
        result = await asyncio.wait_for(self.model.ainvoke(prompt), timeout=self.timeout)
        draft = self._validate(result)
        structured = await super().explain(context)
        reasons = draft.reasons
        if _policy_denies(context, "reasons"):
            reasons = structured.reasons
        return structured.model_copy(
            update={
                "summary": draft.summary,
                "reasons": reasons,
                "disclosure": list(dict.fromkeys(structured.disclosure + draft.disclosure)),
                "metadata": {"engine": "llm", "validated": True},
            }
        )

    @staticmethod
    def _prompt(context: ExplanationContext) -> str:
        decision = context.decision
        factors = []
        if decision is not None and not _policy_denies(context, "contributing_factors"):
            factors = [
                {"name": factor.name, "value": factor.value}
                for factor in sorted(decision.factors, key=lambda item: item.name)
            ]
        evidence = []
        if not _policy_denies(context, "supporting_evidence"):
            evidence = [
                {
                    "id": str(item.id),
                    "type": str(item.evidence_type),
                    "summary": item.summary,
                    "confidence": item.confidence,
                }
                for item in context.evidence
            ]
        payload = {
            "audience": str(context.audience),
            "selected_action": decision.selected_action if decision else None,
            "factors": factors,
            "evidence": evidence,
            "output_schema": {
                "summary": "string",
                "reasons": "array of strings",
                "disclosure": (
                    "array of strings (use an empty array [] if there is nothing to disclose)"
                ),
            },
            "instructions": (
                "Return only a single JSON object with exactly the keys summary, reasons, "
                "and disclosure, matching output_schema exactly. `reasons` and `disclosure` "
                "MUST each be a JSON array of strings, never a single string. "
                "Use only the supplied observable facts. Do not infer or provide "
                "hidden reasoning. Keep the explanation appropriate for the audience."
            ),
        }
        return json.dumps(payload, sort_keys=True)

    @staticmethod
    def _validate(result: object) -> ExplanationDraft:
        if isinstance(result, ExplanationDraft):
            return result
        content = getattr(result, "content", result)
        if isinstance(content, list):
            content = "".join(
                block.get("text", "") if isinstance(block, Mapping) else str(block)
                for block in content
            )
        if isinstance(content, str):
            try:
                content = json.loads(content)
            except json.JSONDecodeError as exc:
                raise ValueError("LLM explanation output must be valid JSON") from exc
        if isinstance(content, Mapping):
            # Models occasionally return a single string for a list-typed field
            # (e.g. one combined disclosure sentence instead of an array). This is
            # a formatting normalization only -- it does not add, infer, or hide
            # any content the model did not already provide.
            content = {
                key: [value]
                if key in ("reasons", "disclosure") and isinstance(value, str)
                else value
                for key, value in content.items()
            }
        try:
            return ExplanationDraft.model_validate(content)
        except ValidationError as exc:
            raise ValueError("LLM explanation output failed schema validation") from exc
