from langgraph.graph import StateGraph, END

from app.agents.testcase.state import TestCaseAgentState
from app.agents.testcase.nodes import parse_request, generate_drafts, deduplicate
from app.llm import LLMClient
from app.schemas.testcase import TestCaseGenerationRequest, TestCaseGenerationResponse


def _has_error(state: TestCaseAgentState) -> str:
    return "end" if state.get("error") else "generate"


def build_graph(llm: LLMClient) -> StateGraph:
    graph = StateGraph(TestCaseAgentState)

    graph.add_node("parse", parse_request)
    graph.add_node("generate", generate_drafts)
    graph.add_node("dedup", deduplicate)

    graph.set_entry_point("parse")
    graph.add_conditional_edges("parse", _has_error, {"end": END, "generate": "generate"})
    graph.add_edge("generate", "dedup")
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
    }

    final_state: TestCaseAgentState = await graph.ainvoke(initial_state)

    if final_state.get("error"):
        raise ValueError(final_state["error"])

    if not final_state["drafts"]:
        raise ValueError("No test cases generated. Please retry.")

    return TestCaseGenerationResponse(
        requestId=request.requestId,
        generationId=request.generationContext.generationId,
        drafts=final_state["drafts"],
    )

# orchestrator를 위한 동기 버전 추가
def run_testcase_agent_sync(
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
    }

    # ainvoke 대신 invoke 사용
    final_state: TestCaseAgentState = graph.invoke(initial_state)

    if final_state.get("error"):
        raise ValueError(final_state["error"])

    if not final_state["drafts"]:
        raise ValueError("No test cases generated. Please retry.")

    return TestCaseGenerationResponse(
        requestId=request.requestId,
        generationId=request.generationContext.generationId,
        drafts=final_state["drafts"],
    )