"""Validator 노드.

생성·체이닝까지 끝난 final_scenarios의 스키마 정합성을 검증한다.

검증은 '비파괴적'이다 — 문제를 errors에 기록만 하고 시나리오를 제거하지 않는다.
(엔드포인트 핸들러가 errors를 '부분 검증 실패'로 요약해 응답 error_message에 첨부.
 시나리오가 1개라도 있으면 success=true 유지.)

검사 항목:
1. apiId가 inventory에 존재하는가 (안전망; planner가 이미 1차로 거름).
2. requestSpec.body가 request_body_schema에 부합하는가 — **정상 흐름 step만**.
   - HAPPY_PATH / PERFORMANCE 처럼 '유효한 요청'을 보내는 step에만 적용.
   - VALIDATION / EDGE_CASE / FAILURE_HANDLING / AUTHORIZATION 같은 음성 테스트는
     일부러 스키마를 위반(필드 누락/잘못된 값)하는 것이 목적이므로 검사하지 않음.
   - required 필드 충족 — chained_variables로 body에 주입되는 필드도 '충족'으로 인정.
   - 스키마 properties에 없는 필드(unknown)가 정적 body에 있는가.
3. chained_variables 경로 검증 — **모든 step**.
   - body target 필드가 request_body_schema에 존재하는가.
   - source_json_path 최상위가 source 스텝의 response_schema에 존재하는가
     (response_schema가 있을 때만).
"""

from __future__ import annotations

from app.agents.scenario.state import AgentError, ScenarioAgentState
from app.schemas import APIEndpoint, DraftType, Scenario, ScenarioStep

# 유효한 요청을 보내는(=스키마를 지켜야 하는) step 타입.
# 그 외(VALIDATION/EDGE_CASE/FAILURE_HANDLING/AUTHORIZATION)는 일부러 위반하므로 정합성 검사 제외.
_POSITIVE_TYPES = {DraftType.HAPPY_PATH, DraftType.PERFORMANCE}


def validator_node(state: ScenarioAgentState) -> dict:
    scenarios = state.get("final_scenarios", [])
    if not scenarios:
        return {}

    by_id = state["request"].api_inventory.by_id()

    errors: list[AgentError] = []
    for sc in scenarios:
        ref_to_step = {st.ref: st for st in sc.steps}
        for st in sc.steps:
            errors.extend(_validate_step(sc, st, by_id, ref_to_step))

    return {"errors": errors} if errors else {}


# ---------------------------------------------------------------------------
# 내부 헬퍼
# ---------------------------------------------------------------------------


def _validate_step(
    scenario: Scenario,
    step: ScenarioStep,
    by_id: dict[str, APIEndpoint],
    ref_to_step: dict[str, ScenarioStep],
) -> list[AgentError]:
    ep = by_id.get(step.apiId)
    if ep is None:
        return [AgentError(
            node="validator",
            code="UNKNOWN_APIID",
            message=f"시나리오 '{scenario.name}' step '{step.ref}': inventory에 없는 apiId '{step.apiId}'",
        )]

    errors: list[AgentError] = []

    # body 정합성은 '정상 요청' step에만 (음성 테스트는 일부러 위반하므로 제외)
    if step.type in _POSITIVE_TYPES:
        errors.extend(_validate_body_conformance(scenario, step, ep))

    # 체이닝 경로 정합성은 타입과 무관하게 항상
    errors.extend(_validate_chaining(scenario, step, ep, by_id, ref_to_step))
    return errors


def _validate_body_conformance(
    scenario: Scenario,
    step: ScenarioStep,
    ep: APIEndpoint,
) -> list[AgentError]:
    schema = ep.request_body_schema
    if not isinstance(schema, dict) or schema.get("type") != "object":
        return []  # 검증할 object 스키마가 없음

    props = schema.get("properties") or {}
    required = schema.get("required") or []

    static_body = (step.requestSpec or {}).get("body")
    static_keys = set(static_body.keys()) if isinstance(static_body, dict) else set()
    chained_body_fields = _chained_body_fields(step)
    present = static_keys | chained_body_fields

    errors: list[AgentError] = []

    # required 충족 (체이닝으로 채워지는 필드도 충족으로 인정 — 핵심)
    missing = [r for r in required if r not in present]
    if missing:
        errors.append(AgentError(
            node="validator",
            code="PAYLOAD_MISSING_REQUIRED",
            message=f"시나리오 '{scenario.name}' step '{step.ref}': 필수 필드 누락 {missing} (apiId={step.apiId})",
        ))

    # 스키마에 없는 필드 (정적 body 기준)
    if props:
        unknown = sorted(k for k in static_keys if k not in props)
        if unknown:
            errors.append(AgentError(
                node="validator",
                code="PAYLOAD_UNKNOWN_FIELD",
                message=f"시나리오 '{scenario.name}' step '{step.ref}': 스키마에 없는 필드 {unknown} (apiId={step.apiId})",
            ))

    return errors


def _validate_chaining(
    scenario: Scenario,
    step: ScenarioStep,
    ep: APIEndpoint,
    by_id: dict[str, APIEndpoint],
    ref_to_step: dict[str, ScenarioStep],
) -> list[AgentError]:
    errors: list[AgentError] = []

    schema = ep.request_body_schema
    props = schema.get("properties") if isinstance(schema, dict) else None

    for cv in step.chained_variables:
        # body target이 request_body_schema에 존재하는가 (스키마 있을 때만)
        if props and cv.target_location == "body" and cv.target_field:
            top = _top_level_field(cv.target_field)
            if top and top not in props:
                errors.append(AgentError(
                    node="validator",
                    code="INVALID_TARGET_PATH",
                    message=(
                        f"시나리오 '{scenario.name}' step '{step.ref}': "
                        f"체이닝 target '{cv.target_field}'가 스키마에 없음 (apiId={step.apiId})"
                    ),
                ))

        # source_json_path가 source 스텝 응답 스키마에 존재하는가
        if cv.source_step_ref and cv.source_json_path:
            src_step = ref_to_step.get(cv.source_step_ref)
            if src_step is None:
                continue  # chainer가 이미 검증
            src_ep = by_id.get(src_step.apiId)
            if src_ep is None or not isinstance(src_ep.response_schema, dict):
                continue  # 응답 스키마 없으면 검증 불가 → skip
            resp_props = src_ep.response_schema.get("properties") or {}
            if not resp_props:
                continue
            top = _top_level_field(cv.source_json_path)
            if top and top not in resp_props:
                errors.append(AgentError(
                    node="validator",
                    code="INVALID_SOURCE_PATH",
                    message=(
                        f"시나리오 '{scenario.name}' step '{step.ref}': "
                        f"source_json_path '{cv.source_json_path}'가 "
                        f"'{cv.source_step_ref}'({src_step.apiId}) 응답 스키마에 없음"
                    ),
                ))

    return errors


def _chained_body_fields(step: ScenarioStep) -> set[str]:
    """chained_variables 중 body에 주입되는 최상위 필드 집합."""
    return {
        _top_level_field(cv.target_field)
        for cv in step.chained_variables
        if cv.target_location == "body" and cv.target_field
    }


def _top_level_field(path: str) -> str:
    """JSONPath에서 최상위 필드명만 추출.

    예: '$.userId' -> 'userId', '$.items[0].productId' -> 'items', 'userId' -> 'userId'
    """
    p = path.lstrip("$").lstrip(".")
    for i, ch in enumerate(p):
        if ch in ".[":
            return p[:i]
    return p