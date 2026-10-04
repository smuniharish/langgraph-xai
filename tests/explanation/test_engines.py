import asyncio
import json

import pytest
from hypothesis import given
from hypothesis import strategies as st
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

from langgraph_xai import (
    Decision,
    ExplanationContext,
    LLMExplanationEngine,
    PolicyAction,
    PolicyDecision,
    StructuredExplanationEngine,
)
from langgraph_xai.core import AttributionContribution, AttributionResult, ExecutionStatus
from langgraph_xai.explanation import ExplanationDraft
from tests.helpers import context, execution, explanation_context

SECTIONS = ("reasons", "contributing_factors", "supporting_evidence")


def deny(
    *fields: str,
    allowed: bool = True,
    reason: str | None = None,
    allow_only: set[str] | None = None,
) -> PolicyDecision:
    return PolicyDecision(
        context=context(),
        policy_id="test",
        action=PolicyAction.EXPOSE,
        allowed=allowed,
        denied_fields=set(fields),
        allowed_fields=allow_only or set(),
        reason=reason,
    )


def with_attribution(context_: ExplanationContext) -> ExplanationContext:
    attribution = AttributionResult(
        context=context_.execution.context,
        subject_id=context_.execution.id,
        method="test",
        contributions=[
            AttributionContribution(factor_id="small", factor_type="t", score=0.1),
            AttributionContribution(factor_id="negative", factor_type="t", score=-0.6),
            AttributionContribution(factor_id="large", factor_type="t", score=0.3),
        ],
    )
    return context_.model_copy(update={"attribution": attribution})


async def test_structured_explanation_renders_decision_facts() -> None:
    result = await StructuredExplanationEngine().explain(with_attribution(explanation_context()))

    assert result.summary == "The routing decision selected 'HUMAN_REVIEW'."
    assert result.reasons == [
        "Selected action: HUMAN_REVIEW.",
        "Alternatives considered: AUTO_APPROVE.",
        "Factor risk was 0.91.",
        "Factor threshold was 0.8.",
        "Decision confidence: 0.9.",
    ]
    assert [item.factor_id for item in result.contributing_factors] == [
        "negative",
        "large",
        "small",
    ]
    assert len(result.supporting_evidence) == 2
    assert result.disclosure == []
    assert result.metadata == {"engine": "structured"}


async def test_summary_for_custom_decisions_and_missing_decisions() -> None:
    ctx = context()
    custom = Decision(context=ctx, decision_type="custom", selected_action="ship")
    failed = execution(ctx).model_copy(update={"status": ExecutionStatus.FAILED})

    with_custom = await StructuredExplanationEngine().explain(
        ExplanationContext(execution=execution(ctx), decision=custom)
    )
    without = await StructuredExplanationEngine().explain(ExplanationContext(execution=failed))

    assert with_custom.summary == "The decision selected 'ship'."
    assert without.summary == "No decision was recorded for this execution (status: failed)."
    assert without.reasons == ["No decision was recorded."]


@pytest.mark.parametrize("field", SECTIONS)
async def test_each_section_can_be_withheld(field: str) -> None:
    result = await StructuredExplanationEngine().explain(
        with_attribution(explanation_context(policies=[deny(field, reason="Customer view.")]))
    )

    assert getattr(result, field) == []
    assert result.disclosure[-1] == "Customer view."
    assert any("withheld by policy" in note for note in result.disclosure)
    for other in set(SECTIONS) - {field}:
        assert getattr(result, other)


async def test_denied_exposure_withholds_every_section_without_false_claims() -> None:
    result = await StructuredExplanationEngine().explain(
        with_attribution(explanation_context(policies=[deny(allowed=False), deny("reasons")]))
    )

    assert result.reasons == result.contributing_factors == result.supporting_evidence == []
    assert "No decision" not in " ".join(result.reasons + result.disclosure)
    assert result.disclosure == [
        "Decision reasons are withheld by policy.",
        "Contributing factors are withheld by policy.",
        "Supporting evidence is withheld by policy.",
    ]


