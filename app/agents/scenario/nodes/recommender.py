"""시나리오 추천기(recommender) 노드.

추천 모드에서 api_inventory + existing_test_cases를 보고
'아직 검증되지 않은/부족한' 시나리오 갭(CoverageGap)을 규칙 기반으로 도출한다.
도출된 갭은 planner의 입력(user_intent)으로 흘러간다.

설계 (validator/risk/dedup과 동일 기조):
- LLM 미사용. 결정론적·재현 가능·유닛 테스트 가능.
- 갭은 planner가 흐름을 설계할 수 있게 '자연어 흐름 묘사'로 만든다.
- 214개처럼 큰 인벤토리에서도 갭을 request.max_scenarios개로 제한해
  planner 입력(=토큰)과 결과 폭주를 막는다.

갭 도출 규칙 (우선순위 순, 위가 먼저 채워짐):
1. 미커버 도메인 : 기존 테스트가 전혀 없는 endpoint를 태그(도메인)로 묶어 정상 흐름 제안.
2. 음성 미커버   : 정상(HAPPY_PATH)만 있고 음성(VALIDATION/EDGE_CASE/...)이 없는 endpoint.
3. 인증 미검증   : auth 필요 endpoint인데 AUTHORIZATION 테스트가 없음.

NOTE: 갭 비교/매칭의 기준은 endpoint_id다. existing_test_cases의 endpoint_id가
      inventory의 endpoint_id(문자열)와 같은 식별자여야 커버리지가 잡힌다.
      (백엔드가 숫자 DB id로 보내면 전부 '미커버'로 잡혀 1번 규칙만 동작 — 그래도 결과는 나온다)
"""

from __future__ import annotations

from collections import defaultdict

from app.agents.scenario.state import CoverageGap, ScenarioAgentState
from app.schemas import APIEndpoint, DraftType

# 음성 테스트 타입 값 (정상 흐름 외)
_NEGATIVE_TYPE_VALUES = {
    DraftType.VALIDATION.value,
    DraftType.EDGE_CASE.value,
    DraftType.FAILURE_HANDLING.value,
    DraftType.AUTHORIZATION.value,
}
_HAPPY = DraftType.HAPPY_PATH.value
_AUTHZ = DraftType.AUTHORIZATION.value

# 흐름 묘사에 나열할 endpoint 최대 수 (planner 입력 토큰 억제용)
_MAX_FLOW_ENDPOINTS = 6
# 경로에서 리소스명 추출 시 건너뛸 공통 접두사
_PATH_SKIP = {"api", "v1", "v2", "v3", "rest"}


def recommender_node(state: ScenarioAgentState) -> dict:
    request = state["request"]
    endpoints = request.api_inventory.endpoints
    if not endpoints:
        return {"coverage_gaps": []}

    max_gaps = max(1, request.max_scenarios)

    # endpoint_id -> 커버된 test type 값 집합
    covered: dict[str, set[str]] = defaultdict(set)
    for tc in request.existing_test_cases:
        covered[tc.endpoint_id].add(_type_value(tc.type))

    gaps: list[CoverageGap] = []
    gaps.extend(_uncovered_domain_gaps(endpoints, covered))
    gaps.extend(_missing_negative_gaps(endpoints, covered))
    gaps.extend(_missing_auth_gaps(endpoints, covered))

    return {"coverage_gaps": gaps[:max_gaps]}


# ---------------------------------------------------------------------------
# 규칙별 갭 도출
# ---------------------------------------------------------------------------


def _uncovered_domain_gaps(
    endpoints: list[APIEndpoint],
    covered: dict[str, set[str]],
) -> list[CoverageGap]:
    """기존 테스트가 전혀 없는 endpoint를 도메인(태그/리소스)으로 묶어 정상 흐름 제안.

    큰 도메인부터 우선(가장 임팩트 큰 갭이 max_gaps 상한에 먼저 살아남도록).
    """
    uncovered = [ep for ep in endpoints if not covered.get(ep.endpoint_id)]
    if not uncovered:
        return []

    gaps: list[CoverageGap] = []
    for domain, eps in _group_by_domain(uncovered):
        sample = eps[:_MAX_FLOW_ENDPOINTS]
        flow = " → ".join(_describe(ep) for ep in sample)
        gaps.append(CoverageGap(
            description=f"'{domain}' 도메인에 대한 테스트가 전혀 없음",
            suggested_flow=(
                f"'{domain}' 도메인의 핵심 사용자 흐름을 정상 경로로 검증하는 시나리오. "
                f"관련 endpoint: {flow}"
            ),
            related_endpoint_ids=[ep.endpoint_id for ep in sample],
        ))
    return gaps


