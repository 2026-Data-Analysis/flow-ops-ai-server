"""시나리오 플래너 노드.

자연어 모드: request.user_intent를 받아 LLM에게 시나리오 시퀀스를 만들게 함.
추천 모드: coverage_gaps의 각 갭을 user_intent처럼 사용 (향후 구현).

LLM 출력 → 검증 → Scenario 객체 조립 → State 갱신.

[2단계 변경]
LLM이 testcase draft와 동일한 필드(type/requestSpec/expectedSpec/assertionSpec)를
직접 채우도록 PlannerStep 확장. 조립 단계는 ScenarioStep으로 거의 1:1 매핑.
- requestSpec.method는 LLM 값과 무관하게 inventory 기준으로 강제 교정.
- test_case_type은 type으로부터 DRAFT_TO_TEST_CASE_TYPE 매핑.
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
    title: str = Field(description="이 스텝이 무엇을 하는지 짧은 이름")
    description: str | None = None

    type: DraftType = Field(
        default=DraftType.HAPPY_PATH,
        description="HAPPY_PATH | VALIDATION | FAILURE_HANDLING | EDGE_CASE | AUTHORIZATION | PERFORMANCE",
    )
    userRole: str | None = None
    stateCondition: str | None = None
    dataVariant: str | None = None

    requestSpec: dict[str, Any] | None = Field(
        default=None,
        description=(
            "{method, pathParams, queryParams, body}. "
            "body는 endpoint의 request_body_schema 구조의 정적 값만. "
            "동적 값(이전 응답)은 비워둘 것 (chainer가 채움)."
        ),
    )
    expectedSpec: dict[str, Any] | None = Field(
        default=None,
        description="{statusCode, body, errorMessage}",
    )
    assertionSpec: dict[str, Any] | None = Field(
        default=None,
        description="{statusCode, bodyContains, bodyEquals, headerContains}",
    )


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


def _normalize_request_spec(ep: APIEndpoint, raw: dict[str, Any] | None) -> dict[str, Any]:
    """LLM이 만든 requestSpec을 표준 구조로 정규화.

    - method는 LLM 값과 무관하게 inventory 기준으로 강제 (LLM이 틀려도 교정).
    - pathParams/queryParams/body 키를 항상 존재하도록 보정.
    """
    raw = raw or {}
    return {
        "method": ep.method.value,
        "pathParams": raw.get("pathParams") or {},
        "queryParams": raw.get("queryParams") or {},
        "body": raw.get("body"),
    }


def _assemble_scenarios(
    parsed: PlannerOutput,
    inventory: APIInventory,
) -> tuple[list[Scenario], list[AgentError]]:
    """LLM이 만든 PlannerOutput을 검증하고 진짜 Scenario 객체로 변환.

    검증 실패한 시나리오는 결과에서 제외하고 에러만 기록.
    (requestSpec.body의 스키마 정합성 검증은 validator 노드(4단계) 담당)
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
            steps.append(ScenarioStep(
                ref=s.ref,
                order=s.order,
                chained_variables=[],  # chainer 노드가 채움
                apiId=s.endpoint_id,
                title=s.title,
                description=s.description,
                type=s.type,
                test_case_type=DRAFT_TO_TEST_CASE_TYPE[s.type],
                userRole=s.userRole,
                stateCondition=s.stateCondition,
                dataVariant=s.dataVariant,
                requestSpec=_normalize_request_spec(ep, s.requestSpec),
                expectedSpec=s.expectedSpec,
                assertionSpec=s.assertionSpec,
                duplicate=False,
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