async def test_withholding_contributing_factors_also_removes_factor_values_from_reasons() -> None:
    result = await StructuredExplanationEngine().explain(
        explanation_context(policies=[deny("contributing_factors")])
    )

    assert result.reasons == [
        "Selected action: HUMAN_REVIEW.",
        "Alternatives considered: AUTO_APPROVE.",
        "Decision confidence: 0.9.",
    ]


async def test_allowed_fields_act_as_an_allowlist() -> None:
    result = await StructuredExplanationEngine().explain(
        with_attribution(explanation_context(policies=[deny(allow_only={"reasons"})]))
    )

    assert result.reasons == [
        "Selected action: HUMAN_REVIEW.",
        "Alternatives considered: AUTO_APPROVE.",
        "Decision confidence: 0.9.",
    ]
    assert result.contributing_factors == result.supporting_evidence == []
    assert result.disclosure == [
        "Contributing factors are withheld by policy.",
        "Supporting evidence is withheld by policy.",
    ]


async def test_non_exposure_policies_are_ignored() -> None:
    capture = PolicyDecision(
        context=context(),
        policy_id="p",
        action=PolicyAction.CAPTURE,
        allowed=False,
        reason="capture only",
    )

    result = await StructuredExplanationEngine().explain(explanation_context(policies=[capture]))

    assert result.reasons
    assert result.disclosure == []


@given(
    denied=st.sets(st.sampled_from(SECTIONS)),
    allow_only=st.sets(st.sampled_from(SECTIONS)),
    allowed=st.booleans(),
)
async def test_disclosure_always_explains_every_withheld_section(
    denied, allow_only, allowed
) -> None:
    result = await StructuredExplanationEngine().explain(
        with_attribution(
            explanation_context(policies=[deny(*denied, allowed=allowed, allow_only=allow_only)])
        )
    )

    not_allowlisted = set(SECTIONS) - allow_only if allow_only else set()
    withheld = set(SECTIONS) if not allowed else denied | not_allowlisted
    for field in SECTIONS:
        assert (getattr(result, field) == []) == (field in withheld)
    assert len(result.disclosure) == len(withheld) == len(set(result.disclosure))
    if "contributing_factors" in withheld:
        assert not any(reason.startswith("Factor ") for reason in result.reasons)


def model_returning(payload: object) -> RunnableLambda:
    return RunnableLambda(lambda _: payload)


async def test_llm_engine_requires_explicit_enablement_and_a_model() -> None:
    with pytest.raises(RuntimeError, match="disabled"):
        await LLMExplanationEngine(model_returning("{}")).explain(explanation_context())
    with pytest.raises(RuntimeError, match="require an injected"):
        await LLMExplanationEngine(enabled=True).explain(explanation_context())
    with pytest.raises(ValueError, match="timeout"):
        LLMExplanationEngine(timeout=0)


@pytest.mark.parametrize(
    "response",
    [
        json.dumps({"summary": "Review required.", "reasons": ["High risk."]}),
        '```json\n{"summary": "Review required.", "reasons": ["High risk."]}\n```',
        AIMessage(content='{"summary": "Review required.", "reasons": ["High risk."]}'),
        AIMessage(
            content=[
                {"type": "text", "text": '{"summary": "Review required.", '},
                '"reasons": ["High risk."]}',
            ]
        ),
        ExplanationDraft(summary="Review required.", reasons=["High risk."]),
        {"summary": "Review required.", "reasons": "High risk."},
    ],
    ids=["json", "fenced", "message", "content-blocks", "draft", "scalar-reasons"],
)
async def test_llm_engine_accepts_supported_response_shapes(response: object) -> None:
    engine = LLMExplanationEngine(model_returning(response), enabled=True)

    result = await engine.explain(explanation_context())

    assert result.summary == "Review required."
    assert result.reasons == ["High risk."]
    assert result.metadata == {"engine": "llm", "validated": True}


@pytest.mark.parametrize(
    ("response", "message"),
    [
        ("not json", "valid JSON"),
        (json.dumps({"summary": "x", "hidden_reasoning": "no"}), "schema validation"),
        (json.dumps({"reasons": ["missing summary"]}), "schema validation"),
        (json.dumps(["not", "an", "object"]), "schema validation"),
    ],
)
async def test_llm_engine_rejects_invalid_output(response: str, message: str) -> None:
    engine = LLMExplanationEngine(model_returning(response), enabled=True)

    with pytest.raises(ValueError, match=message):
        await engine.explain(explanation_context())


