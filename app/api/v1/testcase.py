import logging

from fastapi import APIRouter, Depends, HTTPException
from langgraph.graph.state import CompiledStateGraph

from app.agents.testcase.graph import run_testcase_agent
from app.api.deps import get_llm, get_testcase_graph
from app.llm import LLMClient
from app.schemas.testcase import TestCaseGenerationRequest, TestCaseGenerationResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/agents/testcase", tags=["Test Case Generation"])


@router.post("/generate", response_model=TestCaseGenerationResponse, summary="테스트 생성")
async def generate_test_cases(
    request: TestCaseGenerationRequest,
    graph: CompiledStateGraph = Depends(get_testcase_graph),
    llm: LLMClient = Depends(get_llm),
) -> TestCaseGenerationResponse:
    logger.info("testcase_generate.request requestId=%s", request.requestId)
    logger.debug(
        "testcase_generate.request requestId=%s payload=%s",
        request.requestId,
        request.model_dump_json(),
    )
    try:
        return await run_testcase_agent(request, graph, llm)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Agent error: {exc}")
