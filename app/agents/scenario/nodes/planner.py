"""시나리오 플래너 노드.

자연어 모드: request.user_intent를 받아 LLM에게 시나리오 시퀀스를 만들게 함.
추천 모드: coverage_gaps의 각 갭을 user_intent처럼 사용 (향후 구현).

LLM 출력 → 검증 → Scenario 객체 조립 → State 갱신.

[1단계 변경]
LLM 출력 스키마(PlannerStep)는 그대로 두고, 조립 단계(_assemble_scenarios)에서
새 ScenarioStep(testcase draft 호환 구조)로 변환한다.
- endpoint_id            -> apiId
- name                   -> title
- static_payload         -> requestSpec.body
- static_params          -> requestSpec.pathParams / queryParams (inventory 기준 분류)
- expected_status_code   -> expectedSpec.statusCode / assertionSpec.statusCode
- type                   -> 기본 HAPPY_PATH (Step 2에서 LLM이 분류하도록 확장 예정)
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from app.agents.scenario.state import AgentError, ScenarioAgentState
from app.llm import LLMClient
from app.llm.prompts.scenario_planner import SYSTEM_PROMPT, build_user_prompt
from app.schemas import (
    DRAFT_TO_TEST_CASE_TYPE,
    APIEndpoint,
    APIInventory,
    DraftType,
    Scenario,
    ScenarioGenerationMode,
    ScenarioMeta,
    ScenarioStep,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# LLM 출력 전용 스키마
# ---------------------------------------------------------------------------
# 우리의 Scenario 스키마에는 step_id(uuid), scenario_id(uuid) 같은 서버 발급 필드가 있음.
# LLM에게 이런 걸 만들게 하면 토큰 낭비 + 형식 오류 위험.
# LLM 출력용 슬림 스키마를 별도로 정의하고, 우리 코드가 진짜 객체로 조립한다.


class PlannerStep(BaseModel):
    ref: str = Field(description="스텝 단축 식별자. 'step_1', 'step_2' 형식")
    order: int = Field(ge=1, description="실행 순서. 1부터")
    endpoint_id: str = Field(description="API Inventory에 존재하는 endpoint_id")
    name: str = Field(description="이 스텝이 무엇을 하는지 짧은 이름")
    description: str | None = None
    static_payload: dict[str, Any] | None = Field(
        default=None,
        description="요청 바디의 고정 값. 동적 값(이전 응답)은 여기 넣지 말 것",
    )
    static_params: dict[str, Any] = Field(
        default_factory=dict,
        description="경로/쿼리 파라미터 고정 값",
    )
    expected_status_code: int = Field(default=200, ge=100, le=599)
    expected_assertions: list[str] = Field(default_factory=list)


class PlannerScenario(BaseModel):
    name: str = Field(description="시나리오 이름")
    description: str | None = None
    rationale: str = Field(description="왜 이 흐름을 만들었는지 한 줄 설명")
    steps: list[PlannerStep]


class PlannerOutput(BaseModel):
    """LLM이 emit_scenarios 도구로 반환할 페이로드."""

    scenarios: list[PlannerScenario]


# ---------------------------------------------------------------------------
# 노드 팩토리
# ---------------------------------------------------------------------------
# LangGraph 노드는 (state) -> dict 시그니처여야 함.
# 그런데 우리는 LLMClient를 주입받고 싶다 → 클로저 팩토리로 해결.


def make_planner_node(llm: LLMClient):
    """LLMClient를 캡처한 planner 노드 함수를 반환."""

    def planner_node(state: ScenarioAgentState) -> dict:
        request = state["request"]
        inventory = request.api_inventory

        # 자연어 모드만 우선 구현
        if request.mode == ScenarioGenerationMode.NATURAL_LANGUAGE:
            if not request.user_intent:
                return _err_only("planner", "MISSING_USER_INTENT",
                                 "자연어 모드인데 user_intent가 비어있음")
            user_intent = request.user_intent
        else:
            # 추천 모드: coverage_gaps를 합쳐서 의도 문자열로
            gaps = state.get("coverage_gaps", [])
            if not gaps:
                # 추천 모드인데 recommender가 갭을 못 찾았으면 빈 결과 반환
                return {"planned_scenarios": []}
            user_intent = "\n".join(
                f"- {g['description']}: {g['suggested_flow']}" for g in gaps
            )

        user_prompt = build_user_prompt(
            user_intent=user_intent,
            inventory=inventory,
            max_scenarios=request.max_scenarios,
            max_steps_per_scenario=request.max_steps_per_scenario,
        )

        try:
            raw_output, usage = llm.generate_structured(
                system=SYSTEM_PROMPT,
                user=user_prompt,
                output_schema=PlannerOutput.model_json_schema(),
                output_name="emit_scenarios",
                output_description="설계된 시나리오 목록을 반환",
                max_tokens=4096,
                temperature=0.1,
            )
        except Exception as e:
            logger.exception("planner LLM call failed")
            return _err_only("planner", "LLM_CALL_FAILED", str(e))

        # LLM 출력 파싱
        try:
            parsed = PlannerOutput.model_validate(raw_output)
        except ValidationError as e:
            logger.error("planner output validation failed: %s", e)
            return {
                "errors": [AgentError(
                    node="planner",
                    code="OUTPUT_VALIDATION_FAILED",
                    message=str(e),
                )],
                "token_usages": [usage],
            }

        # endpoint_id, ref 검증 + Scenario 조립
        scenarios, errs = _assemble_scenarios(parsed, inventory)

        return {
            "planned_scenarios": scenarios,
            "errors": errs,
            "token_usages": [usage],
        }

    return planner_node


# ---------------------------------------------------------------------------
# 내부 헬퍼
# ---------------------------------------------------------------------------


def _build_request_spec(ep: APIEndpoint, step: PlannerStep) -> dict[str, Any]:
    """PlannerStep의 static_payload / static_params를 testcase requestSpec 구조로 변환.

    static_params는 inventory의 parameters 정의(location)로 path/query를 분류한다.
    parameters에 정의가 없으면 경로 템플릿('{name}') 포함 여부로 path/query를 판단.
    """
    loc_by_name = {p.name: p.location for p in ep.parameters}

    path_params: dict[str, Any] = {}
    query_params: dict[str, Any] = {}
    for name, value in (step.static_params or {}).items():
        location = loc_by_name.get(name)
        if location == "path":
            path_params[name] = value
        elif location == "query":
            query_params[name] = value
        elif "{" + name + "}" in ep.path:
            path_params[name] = value
        else:
            query_params[name] = value

    return {
        "method": ep.method.value,
        "pathParams": path_params,
        "queryParams": query_params,
        "body": step.static_payload,
    }


def _assemble_scenarios(
    parsed: PlannerOutput,
    inventory: APIInventory,
) -> tuple[list[Scenario], list[AgentError]]:
    """LLM이 만든 PlannerOutput을 검증하고 진짜 Scenario 객체로 변환.

    검증 실패한 시나리오는 결과에서 제외하고 에러만 기록.
    """
    by_id = inventory.by_id()
    valid_ids = set(by_id.keys())
    scenarios: list[Scenario] = []
    errors: list[AgentError] = []

    for ps in parsed.scenarios:
        # ref 중복 검사
        refs = [s.ref for s in ps.steps]
        if len(refs) != len(set(refs)):
            errors.append(AgentError(
                node="planner",
                code="DUPLICATE_STEP_REF",
                message=f"시나리오 '{ps.name}': 중복 ref - {refs}",
            ))
            continue

        # endpoint_id 존재 확인
        bad_ids = [s.endpoint_id for s in ps.steps if s.endpoint_id not in valid_ids]
        if bad_ids:
            errors.append(AgentError(
                node="planner",
                code="UNKNOWN_ENDPOINT_ID",
                message=f"시나리오 '{ps.name}': inventory에 없는 endpoint - {bad_ids}",
            ))
            continue

        # order 일관성 확인 (1, 2, 3, ... 순서)
        sorted_steps = sorted(ps.steps, key=lambda s: s.order)
        if [s.order for s in sorted_steps] != list(range(1, len(sorted_steps) + 1)):
            errors.append(AgentError(
                node="planner",
                code="INVALID_STEP_ORDER",
                message=f"시나리오 '{ps.name}': order가 1부터 연속되지 않음",
            ))
            continue

        # 진짜 Scenario 객체로 변환 (testcase draft 호환 구조)
        steps: list[ScenarioStep] = []
        for s in sorted_steps:
            ep = by_id[s.endpoint_id]
            draft_type = DraftType.HAPPY_PATH  # Step 2에서 LLM 분류로 확장 예정
            steps.append(ScenarioStep(
                ref=s.ref,
                order=s.order,
                chained_variables=[],  # chainer 노드가 채움
                apiId=s.endpoint_id,
                title=s.name,
                description=s.description,
                type=draft_type,
                test_case_type=DRAFT_TO_TEST_CASE_TYPE[draft_type],
                requestSpec=_build_request_spec(ep, s),
                expectedSpec={
                    "statusCode": s.expected_status_code,
                    "body": None,
                    "errorMessage": None,
                },
                assertionSpec={
                    "statusCode": s.expected_status_code,
                    "bodyContains": [],
                    "bodyEquals": {},
                    "headerContains": {},
                },
                duplicate=False,
                expected_assertions=s.expected_assertions,
            ))

        scenarios.append(Scenario(
            name=ps.name,
            description=ps.description,
            steps=steps,
            meta=ScenarioMeta(rationale=ps.rationale),
        ))

    return scenarios, errors


def _err_only(node: str, code: str, message: str) -> dict:
    """에러만 반환하는 단축 헬퍼."""
    return {"errors": [AgentError(node=node, code=code, message=message)]}