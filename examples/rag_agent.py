"""Retrieval evidence references without persisting raw document content."""

import asyncio

from _shared import compiled_graph, explain_result

from langgraph_xai import DecisionFactor, RetrievedDocument, XAIRuntime


async def main() -> None:
    runtime = XAIRuntime(graph_id="rag")
    run = await runtime.start_run()
    await runtime.record_retrieval(
        "local-documents",
        documents=[
            RetrievedDocument(
                document_id="policy-1",
                chunk_id="policy-1#3",
                rank=1,
                score=0.93,
                content_reference="docs://policy-1#3",
            )
        ],
        run=run,
    )
    await runtime.finish_run(run)
    result = await runtime.instrument(
        compiled_graph(lambda _: {"answer": "Returns are accepted for 30 days."})
    ).ainvoke({"query": "What is the return policy?"})
    explanation = await explain_result(
        runtime,
        "ANSWER_FROM_RETRIEVAL",
        DecisionFactor(name="retrieval_score", value=0.93),
    )
    print(result, explanation)


if __name__ == "__main__":
    asyncio.run(main())
