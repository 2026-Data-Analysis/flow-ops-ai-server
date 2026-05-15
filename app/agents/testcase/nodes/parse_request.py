from app.agents.testcase.state import TestCaseAgentState


async def parse_request(state: TestCaseAgentState) -> dict:
    """요청 유효성 검사 및 미지원 모드 게이트."""
    req = state["request"]

    if req.generationContext.mode == "FROM_FAILURE":
        return {**state, "error": "FROM_FAILURE mode is not yet supported."}

    if not req.apis:
        return {**state, "error": "No APIs provided for test case generation."}

    return {**state, "error": None}
