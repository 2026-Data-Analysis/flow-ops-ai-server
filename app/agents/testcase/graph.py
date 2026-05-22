from langgraph.graph import StateGraph, END

from app.agents.testcase.state import TestCaseAgentState
from app.agents.testcase.nodes import parse_request, generate_drafts, deduplicate
from app.llm import LLMClient
from app.schemas.testcase import TestCaseGenerationRequest, TestCaseGenerationResponse
MAX_RETRIES = 2


def _has_error(state: TestCaseAgentState) -> str:
    return "end" if state.get("error") else "generate"


def _check_drafts(state: TestCaseAgentState) -> str:
    if state.get("raw_drafts"):
        return "dedup"
    if state.get("retry_count", 0) < MAX_RETRIES:
        return "retry"
    return "end"


def _bump_retry(state: TestCaseAgentState) -> dict:
    return {"retry_count": state.get("retry_count", 0) + 1}


def build_graph(llm: LLMClient) -> StateGraph:
    graph = StateGraph(TestCaseAgentState)

    graph.add_node("parse", parse_request)
    graph.add_node("generate", generate_drafts)
    graph.add_node("bump_retry", _bump_retry)
    graph.add_node("dedup", deduplicate)

    graph.set_entry_point("parse")
    graph.add_conditional_edges("parse", _has_error, {"end": END, "generate": "generate"})
    graph.add_conditional_edges(
        "generate",
        _check_drafts,
        {"dedup": "dedup", "retry": "bump_retry", "end": END},
    )
    graph.add_edge("bump_retry", "generate")
    graph.add_edge("dedup", END)

    return graph


async def run_testcase_agent(
    request: TestCaseGenerationRequest,
    graph,
    llm: LLMClient,
) -> TestCaseGenerationResponse:
    initial_state: TestCaseAgentState = {
        "llm": llm,
        "request": request,
        "raw_drafts": [],
        "drafts": [],
        "error": None,
        "retry_count": 0,
    }

    final_state: TestCaseAgentState = await graph.ainvoke(initial_state)

    if final_state.get("error"):
        raise ValueError(final_state["error"])

    if not final_state.get("raw_drafts"):
        raise ValueError(
            f"LLM이 {MAX_RETRIES}번 재시도 후에도 테스트 케이스를 생성하지 못했습니다."
        )

    return TestCaseGenerationResponse(
        requestId=request.requestId,
        generationId=request.generationContext.generationId,
        drafts=final_state["drafts"],
    )
