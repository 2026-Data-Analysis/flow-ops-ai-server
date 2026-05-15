"""시나리오 Agent의 LangGraph 노드 stub 모음.

각 노드는 실제 LLM 호출 없이 State를 통과시키는 placeholder.
실제 구현된 노드는 _stubs.py에서 빠지고 별도 파일로 옮겨진다.

현재 stub: intent_parser, recommender, validator
실제 구현: planner.py, chainer.py
"""

from __future__ import annotations

from app.agents.scenario.state import ScenarioAgentState
from app.schemas import ScenarioGenerationMode


def intent_parser_node(state: ScenarioAgentState) -> dict:
    """사용자 요청의 의도를 분석해 route를 결정.

    현 단계는 mode를 그대로 route로 매핑.
    추후 자연어 입력이 들어왔지만 실제로는 추천을 원하는 경우 등 분기 가능.
    """
    mode = state["request"].mode
    if mode == ScenarioGenerationMode.NATURAL_LANGUAGE:
        route = "natural"
    else:
        route = "recommend"
    return {"route": route}


def recommender_node(state: ScenarioAgentState) -> dict:
    """추천 모드 한정: 기존 테스트 이력 기반으로 부족한 시나리오 도출.

    STUB: 현재는 빈 갭 리스트 반환.
    """
    return {"coverage_gaps": []}


def validator_node(state: ScenarioAgentState) -> dict:
    """생성 결과 검증.

    - 각 step의 endpoint_id가 실제 inventory에 존재하는가
    - chained_variables의 source_step_ref가 유효한가
    - 순환 참조가 없는가

    STUB: 현재는 검증 없이 통과.
    """
    return {}


def route_after_intent(state: ScenarioAgentState) -> str:
    """intent_parser 다음 분기를 결정하는 conditional edge 함수.

    LangGraph의 conditional edge는 다음 노드 이름(문자열)을 반환해야 함.
    """
    return "recommender" if state["route"] == "recommend" else "planner"
