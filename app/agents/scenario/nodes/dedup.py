"""Dedup 노드.

역할:
- chainer까지 완성된 final_scenarios의 각 step을, 요청에 포함된 기존 테스트
  (request.existing_test_cases)와 비교한다.
- 같은 테스트로 판단되면 step.duplicate = True 로 표시한다.
  (백엔드는 duplicate=True인 step에 대해 새 테스트케이스를 만들지 않고 기존 것을 재사용)

설계 결정:
1. 공용 fingerprint(app.core.fingerprint.make_fingerprint)로 testcase와 동일 기준 사용.
2. 기존 테스트는 백엔드 표준 모델인 ExistingTestCase(type=DraftType, camelCase)로 받는다.
   - testcase 에이전트가 받는 existingTestCases와 동일 모델이라 두 에이전트가 정렬됨.
   - 지문 축은 DraftType. 시나리오 step도 st.type(DraftType)으로 같은 축을 쓴다.
   - body는 requestSpec['body']에서 꺼낸다(requestSpec는 {method,path,body,...} 래퍼).
3. 시나리오 step의 'body 필드'는 정적 requestSpec.body 필드 + chained_variables로
   body에 주입되는 필드를 합쳐서 계산한다.
   (userId 등 동적 값은 정적 body엔 없고 체이닝으로 들어오므로, 합치지 않으면
    전체 body를 가진 기존 테스트와 매칭되지 않음)
4. 중복은 '플래그만' 세팅하고 step을 제거하지 않는다. 시나리오 실행 시 그 step은
   여전히 호출되어야 하기 때문. duplicate는 '새 테스트케이스 생성 여부' 신호일 뿐.
5. 같은 응답 배치 안에서 동일 step이 또 나오면(예: 여러 시나리오의 로그인) 두 번째부터
   duplicate=True (기존 seen에 누적). 시나리오 단위로 리셋하고 싶으면 _dedup_scenarios
   안에서 seen 초기화 위치만 바꾸면 됨.
"""

from __future__ import annotations

from app.agents.scenario.state import ScenarioAgentState
from app.core.fingerprint import make_fingerprint
from app.schemas import Scenario, ScenarioStep
from app.schemas.testcase import ExistingTestCase


def dedup_node(state: ScenarioAgentState) -> dict:
    scenarios = state.get("final_scenarios", [])
    if not scenarios:
        return {}

    existing = state["request"].existing_test_cases
    seen = _existing_fingerprints(existing)

    updated = _dedup_scenarios(scenarios, seen)
    return {"final_scenarios": updated}


# ---------------------------------------------------------------------------
# 내부 헬퍼
# ---------------------------------------------------------------------------


def _existing_fingerprints(existing: list[ExistingTestCase]) -> set[frozenset]:
    """기존 테스트케이스들의 지문 집합.

    ExistingTestCase는 type=DraftType, requestSpec={method,path,body,...} 형태다.
    body는 requestSpec['body']에서 꺼낸다(requestSpec 자체가 body가 아님).
    """
    fps: set[frozenset] = set()
    for tc in existing:
        body = (tc.requestSpec or {}).get("body")
        body = body if isinstance(body, dict) else {}
        fps.add(make_fingerprint(
            api_id=tc.apiId,
            test_case_type=tc.type.value,
            body_fields=body.keys(),
        ))
    return fps


def _dedup_scenarios(
    scenarios: list[Scenario],
    seen: set[frozenset],
) -> list[Scenario]:
    """각 step에 duplicate 플래그를 세팅한 새 시나리오 리스트 반환."""
    updated_scenarios: list[Scenario] = []

    for sc in scenarios:
        new_steps: list[ScenarioStep] = []
        for st in sc.steps:
            fp = make_fingerprint(
                api_id=st.apiId,
                test_case_type=st.type.value,
                body_fields=_step_body_fields(st),
            )
            is_dup = fp in seen
            if not is_dup:
                seen.add(fp)
            new_steps.append(st.model_copy(update={"duplicate": is_dup}))
        updated_scenarios.append(sc.model_copy(update={"steps": new_steps}))

    return updated_scenarios


def _step_body_fields(step: ScenarioStep) -> set[str]:
    """step이 실제로 보낼 body의 최상위 필드 집합.

    정적 requestSpec.body 필드 + chained_variables로 body에 주입되는 필드.
    """
    fields: set[str] = set()

    body = (step.requestSpec or {}).get("body")
    if isinstance(body, dict):
        fields.update(body.keys())

    for cv in step.chained_variables:
        if cv.target_location == "body" and cv.target_field:
            fields.add(_top_level_field(cv.target_field))

    return fields


def _top_level_field(path: str) -> str:
    """target_field(JSONPath)에서 최상위 필드명만 추출.

    예: '$.userId' -> 'userId', '$.items[0].productId' -> 'items', 'userId' -> 'userId'
    """
    p = path.lstrip("$").lstrip(".")
    for i, ch in enumerate(p):
        if ch in ".[":
            return p[:i]
    return p