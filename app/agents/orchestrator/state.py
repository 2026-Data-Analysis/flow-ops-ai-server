"""Orchestrator Agent의 LangGraph State.

처리 흐름:
  intent_classifier → dispatcher → aggregator → END

설계 결정:
1. 사용자의 자연어 프롬프트를 받아 어떤 Agent(들)를 호출할지 결정.
2. 하나의 프롬프트가 여러 Agent를 순차 호출할 수 있음
   (예: "로그 분석 후 테스트 케이스도 만들어줘").
3. dispatched_agents: 실행한 Agent 이름 목록 → 서버가 어떤 Agent가 쓰였는지 파악.
4. agent_results: Agent별 결과를 키-값으로 저장.
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict

from app.schemas import TokenUsage
from app.schemas.orchestrator import AgentResultItem


class OrchestratorError(TypedDict):
    node: str
    code: str
    message: str


AgentCallResult = AgentResultItem



class OrchestratorAgentState(TypedDict, total=False):
    # 입력
    user_prompt: str
    project_id: str 
    context: dict[str, Any]  # api_inventory, log_entries 등 추가 컨텍스트

    # intent_classifier 출력
    intent_plan: list[dict]
    # 예: [{"agent": "incident", "priority": 1, "extracted_params": {...}},
    #      {"agent": "testcase", "priority": 2, "extracted_params": {...}}]

    # dispatcher 출력
    dispatched_agents: list[str]    # 실행된 Agent 이름 목록 (서버 응답용)
    agent_results: list[AgentCallResult]

    # aggregator 출력
    summary: str  # 전체 실행 결과를 자연어로 요약

    # 누적
    errors: Annotated[list[OrchestratorError], operator.add]
    token_usages: Annotated[list[TokenUsage], operator.add]
    trace_id: str


def initial_state(
    user_prompt: str,
    project_id: str,
    context: dict[str, Any],
    trace_id: str,
) -> OrchestratorAgentState:
    return OrchestratorAgentState(
        user_prompt=user_prompt,
        project_id=project_id,
        context=context,
        errors=[],
        token_usages=[],
        dispatched_agents=[],
        agent_results=[],
        trace_id=trace_id,
    )