def _missing_negative_gaps(
    endpoints: list[APIEndpoint],
    covered: dict[str, set[str]],
) -> list[CoverageGap]:
    """정상(HAPPY_PATH)만 있고 음성 케이스가 하나도 없는 endpoint."""
    targets = [
        ep for ep in endpoints
        if (types := covered.get(ep.endpoint_id))
        and _HAPPY in types
        and not (types & _NEGATIVE_TYPE_VALUES)
    ]
    if not targets:
        return []

    sample = targets[:_MAX_FLOW_ENDPOINTS]
    flow = ", ".join(_describe(ep) for ep in sample)
    return [CoverageGap(
        description="정상 케이스만 있고 음성(검증/경계/실패) 케이스가 없는 endpoint들",
        suggested_flow=(
            "다음 endpoint들에 대해 잘못된 입력·누락 필드·경계값으로 4xx를 유도하는 "
            f"음성 흐름을 추가: {flow}"
        ),
        related_endpoint_ids=[ep.endpoint_id for ep in sample],
    )]


def _missing_auth_gaps(
    endpoints: list[APIEndpoint],
    covered: dict[str, set[str]],
) -> list[CoverageGap]:
    """인증 필요 endpoint인데 AUTHORIZATION 테스트가 없는 경우."""
    targets = [
        ep for ep in endpoints
        if _is_auth_required(ep) and _AUTHZ not in covered.get(ep.endpoint_id, set())
    ]
    if not targets:
        return []

    sample = targets[:_MAX_FLOW_ENDPOINTS]
    flow = ", ".join(_describe(ep) for ep in sample)
    return [CoverageGap(
        description="인증이 필요한데 인증 실패(토큰 누락·만료) 검증이 없는 endpoint들",
        suggested_flow=(
            "토큰 없이 또는 만료/잘못된 토큰으로 접근해 401을 확인하는 인증 흐름을 추가: "
            f"{flow}"
        ),
        related_endpoint_ids=[ep.endpoint_id for ep in sample],
    )]


# ---------------------------------------------------------------------------
# 내부 헬퍼
# ---------------------------------------------------------------------------


def _group_by_domain(
    endpoints: list[APIEndpoint],
) -> list[tuple[str, list[APIEndpoint]]]:
    """endpoint를 도메인으로 묶어 (도메인, endpoints)를 큰 그룹 우선으로 반환.

    도메인 = 첫 태그가 있으면 그 태그, 없으면 경로의 첫 리소스 세그먼트.
    """
    groups: dict[str, list[APIEndpoint]] = defaultdict(list)
    for ep in endpoints:
        domain = ep.tags[0] if ep.tags else _resource_of(ep.path)
        groups[domain].append(ep)
    return sorted(groups.items(), key=lambda kv: len(kv[1]), reverse=True)


def _resource_of(path: str) -> str:
    """경로에서 리소스명 추출. 예: /api/v1/users/{userId} -> 'users'."""
    parts = [p for p in path.strip("/").split("/") if p and not p.startswith("{")]
    for p in parts:
        if p.lower() not in _PATH_SKIP:
            return p
    return parts[0] if parts else "general"


def _describe(ep: APIEndpoint) -> str:
    """흐름 묘사용 한 줄. 예: 'POST /api/v1/users (회원 생성)'."""
    base = f"{ep.method.value} {ep.path}"
    return f"{base} ({ep.summary})" if ep.summary else base


def _is_auth_required(ep: APIEndpoint) -> bool:
    """auth.type이 none이 아니면 인증 필요 (risk._is_auth_protected와 동일 판정)."""
    if ep.auth is None:
        return False
    auth_type = getattr(ep.auth, "type", None)
    auth_type = getattr(auth_type, "value", auth_type)
    return bool(auth_type) and str(auth_type).lower() != "none"


def _type_value(t) -> str:
    """TestCase.type이 enum이면 .value, 문자열이면 그대로."""
    return getattr(t, "value", t)