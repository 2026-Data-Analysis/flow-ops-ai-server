"""FastAPI 의존성 정의.

핸들러는 Depends(...)로 이 함수들을 받아온다. 객체 생성 비용이 큰 것들은
lifespan에서 만들어두고 여기서 꺼내쓰는 패턴.

설계 결정:
1. LLMClient와 컴파일된 그래프는 lifespan에서 app.state에 저장.
2. 핸들러는 Request 객체를 통해 app.state에 접근.
3. 이러면 테스트에서 의존성 오버라이드도 깔끔.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import Request

if TYPE_CHECKING:
    from langgraph.graph.state import CompiledStateGraph

    from app.llm import LLMClient


def get_llm(request: Request) -> "LLMClient":
    """lifespan에서 만들어둔 LLM 클라이언트 반환."""
    return request.app.state.llm


def get_scenario_graph(request: Request) -> "CompiledStateGraph":
    """lifespan에서 만들어둔 시나리오 Agent 그래프 반환."""
    return request.app.state.scenario_graph
