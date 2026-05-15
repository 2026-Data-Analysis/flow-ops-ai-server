"""시나리오 테스트 Agent의 LangGraph State.

설계 결정:
1. State는 TypedDict로 정의 (LangGraph 권장 패턴).
2. 입력(request)은 처음에 한 번 들어오고 노드들은 읽기만 함.
3. 중간 산출물은 단계별로 분리:
   - coverage_gaps: 추천 모드에서 recommender가 찾아낸 갭들
   - planned_scenarios: planner가 만든 시나리오 (chaining 변수 비어있음)
   - final_scenarios: chainer가 변수 매핑 채운 최종 시나리오
4. errors, token_usages는 여러 노드가 누적해야 하므로 Annotated + reducer 사용.
5. validator의 결과는 final_scenarios를 갱신하거나 errors에 추가하는 식으로 흘러감.
"""

from __future__ import annotations

import operator
from typing import Annotated, TypedDict

from app.schemas import (
    Scenario,
    ScenarioGenerationRequest,
    TokenUsage,
)


class CoverageGap(TypedDict):
    """추천 모드에서 식별된 커버리지 갭 한 건.

    recommender가 만들고, planner가 이걸 입력으로 받아 실제 Scenario로 확장.
    """

    description: str          # 예: "결제 실패 후 재시도 흐름이 없음"
    suggested_flow: str       # 자연어로 표현된 추천 흐름. planner의 입력이 됨.
    related_endpoint_ids: list[str]


class AgentError(TypedDict):
    """노드 실행 중 발생한 에러 1건."""

    node: str                 # 어느 노드에서 발생했는지
    code: str                 # 식별자. 예: "INVALID_JSON", "ENDPOINT_NOT_FOUND"
    message: str


class ScenarioAgentState(TypedDict, total=False):
    """시나리오 Agent의 공유 State.

    total=False로 두어 노드가 부분 갱신만 반환해도 되도록 함 (LangGraph 컨벤션).
    """

    # === 입력 (intent_parser 진입 시 채워짐, 이후 읽기 전용) ===
    request: ScenarioGenerationRequest

    # === intent_parser 출력 ===
    route: str
    # "natural" | "recommend"
    # mode와 거의 같지만, 향후 자연어 입력 안에 추천 요청이 섞여있으면
    # intent_parser가 재분류할 수 있도록 별도 필드로 둠.

    # === recommender 출력 (추천 모드일 때만) ===
    coverage_gaps: list[CoverageGap]

    # === planner 출력 ===
    planned_scenarios: list[Scenario]
    # 이 시점에서는 chained_variables가 비어있을 수 있음.
    # planner는 흐름 설계에 집중하고, chainer가 변수 매핑을 채움.

    # === chainer 출력 ===
    final_scenarios: list[Scenario]
    # chained_variables까지 모두 채워진 완성된 시나리오들.

    # === validator 출력 ===
    # validator는 final_scenarios를 검증하고, 문제가 있으면 errors에 추가하거나
    # 수정 가능한 경우 final_scenarios를 갱신.

    # === 누적되는 메타데이터 ===
    # operator.add를 reducer로 사용하면 노드가 반환한 리스트가 기존 리스트에 append됨.
    errors: Annotated[list[AgentError], operator.add]
    token_usages: Annotated[list[TokenUsage], operator.add]

    # === 추적 ===
    trace_id: str


def initial_state(
    request: ScenarioGenerationRequest,
    trace_id: str,
) -> ScenarioAgentState:
    """초기 State 생성 헬퍼.

    그래프 실행 진입점에서 호출. errors/token_usages를 빈 리스트로
    명시 초기화하지 않으면 reducer가 None과 list를 더하다 터질 수 있음.
    """
    return ScenarioAgentState(
        request=request,
        errors=[],
        token_usages=[],
        trace_id=trace_id,
    )
