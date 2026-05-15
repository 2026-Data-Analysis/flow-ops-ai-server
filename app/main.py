"""FastAPI 앱 진입점.

실행:
    uvicorn app.main:app --reload --port 8000

환경변수:
    FLOWOPS_ANTHROPIC_API_KEY=sk-ant-...
    FLOWOPS_ANTHROPIC_MODEL=claude-sonnet-4-5  (선택)
    FLOWOPS_LOG_LEVEL=INFO                      (선택)

설계 결정:
1. lifespan에서 LLM 클라이언트와 컴파일된 그래프를 만들어 app.state에 저장.
   - LLM 객체와 그래프 컴파일을 매 요청마다 하면 큰 낭비.
2. 라우터 prefix 안 붙임. 라우터 모듈 자체에 prefix가 있음.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI

from app.agents.scenario.graph import build_graph
from app.api.v1 import scenario as scenario_router
from app.core.config import get_settings
from app.llm import AnthropicClient


def _configure_logging(level: str) -> None:
    logging.basicConfig(
        level=level.upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """앱 수명주기 동안 1회만 실행되는 셋업/티어다운.

    여기서 LLM 클라이언트와 그래프를 만들어 app.state에 보관.
    """
    settings = get_settings()
    _configure_logging(settings.log_level)
    logger = logging.getLogger(__name__)
    logger.info("FlowOps AI starting (model=%s)", settings.anthropic_model)

    llm = AnthropicClient(
        api_key=settings.anthropic_api_key.get_secret_value(),
        model=settings.anthropic_model,
    )
    scenario_graph = build_graph(llm).compile()

    app.state.llm = llm
    app.state.scenario_graph = scenario_graph

    try:
        yield
    finally:
        logger.info("FlowOps AI shutting down")


app = FastAPI(
    title="FlowOps AI",
    description="QA/QC 자동화 멀티 에이전트 서비스 — 시나리오 테스트 Agent",
    version="0.1.0",
    lifespan=lifespan,
)

# 라우터 등록
app.include_router(scenario_router.router)


@app.get("/health", tags=["meta"], summary="헬스 체크")
def health() -> dict[str, str]:
    """간단한 liveness 체크. 외부 의존성(LLM API)은 검사하지 않음."""
    return {"status": "ok"}