async def test_llm_engine_merges_disclosure_and_never_takes_withheld_reasons() -> None:
    payload = json.dumps(
        {"summary": "Review required.", "reasons": ["Risk 0.91"], "disclosure": "Model note."}
    )
    engine = LLMExplanationEngine(model_returning(payload), enabled=True)

    result = await engine.explain(explanation_context(policies=[deny("reasons", reason="Policy.")]))

    assert result.reasons == []
    assert result.disclosure == [
        "Decision reasons are withheld by policy.",
        "Policy.",
        "Model note.",
    ]


async def test_llm_prompt_contains_only_permitted_facts() -> None:
    prompts: list[str] = []

    def capture(prompt: str) -> str:
        prompts.append(prompt)
        return json.dumps({"summary": "ok"})

    engine = LLMExplanationEngine(RunnableLambda(capture), enabled=True)
    await engine.explain(explanation_context())
    await engine.explain(explanation_context(policies=[deny("reasons", "supporting_evidence")]))
    await engine.explain(explanation_context(policies=[deny("contributing_factors")]))
    await engine.explain(ExplanationContext(execution=execution()))

    full, restricted, no_factors, empty = (json.loads(prompt) for prompt in prompts)
    assert full["selected_action"] == "HUMAN_REVIEW"
    assert full["decision_type"] == "routing"
    assert full["candidate_actions"] == ["AUTO_APPROVE", "HUMAN_REVIEW"]
    assert [factor["name"] for factor in full["factors"]] == ["risk", "threshold"]
    assert len(full["evidence"]) == 2
    assert restricted["factors"] == restricted["evidence"] == restricted["candidate_actions"] == []
    assert restricted["withheld_by_policy"] == ["reasons", "supporting evidence"]
    assert no_factors["factors"] == []
    assert no_factors["evidence"]
    assert no_factors["withheld_by_policy"] == ["contributing factors"]
    assert full["withheld_by_policy"] == []
    assert empty["selected_action"] is None
    assert empty["decision_type"] is None
    assert "hidden reasoning" in full["instructions"]
    assert "never mention them" in full["instructions"]


async def test_llm_engine_times_out() -> None:
    async def slow(_: str) -> str:
        await asyncio.sleep(1)
        return "{}"

    engine = LLMExplanationEngine(RunnableLambda(slow), enabled=True, timeout=0.01)

    with pytest.raises(TimeoutError):
        await engine.explain(explanation_context())


untrusted_json = st.recursive(
    st.none() | st.booleans() | st.integers() | st.floats() | st.text(max_size=12),
    lambda children: (
        st.lists(children, max_size=3) | st.dictionaries(st.text(max_size=12), children, max_size=3)
    ),
    max_leaves=10,
)
draft_like = st.fixed_dictionaries(
    {},
    optional={
        "summary": untrusted_json,
        "reasons": untrusted_json,
        "disclosure": untrusted_json,
        "extra": untrusted_json,
    },
)
model_outputs = st.one_of(
    st.text(max_size=80),
    untrusted_json,
    draft_like,
    draft_like.map(json.dumps),
    draft_like.map(lambda draft: f"```json\n{json.dumps(draft)}\n```"),
    st.lists(
        st.one_of(
            st.text(max_size=20),
            st.fixed_dictionaries({"type": st.just("text"), "text": untrusted_json}),
        ),
        max_size=4,
    ),
    st.integers(min_value=1, max_value=60).map(lambda depth: "[" * depth * 1000),
)


@given(output=model_outputs, as_message=st.booleans())
def test_untrusted_model_output_is_a_draft_or_a_value_error(output, as_message: bool) -> None:
    valid_content = isinstance(output, str) or (
        isinstance(output, list) and all(isinstance(item, str | dict) for item in output)
    )
    result = AIMessage(content=output) if as_message and valid_content else output

    try:
        draft = LLMExplanationEngine._validate(result)
    except ValueError:
        return
    assert isinstance(draft, ExplanationDraft)
    assert draft.summary
