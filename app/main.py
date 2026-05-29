"""FastAPI 앱 진입점.

실행:
    uvicorn app.main:app --reload --port 8000

환경변수:
    FLOWOPS_ANTHROPIC_API_KEY=sk-ant-...
    FLOWOPS_ANTHROPIC_MODEL=claude-sonnet-4-5  (선택)
    FLOWOPS_LOG_LEVEL=INFO                      (선택)

그래프 빌드 순서 (의존 관계 주의):
1. llm
2. testcase_graph, scenario_graph, incident_graph  (독립)
3. orchestrator_graph  (위 세 그래프를 주입받음)
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI

from app.agents.api_management.graph import build_graph as build_api_management_graph
from app.agents.incident.graph import build_graph as build_incident_graph
from app.agents.orchestrator.graph import build_graph as build_orchestrator_graph
from app.agents.scenario.graph import build_graph as build_scenario_graph
from app.agents.testcase.graph import build_graph as build_testcase_graph
from app.api.v1 import incident as incident_router
from app.api.v1 import orchestrator as orchestrator_router
from app.api.v1 import scenario as scenario_router
from app.api.v1 import testcase as testcase_router
from app.core.config import get_settings
from app.llm import AnthropicClient


def _configure_logging(level: str) -> None:
    logging.basicConfig(
        level=level.upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """앱 수명주기 동안 1회만 실행되는 셋업/티어다운."""
    settings = get_settings()
    _configure_logging(settings.log_level)
    logger = logging.getLogger(__name__)
    logger.info("FlowOps AI starting (model=%s)", settings.anthropic_model)

    llm = AnthropicClient(
        api_key=settings.anthropic_api_key.get_secret_value(),
        model=settings.anthropic_model,
    )

    # 독립 그래프 먼저 컴파일
    testcase_graph = build_testcase_graph(llm).compile()
    scenario_graph = build_scenario_graph(llm).compile()
    incident_graph = build_incident_graph(llm).compile()
    api_management_graph = build_api_management_graph(llm).compile()

    # Orchestrator는 위 세 그래프를 모두 주입받음
    orchestrator_graph = build_orchestrator_graph(
        llm=llm,
        testcase_graph=testcase_graph,
        scenario_graph=scenario_graph,
        incident_graph=incident_graph,
        api_management_graph=api_management_graph,
    ).compile()

    app.state.llm = llm
    app.state.testcase_graph = testcase_graph
    app.state.scenario_graph = scenario_graph
    app.state.incident_graph = incident_graph
    app.state.orchestrator_graph = orchestrator_graph
    app.state.api_management_graph = api_management_graph

    try:
        yield
    finally:
        logger.info("FlowOps AI shutting down")


app = FastAPI(
    title="FlowOps AI",
    description="QA/QC 자동화 멀티 에이전트 서비스",
    version="0.2.0",
    lifespan=lifespan,
)

# 라우터 등록
app.include_router(scenario_router.router)
app.include_router(testcase_router.router)
app.include_router(incident_router.router)
app.include_router(orchestrator_router.router)


@app.get("/health", tags=["meta"], summary="헬스 체크")
def health() -> dict[str, str]:
    return {"status": "ok"}
