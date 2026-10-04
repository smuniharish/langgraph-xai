"""Explanation engines with explicit disclosure and model boundaries."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Mapping
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..core.models import (
    AttributionContribution,
    Decision,
    DecisionType,
    EvidenceReference,
    Explanation,
    ExplanationContext,
    PolicyAction,
)

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel
    from langchain_core.runnables import Runnable

_WITHHELD_NOTES = {
    "reasons": "Decision reasons are withheld by policy.",
    "contributing_factors": "Contributing factors are withheld by policy.",
    "supporting_evidence": "Supporting evidence is withheld by policy.",
}
_JSON_FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL | re.IGNORECASE)


class ExplanationDraft(BaseModel):
    """The only output shape accepted from an LLM explanation model."""

    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1)
    reasons: list[str] = Field(default_factory=list)
    disclosure: list[str] = Field(default_factory=list)


def _block_text(block: object) -> str:
    # A chat model's content blocks; only text blocks carry the answer.
    if isinstance(block, Mapping):
        text = block.get("text")
        return text if isinstance(text, str) else ""
    return str(block)


def _policy_denies(context: ExplanationContext, field: str) -> bool:
    return any(
        policy.action is PolicyAction.EXPOSE
        and (
            not policy.allowed
            or field in policy.denied_fields
            or (bool(policy.allowed_fields) and field not in policy.allowed_fields)
        )
        for policy in context.policies
    )


def _decision_reasons(decision: Decision, *, include_factors: bool) -> list[str]:
    reasons = [f"Selected action: {decision.selected_action}."]
    alternatives = [
        action for action in decision.candidate_actions if action != decision.selected_action
    ]
    if alternatives:
        reasons.append(f"Alternatives considered: {', '.join(alternatives)}.")
    if include_factors:
        reasons.extend(
            f"Factor {factor.name} was {factor.value!r}."
            for factor in sorted(decision.factors, key=lambda item: item.name)
        )
    if decision.confidence is not None:
        reasons.append(f"Decision confidence: {decision.confidence:g}.")
    return reasons


class StructuredExplanationEngine:
    """Build a deterministic explanation from canonical fields, without calling a model.

    The summary names the decision and selected action; ``reasons`` list the
    selected action, alternatives, factor values, and confidence;
    ``contributing_factors`` are the attribution contributions ranked by
    absolute score; ``supporting_evidence`` references the decision's evidence.
    An exposure policy that denies ``reasons``, ``contributing_factors``, or
    ``supporting_evidence`` (or denies exposure altogether) empties that section
    and records why in ``disclosure``. Withholding ``contributing_factors`` also
    removes factor values from ``reasons``.
    """

    requires_llm = False

    async def explain(self, context: ExplanationContext) -> Explanation:
        """Render ``context`` for ``context.audience``."""
        withheld = [field for field in _WITHHELD_NOTES if _policy_denies(context, field)]
        decision = context.decision
        reasons: list[str] = []
        evidence: list[EvidenceReference] = []
        factors: list[AttributionContribution] = []
        if decision is not None:
            reasons = _decision_reasons(
                decision, include_factors="contributing_factors" not in withheld
            )
            evidence = [
                EvidenceReference(evidence_id=evidence_id)
                for evidence_id in sorted(set(decision.evidence_ids), key=str)
            ]
        else:
            reasons = ["No decision was recorded."]
        if context.attribution is not None:
            factors = sorted(
                context.attribution.contributions,
                key=lambda item: (-abs(item.score), str(item.factor_id)),
            )

        if "reasons" in withheld:
            reasons = []
        if "contributing_factors" in withheld:
            factors = []
        if "supporting_evidence" in withheld:
            evidence = []
        disclosure = [_WITHHELD_NOTES[field] for field in withheld]
        disclosure.extend(
            policy.reason
            for policy in context.policies
            if policy.action is PolicyAction.EXPOSE and policy.reason
        )

        return Explanation(
            context=context.execution.context,
            audience=context.audience,
            summary=self._summary(context),
            reasons=reasons,
            supporting_evidence=evidence,
            contributing_factors=factors,
            disclosure=list(dict.fromkeys(disclosure)),
            metadata={"engine": "structured"},
        )

    @staticmethod
    def _summary(context: ExplanationContext) -> str:
        decision = context.decision
        if decision is None:
            return (
                f"No decision was recorded for this execution (status: {context.execution.status})."
            )
        kind = str(decision.decision_type)
        subject = (
            "The decision"
            if kind == DecisionType.CUSTOM
            else f"The {kind.replace('_', ' ')} decision"
        )
        return f"{subject} selected '{decision.selected_action}'."


class LLMExplanationEngine(StructuredExplanationEngine):
    """Opt-in phrasing of an already-approved explanation through an injected LangChain model.

    The model receives only policy-filtered, structured facts and must return a
    JSON object matching `ExplanationDraft` exactly; any other shape is
    rejected. Sections withheld by policy are never sent to the model, and
    withheld reasons are never taken from its reply. Runs only when constructed
    with ``enabled=True`` *and* the runtime's ``XAIConfig.llm_explanation_enabled``
    is set.
    """

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
        """Phrase the structured explanation of ``context`` with the injected model."""
        if not self.enabled:
            raise RuntimeError("LLM explanations are disabled; construct with enabled=True")
        if self.model is None:
            raise RuntimeError("LLM explanations require an injected LangChain model")

        result = await asyncio.wait_for(
            self.model.ainvoke(self._prompt(context)), timeout=self.timeout
        )
        draft = self._validate(result)
        structured = await super().explain(context)
        return structured.model_copy(
            update={
                "summary": draft.summary,
                "reasons": structured.reasons
                if _policy_denies(context, "reasons")
                else draft.reasons,
                "disclosure": list(dict.fromkeys(structured.disclosure + draft.disclosure)),
                "metadata": {"engine": "llm", "validated": True},
            }
        )

    @staticmethod
    def _prompt(context: ExplanationContext) -> str:
        decision = context.decision
        withheld = [field for field in _WITHHELD_NOTES if _policy_denies(context, field)]
        reasons_allowed = "reasons" not in withheld
        factors = []
        if decision is not None and reasons_allowed and "contributing_factors" not in withheld:
            factors = [
                {"name": factor.name, "value": factor.value}
                for factor in sorted(decision.factors, key=lambda item: item.name)
            ]
        evidence = []
        if "supporting_evidence" not in withheld:
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
            "decision_type": str(decision.decision_type) if decision else None,
            "selected_action": decision.selected_action if decision else None,
            "candidate_actions": decision.candidate_actions if decision and reasons_allowed else [],
            "factors": factors,
            "evidence": evidence,
            "withheld_by_policy": [field.replace("_", " ") for field in withheld],
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
                "hidden reasoning. Sections named in withheld_by_policy exist but are "
                "withheld from this audience: never mention them, guess them, or say "
                "they are missing. Keep the explanation appropriate for the audience."
            ),
        }
        return json.dumps(payload, sort_keys=True)

    @staticmethod
    def _validate(result: object) -> ExplanationDraft:
        if isinstance(result, ExplanationDraft):
            return result
        content = getattr(result, "content", result)
        if isinstance(content, list):
            content = "".join(_block_text(block) for block in content)
        if isinstance(content, str):
            fenced = _JSON_FENCE.match(content)
            try:
                content = json.loads(fenced.group(1) if fenced else content)
            except (json.JSONDecodeError, RecursionError) as exc:
                raise ValueError("LLM explanation output must be valid JSON") from exc
        if isinstance(content, Mapping):
            # Models occasionally return a single string for a list-typed field.
            # Wrapping it is a formatting normalization only; unknown keys are
            # still rejected by the strict schema below.
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
