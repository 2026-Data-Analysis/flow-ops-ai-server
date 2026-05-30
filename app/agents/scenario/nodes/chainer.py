"""Response Chainer 노드.

planner가 만든 시나리오의 각 step에 chained_variables를 채워넣는다.
시나리오 1개당 LLM 호출 1번 (시나리오 단위로 컨텍스트가 작아 정확도가 높음).

처리 흐름:
1. State.planned_scenarios 순회
2. 각 시나리오에 대해 LLM 호출 → ChainerOutput 받음
3. 출력 검증 (미래 참조 금지, 알 수 없는 step_ref 금지 등)
4. 검증 통과한 매핑을 해당 step의 chained_variables에 주입
5. 완성된 시나리오를 final_scenarios로 내보냄

[1단계 변경]
재조립하는 ScenarioStep을 새 필드 세트(apiId/title/requestSpec/...)로 맞춤.
체이닝 검증 로직(미래 참조/중복 등)은 그대로 유지.
[2단계 변경]
스키마에서 expected_assertions가 제거됨에 따라 재조립 시 해당 필드 참조 제거.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from app.agents.scenario.state import AgentError, ScenarioAgentState
from app.llm import LLMClient
from app.llm.prompts.response_chainer import SYSTEM_PROMPT, build_user_prompt
from app.schemas import (
    APIInventory,
    ChainedVariable,
    Scenario,
    ScenarioStep,
    VariableSource,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# LLM 출력 전용 스키마
# ---------------------------------------------------------------------------
# planner 때와 같은 이유: LLM에게 우리의 풀스펙 ChainedVariable을 만들게 하면
# 토큰 낭비 + 불필요한 enum 입력 (LITERAL/GENERATED 등 LLM이 신경쓸 필요 없는 케이스 존재).
# 여기서는 PREVIOUS_STEP 기반 매핑만 LLM이 만든다.


class ChainerVariable(BaseModel):
    """LLM이 채울 단일 매핑."""

    name: str = Field(description="변수의 논리 이름 (예: auth_token, created_user_id)")
    source_step_ref: str = Field(description="값을 추출할 이전 스텝의 ref")
    source_json_path: str = Field(description="응답에서 값을 뽑을 JSONPath (예: $.data.accessToken)")
    target_location: str = Field(description="header, path, query, body 중 하나")
    target_field: str = Field(description="주입할 필드명. body면 JSONPath")
    target_template: str | None = Field(
        default=None,
        description="값 포맷 템플릿. {value} 자리표시자 사용. 예: 'Bearer {value}'",
    )


class ChainerStepMapping(BaseModel):
    """한 스텝의 chained_variables."""

    step_ref: str = Field(description="대상 스텝의 ref")
    variables: list[ChainerVariable] = Field(default_factory=list)


class ChainerOutput(BaseModel):
    """LLM이 emit_chained_variables 도구로 반환할 페이로드."""

    step_mappings: list[ChainerStepMapping]


# 허용된 target_location 값
_ALLOWED_LOCATIONS = {"header", "path", "query", "body"}


# ---------------------------------------------------------------------------
# 노드 팩토리
# ---------------------------------------------------------------------------


def make_chainer_node(llm: LLMClient):
    """LLMClient를 캡처한 chainer 노드 함수를 반환."""

    def chainer_node(state: ScenarioAgentState) -> dict:
        planned = state.get("planned_scenarios", [])

        if not planned:
            # planner가 시나리오를 못 만들었으면 그대로 통과
            return {"final_scenarios": []}

        inventory = state["request"].api_inventory

        final_scenarios: list[Scenario] = []
        all_errors: list[AgentError] = []
        all_usages = []

        for scenario in planned:
            updated, errs, usage = _chain_one_scenario(scenario, inventory, llm)
            final_scenarios.append(updated)
            all_errors.extend(errs)
            if usage is not None:
                all_usages.append(usage)

        return {
            "final_scenarios": final_scenarios,
            "errors": all_errors,
            "token_usages": all_usages,
        }

    return chainer_node


# ---------------------------------------------------------------------------
# 시나리오 1개 처리
# ---------------------------------------------------------------------------


def _chain_one_scenario(
    scenario: Scenario,
    inventory: APIInventory,
    llm: LLMClient,
) -> tuple[Scenario, list[AgentError], Any]:
    """시나리오 1개의 chained_variables를 채워 새 Scenario 객체를 반환.

    실패 시에도 원본 시나리오를 그대로 반환 (chained_variables 빈 상태).
    """
    user_prompt = build_user_prompt(scenario=scenario, inventory=inventory)

    try:
        raw_output, usage = llm.generate_structured(
            system=SYSTEM_PROMPT,
            user=user_prompt,
            output_schema=ChainerOutput.model_json_schema(),
            output_name="emit_chained_variables",
            output_description="시나리오의 각 스텝에 대한 chained_variables 매핑",
            max_tokens=3000,
            temperature=0.0,  # chaining은 결정론적이어야 하므로 0
        )
    except Exception as e:
        logger.exception("chainer LLM call failed for scenario %s", scenario.name)
        return scenario, [AgentError(
            node="chainer",
            code="LLM_CALL_FAILED",
            message=f"시나리오 '{scenario.name}': {e}",
        )], None

    try:
        parsed = ChainerOutput.model_validate(raw_output)
    except ValidationError as e:
        logger.error("chainer output validation failed: %s", e)
        return scenario, [AgentError(
            node="chainer",
            code="OUTPUT_VALIDATION_FAILED",
            message=f"시나리오 '{scenario.name}': {e}",
        )], usage

    # ref → order 매핑 (미래 참조 검증용)
    ref_to_order = {s.ref: s.order for s in scenario.steps}
    valid_refs = set(ref_to_order.keys())

    # step_ref → 검증 통과한 ChainedVariable 리스트
    mappings_by_ref: dict[str, list[ChainedVariable]] = {ref: [] for ref in valid_refs}
    errors: list[AgentError] = []

    for sm in parsed.step_mappings:
        # 대상 step_ref가 시나리오 안에 있는가
        if sm.step_ref not in valid_refs:
            errors.append(AgentError(
                node="chainer",
                code="UNKNOWN_TARGET_STEP_REF",
                message=f"시나리오 '{scenario.name}': 알 수 없는 step_ref '{sm.step_ref}'",
            ))
            continue

        target_order = ref_to_order[sm.step_ref]
        used_names: set[str] = set()

        for v in sm.variables:
            # 미래 참조 검사
            if v.source_step_ref not in valid_refs:
                errors.append(AgentError(
                    node="chainer",
                    code="UNKNOWN_SOURCE_STEP_REF",
                    message=(
                        f"시나리오 '{scenario.name}' step '{sm.step_ref}': "
                        f"알 수 없는 source_step_ref '{v.source_step_ref}'"
                    ),
                ))
                continue
            source_order = ref_to_order[v.source_step_ref]
            if source_order >= target_order:
                errors.append(AgentError(
                    node="chainer",
                    code="FUTURE_REFERENCE",
                    message=(
                        f"시나리오 '{scenario.name}' step '{sm.step_ref}': "
                        f"source '{v.source_step_ref}'(order={source_order})는 "
                        f"target(order={target_order})보다 앞서야 함"
                    ),
                ))
                continue

            # target_location 검증
            loc = v.target_location.lower()
            if loc not in _ALLOWED_LOCATIONS:
                errors.append(AgentError(
                    node="chainer",
                    code="INVALID_TARGET_LOCATION",
                    message=(
                        f"시나리오 '{scenario.name}' step '{sm.step_ref}': "
                        f"잘못된 target_location '{v.target_location}'"
                    ),
                ))
                continue

            # 이름 중복 검사 (같은 step 안에서)
            if v.name in used_names:
                errors.append(AgentError(
                    node="chainer",
                    code="DUPLICATE_VARIABLE_NAME",
                    message=(
                        f"시나리오 '{scenario.name}' step '{sm.step_ref}': "
                        f"변수 이름 중복 '{v.name}'"
                    ),
                ))
                continue
            used_names.add(v.name)

            # 검증 통과 → ChainedVariable 객체로 변환
            mappings_by_ref[sm.step_ref].append(ChainedVariable(
                name=v.name,
                source=VariableSource.PREVIOUS_STEP,
                source_step_ref=v.source_step_ref,
                source_json_path=v.source_json_path,
                target_location=loc,
                target_field=v.target_field,
                target_template=v.target_template,
            ))

    # 원본 시나리오를 복사하면서 각 step에 매핑 주입 (새 ScenarioStep 필드 세트)
    new_steps = [
        ScenarioStep(
            step_id=step.step_id,
            ref=step.ref,
            order=step.order,
            chained_variables=mappings_by_ref.get(step.ref, []),
            apiId=step.apiId,
            title=step.title,
            description=step.description,
            type=step.type,
            test_case_type=step.test_case_type,
            userRole=step.userRole,
            stateCondition=step.stateCondition,
            dataVariant=step.dataVariant,
            requestSpec=step.requestSpec,
            expectedSpec=step.expectedSpec,
            assertionSpec=step.assertionSpec,
            duplicate=step.duplicate,
        )
        for step in scenario.steps
    ]
    updated = Scenario(
        scenario_id=scenario.scenario_id,
        name=scenario.name,
        description=scenario.description,
        steps=new_steps,
        meta=scenario.meta,
    )

    return updated, errors, usage