"""Automatic capture of retrievals and tool calls, turned into evidence for a decision.

A support graph retrieves policy passages with a LangChain retriever, runs the tool
call the model requested through LangGraph's ``ToolNode``, and decides whether the
customer is eligible for a refund. Retrievals and tool calls are captured without any
explainability code; the ``decide`` node references them as evidence and records its
decision. Model output is simulated so the example runs offline.

Run with:

    uv run python examples/retrieval_and_tools.py
"""

import asyncio
from typing import Annotated, TypedDict

from _shared import show
from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langchain_core.documents import Document
from langchain_core.messages import AIMessage, AnyMessage
from langchain_core.retrievers import BaseRetriever
from langchain_core.tools import tool
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

from langgraph_xai import (
    DecisionFactor,
    DecisionType,
    EvidenceType,
    SourceReference,
    XAIRuntime,
)

xai = XAIRuntime(application_id="support", tenant_id="acme", graph_id="refund-assistant")

POLICIES = [
    Document(
        id="refund-policy#3",
        page_content="Orders delivered within the last 30 days can be refunded.",
        metadata={"source": "kb://policies/refunds#3", "score": 0.92},
    ),
    Document(
        id="shipping-policy#1",
        page_content="Shipping fees are refunded only for damaged items.",
        metadata={"source": "kb://policies/shipping#1", "score": 0.41},
    ),
]


class PolicyRetriever(BaseRetriever):
    def _get_relevant_documents(
        self, query: str, *, run_manager: CallbackManagerForRetrieverRun
    ) -> list[Document]:
        return POLICIES


@tool
def order_status(order_id: str) -> str:
    """Look up when an order was delivered."""
    return f"Order {order_id} was delivered 12 days ago."


class Support(TypedDict, total=False):
    question: str
    messages: Annotated[list[AnyMessage], add_messages]
    decision: str


retriever = PolicyRetriever().with_config(run_name="policy-index")


async def retrieve(state: Support) -> Support:
    await retriever.ainvoke(state["question"])
    return {}


async def plan(state: Support) -> Support:
    request = AIMessage(
        content="",
        tool_calls=[{"name": "order_status", "args": {"order_id": "A-1042"}, "id": "call_7Qk2"}],
    )
    return {"messages": [request]}


async def decide(state: Support) -> Support:
    run = xai.current_run
    assert run is not None
    (retrieval,) = run.execution.retrievals
    evidence = [
        await xai.record_evidence(
            EvidenceType.RETRIEVAL_DOCUMENT,
            summary=f"Policy passage {document.document_id} (rank {document.rank}).",
            content_reference=document.content_reference,
            source=SourceReference(source_id=retrieval.retriever_id, source_type="retriever"),
            confidence=document.score,
        )
        for document in retrieval.documents
    ]
    (lookup,) = run.execution.tools
    delivery = await xai.record_evidence(
        EvidenceType.TOOL_RESULT,
        summary="Order A-1042 was delivered 12 days ago.",
        content_reference=f"tool-call://{lookup.tool_call_id}",
        confidence=1.0,
    )
    await xai.record_decision(
        "APPROVE_REFUND",
        decision_type=DecisionType.APPROVAL,
        candidate_actions=["APPROVE_REFUND", "DENY_REFUND", "ESCALATE"],
        evidence_ids=[evidence[0].id, delivery.id],
        factors=[
            DecisionFactor(name="days_since_delivery", value=12, evidence_ids=[delivery.id]),
            DecisionFactor(name="refund_window_days", value=30, evidence_ids=[evidence[0].id]),
        ],
    )
    return {"decision": "APPROVE_REFUND"}


def build_graph():
    builder = StateGraph(Support)
    builder.add_node("retrieve", retrieve)
    builder.add_node("plan", plan)
    builder.add_node("tools", ToolNode([order_status]))
    builder.add_node("decide", decide)
    builder.add_edge(START, "retrieve")
    builder.add_edge("retrieve", "plan")
    builder.add_edge("plan", "tools")
    builder.add_edge("tools", "decide")
    builder.add_edge("decide", END)
    return builder.compile()


async def main() -> None:
    graph = xai.instrument(build_graph())
    with xai.collect_runs() as runs:
        result = await graph.ainvoke({"question": "Can I get a refund for order A-1042?"})
    (run,) = runs
    execution = run.execution

    print(f"Decision: {result['decision']}")
    show(
        "Captured retrieval",
        {
            "retriever": execution.retrievals[0].retriever_id,
            "documents": [
                document.model_dump(include={"document_id", "rank", "score", "content_reference"})
                for document in execution.retrievals[0].documents
            ],
        },
    )
    show(
        "Captured tool call",
        execution.tools[0].model_dump(
            mode="json", include={"tool_name", "tool_call_id", "status", "latency_ms"}
        ),
    )
    explanation = await xai.explain_decision(run.decisions[0], audience="end_user", run=run)
    show(
        "Explanation",
        explanation.model_dump(mode="json", include={"summary", "reasons", "disclosure"}),
    )


if __name__ == "__main__":
    asyncio.run(main())
