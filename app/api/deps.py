"""FastAPI 의존성 정의.

설계 결정:
1. LLMClient와 컴파일된 그래프는 lifespan에서 app.state에 저장.
2. 핸들러는 Request 객체를 통해 app.state에 접근.
3. 테스트에서 의존성 오버라이드도 깔끔하게 처리 가능.
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


def get_testcase_graph(request: Request) -> "CompiledStateGraph":
    return request.app.state.testcase_graph


def get_scenario_graph(request: Request) -> "CompiledStateGraph":
    return request.app.state.scenario_graph


def get_incident_graph(request: Request) -> "CompiledStateGraph":
    """lifespan에서 만들어둔 Incident Agent 그래프 반환."""
    return request.app.state.incident_graph


def get_orchestrator_graph(request: Request) -> "CompiledStateGraph":
    """lifespan에서 만들어둔 Orchestrator Agent 그래프 반환."""
    return request.app.state.orchestrator_graph
