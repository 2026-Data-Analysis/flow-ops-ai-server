"""validator 노드.

planner/chainer가 만든 시나리오를 비파괴적으로 검증한다 (LLM 미사용).
시나리오를 수정하지 않고 문제를 errors에 기록만 한다 → success는 유지(부분 검증 실패).

검사 항목:
- PAYLOAD_MISSING_REQUIRED : 정상 흐름 step의 body에 required 필드 누락
                             (단, chained_variables(body)로 채워지면 충족으로 인정)
- PAYLOAD_UNKNOWN_FIELD    : request_body_schema에 없는 필드가 정적 body에 있음
- INVALID_TARGET_PATH      : 체이닝 body target 필드가 request_body_schema에 없음
- INVALID_SOURCE_PATH      : source_json_path가 source step의 response_schema에 없음

적용 범위:
- body 정합성(PAYLOAD_*, INVALID_TARGET_PATH)은 정상 흐름(HAPPY_PATH/PERFORMANCE) step에만.
  음성 테스트(VALIDATION/EDGE_CASE/FAILURE_HANDLING/AUTHORIZATION)는 일부러 스키마를 위반하는
  것이 목적이므로 제외 (오탐 방지).
- INVALID_SOURCE_PATH는 step type과 무관하게 검사 (source 응답은 항상 유효해야 하므로).
"""

from __future__ import annotations

from typing import Any

from app.agents.scenario.state import AgentError
from app.schemas import DraftType

# body 정합성 검사를 적용할(=정상 흐름) type
_POSITIVE_TYPES = {DraftType.HAPPY_PATH, DraftType.PERFORMANCE}


def validator_node(state: dict) -> dict:
    scenarios = state.get("final_scenarios", [])
    if not scenarios:
        return {"errors": []}

    inventory = state["request"].api_inventory
    by_id = inventory.by_id()
    errors: list[AgentError] = []

    for scenario in scenarios:
        ref_to_step = {s.ref: s for s in scenario.steps}

        for step in scenario.steps:
            ep = by_id.get(step.apiId)
            if ep is None:
                continue

            # body 정합성 (정상 흐름 step만)
            if step.type in _POSITIVE_TYPES:
                errors.extend(_check_body(scenario, step, ep))

            # 체이닝 source 경로 (모든 step)
            errors.extend(_check_source_paths(scenario, step, ref_to_step, by_id))

    return {"errors": errors}


# ---------------------------------------------------------------------------
# 내부 헬퍼
# ---------------------------------------------------------------------------


def _top_field(target_field: str) -> str:
    """target_field('$.userId' / 'userId' / '$.a.b')에서 최상위 필드명 추출."""
    f = target_field.strip()
    if f.startswith("$"):
        f = f[1:]
    if f.startswith("."):
        f = f[1:]
    return f.split(".")[0].split("[")[0]


def _path_exists(schema: dict[str, Any] | None, json_path: str) -> bool:
    """JSONPath가 JSON Schema(object/properties)에 존재하는지 best-effort 판정.

    스키마 정보가 없거나(검증 불가) 배열 등 복잡 구조면 오탐 방지를 위해 True를 반환하고,
    'properties가 명확히 있는데 키가 없는' 확정적 불일치만 False로 본다.
    """
    if not isinstance(schema, dict):
        return True

    path = json_path.strip()
    if path.startswith("$"):
        path = path[1:]
    if path.startswith("."):
        path = path[1:]
    if not path:
        return True

    current: Any = schema
    for seg in path.split("."):
        key = seg.split("[")[0]
        if not key:
            continue
        if not isinstance(current, dict):
            return True  # 더 내려갈 수 없음 → 검증 보류(통과)
        props = current.get("properties")
        if not isinstance(props, dict):
            return True  # properties 정보 없음 → 검증 보류(통과)
        if key not in props:
            return False  # 확정적 불일치
        current = props[key]
        # 배열이면 items로 한 단계 내려감
        if isinstance(current, dict) and current.get("type") == "array":
            items = current.get("items")
            if isinstance(items, dict):
                current = items
    return True


def _check_body(scenario, step, ep) -> list[AgentError]:
    out: list[AgentError] = []
    schema = ep.request_body_schema
    if not isinstance(schema, dict):
        return out

    props = schema.get("properties") or {}
    required = schema.get("required") or []
    body = (step.requestSpec or {}).get("body") or {}

    # 정적 body + body로 주입되는 체이닝 필드 = '제공된' 필드
    provided = set(body.keys())
    for cv in step.chained_variables:
        if cv.target_location == "body":
            provided.add(_top_field(cv.target_field))

    # PAYLOAD_MISSING_REQUIRED
    missing = [r for r in required if r not in provided]
    if missing:
        out.append(AgentError(
            node="validator",
            code="PAYLOAD_MISSING_REQUIRED",
            message=f"시나리오 '{scenario.name}' step '{step.ref}': required 누락 {missing}",
        ))

    if props:
        # PAYLOAD_UNKNOWN_FIELD
        unknown = [k for k in body.keys() if k not in props]
        if unknown:
            out.append(AgentError(
                node="validator",
                code="PAYLOAD_UNKNOWN_FIELD",
                message=f"시나리오 '{scenario.name}' step '{step.ref}': 스키마에 없는 필드 {unknown}",
            ))

        # INVALID_TARGET_PATH (body로 주입되는 체이닝의 대상 필드)
        for cv in step.chained_variables:
            if cv.target_location == "body" and _top_field(cv.target_field) not in props:
                out.append(AgentError(
                    node="validator",
                    code="INVALID_TARGET_PATH",
                    message=(
                        f"시나리오 '{scenario.name}' step '{step.ref}': "
                        f"체이닝 target '{cv.target_field}'가 request_body_schema에 없음"
                    ),
                ))

    return out


def _check_source_paths(scenario, step, ref_to_step, by_id) -> list[AgentError]:
    out: list[AgentError] = []
    for cv in step.chained_variables:
        if not cv.source_json_path or not cv.source_step_ref:
            continue
        source_step = ref_to_step.get(cv.source_step_ref)
        if source_step is None:
            continue  # 알 수 없는 ref는 chainer가 이미 처리
        source_ep = by_id.get(source_step.apiId)
        if source_ep is None:
            continue
        if not _path_exists(source_ep.response_schema, cv.source_json_path):
            out.append(AgentError(
                node="validator",
                code="INVALID_SOURCE_PATH",
                message=(
                    f"시나리오 '{scenario.name}' step '{step.ref}': "
                    f"source_json_path '{cv.source_json_path}'가 "
                    f"'{cv.source_step_ref}' 응답 스키마에 없음"
                ),
            ))
    return out