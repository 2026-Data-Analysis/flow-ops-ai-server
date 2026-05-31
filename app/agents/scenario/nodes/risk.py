"""위험레벨(risk) 노드.

생성·체이닝·dedup·validator까지 끝난 final_scenarios의 각 시나리오에 대해
'시나리오 단위' 위험도(meta.estimated_risk)를 산정해 채운다.

설계:
- 결정론적(규칙 기반). LLM 호출 없음 → 빠르고, 재현 가능하고, 유닛 테스트로 못 박힘.
- 산정 기준 자체는 app/core/risk.assess_risk에 공용으로 두고(시나리오/테스트 공용),
  이 노드는 ScenarioStep 구조에서 위험 신호(RiskSignals)를 추출하는 일만 한다.
- 위험도는 '시나리오 단위'(ScenarioMeta.estimated_risk). step 단위 아님.

위험 신호 추출:
- mutating:      step의 requestSpec.method 또는 inventory의 endpoint.method가 변경계열(POST/PUT/PATCH/DELETE)
- destructive:   위 중 DELETE
- auth_protected: 사용한 endpoint의 auth.type이 none이 아님(bearer/api_key/session)
- probes_auth:   AUTHORIZATION 타입 step 존재 (인증 우회 탐침)
- negative_count: 음성 타입(VALIDATION/EDGE_CASE/FAILURE_HANDLING/AUTHORIZATION) step 수
- chain_depth:   chained_variables를 가진 step 수
- step_count:    총 step 수
"""

from __future__ import annotations

from app.agents.scenario.state import ScenarioAgentState
from app.core.risk import RiskSignals, assess_risk
from app.schemas import APIEndpoint, DraftType, Scenario

# 변경(write) 계열 메서드
_MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

# 음성 테스트 타입 (스키마를 일부러 위반하거나 실패를 노리는 step)
_NEGATIVE_TYPES = {
    DraftType.VALIDATION,
    DraftType.EDGE_CASE,
    DraftType.FAILURE_HANDLING,
    DraftType.AUTHORIZATION,
}


def risk_node(state: ScenarioAgentState) -> dict:
    scenarios = state.get("final_scenarios", [])
    if not scenarios:
        return {}

    by_id = state["request"].api_inventory.by_id()

    updated: list[Scenario] = []
    for sc in scenarios:
        signals = _signals_for(sc, by_id)
        level = assess_risk(signals)
        # 비파괴적으로 meta만 갱신해 새 Scenario 반환
        new_meta = sc.meta.model_copy(update={"estimated_risk": level})
        updated.append(sc.model_copy(update={"meta": new_meta}))

    return {"final_scenarios": updated}


# ---------------------------------------------------------------------------
# 내부 헬퍼
# ---------------------------------------------------------------------------


def _signals_for(scenario: Scenario, by_id: dict[str, APIEndpoint]) -> RiskSignals:
    mutating = False
    destructive = False
    auth_protected = False
    probes_auth = False
    negative_count = 0
    chain_depth = 0

    for st in scenario.steps:
        method = _method_of(st, by_id)
        if method in _MUTATING_METHODS:
            mutating = True
        if method == "DELETE":
            destructive = True

        if _is_auth_protected(st, by_id):
            auth_protected = True

        if st.type == DraftType.AUTHORIZATION:
            probes_auth = True
        if st.type in _NEGATIVE_TYPES:
            negative_count += 1

        if st.chained_variables:
            chain_depth += 1

    return RiskSignals(
        mutating=mutating,
        destructive=destructive,
        auth_protected=auth_protected,
        probes_auth=probes_auth,
        negative_count=negative_count,
        chain_depth=chain_depth,
        step_count=len(scenario.steps),
    )


def _method_of(step, by_id: dict[str, APIEndpoint]) -> str:
    """step의 HTTP 메서드를 대문자 문자열로. requestSpec 우선, 없으면 inventory."""
    rs = step.requestSpec or {}
    method = rs.get("method")
    if not method:
        ep = by_id.get(step.apiId)
        method = ep.method.value if ep is not None else ""
    return str(method).upper()


def _is_auth_protected(step, by_id: dict[str, APIEndpoint]) -> bool:
    """사용한 endpoint가 인증 보호 대상인지 (auth.type이 none이 아님)."""
    ep = by_id.get(step.apiId)
    if ep is None or ep.auth is None:
        return False
    auth_type = getattr(ep.auth, "type", None)
    # AuthScheme.type이 enum이면 .value, 문자열이면 그대로
    auth_type = getattr(auth_type, "value", auth_type)
    return bool(auth_type) and str(auth_type).lower() != "none"