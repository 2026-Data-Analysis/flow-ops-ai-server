"""chainer 노드 테스트.

핵심 회귀 방지 포인트:
- model_copy 기반 갱신이 chained_variables만 채우고 나머지 step 필드(apiId/title/type/
  requestSpec/step_id)를 그대로 보존하는지 (리팩터로 깨지기 쉬운 부분)
- 미래 참조(FUTURE_REFERENCE) 등 검증이 유지되는지
- planned_scenarios가 비면 그대로 통과하는지
"""

from __future__ import annotations

from app.agents.scenario.nodes.chainer import make_chainer_node
from app.agents.scenario.state import initial_state
from app.schemas import (
    DraftType,
    Scenario,
    ScenarioMeta,
    ScenarioStep,
    VariableSource,
)


def _planned_scenario() -> Scenario:
    """planner 출력 형태(체이닝 비어있음)의 시나리오를 직접 구성."""
    steps = [
        ScenarioStep(
            ref="step_1",
            order=1,
            apiId="POST:/api/v1/auth/login",
            title="로그인",
            type=DraftType.HAPPY_PATH,
            requestSpec={"method": "POST", "body": {"email": "a@b.com"}},
        ),
        ScenarioStep(
            ref="step_2",
            order=2,
            apiId="POST:/api/v1/orders",
            title="주문",
            type=DraftType.HAPPY_PATH,
            requestSpec={"method": "POST", "body": {"items": []}},
        ),
    ]
    return Scenario(name="로그인-주문", steps=steps, meta=ScenarioMeta(rationale="r"))


def _state_with(scenario: Scenario, request_nl):
    st = initial_state(request_nl, trace_id="t")
    st["planned_scenarios"] = [scenario]
    return st


def test_chainer_injects_and_preserves_fields(request_nl, fake_llm):
    scenario = _planned_scenario()
    original_step2_id = next(s for s in scenario.steps if s.ref == "step_2").step_id

    payload = {
        "step_mappings": [
            {"step_ref": "step_1", "variables": []},
            {
                "step_ref": "step_2",
                "variables": [
                    {
                        "name": "auth_token",
                        "source_step_ref": "step_1",
                        "source_json_path": "$.accessToken",
                        "target_location": "header",
                        "target_field": "Authorization",
                        "target_template": "Bearer {value}",
                    }
                ],
            },
        ]
    }

    out = make_chainer_node(fake_llm(payload))(_state_with(scenario, request_nl))

    finals = out["final_scenarios"]
    assert len(finals) == 1
    sc = finals[0]

    # step_2에 체이닝 주입
    s2 = next(s for s in sc.steps if s.ref == "step_2")
    assert len(s2.chained_variables) == 1
    cv = s2.chained_variables[0]
    assert cv.name == "auth_token"
    assert cv.source == VariableSource.PREVIOUS_STEP
    assert cv.target_template == "Bearer {value}"

    # ── model_copy가 나머지 필드를 보존하는지 (핵심 회귀 검사) ──
    assert s2.apiId == "POST:/api/v1/orders"
    assert s2.title == "주문"
    assert s2.type == DraftType.HAPPY_PATH
    assert s2.requestSpec == {"method": "POST", "body": {"items": []}}
    assert s2.step_id == original_step2_id  # 서버 발급 uuid 보존

    # step_1은 매핑 없음
    s1 = next(s for s in sc.steps if s.ref == "step_1")
    assert s1.chained_variables == []
    assert out["errors"] == []


def test_chainer_rejects_future_reference(request_nl, fake_llm):
    scenario = _planned_scenario()
    payload = {
        "step_mappings": [
            {
                "step_ref": "step_1",
                "variables": [
                    {
                        "name": "x",
                        "source_step_ref": "step_2",  # 자기보다 뒤 → 미래 참조
                        "source_json_path": "$.orderId",
                        "target_location": "body",
                        "target_field": "$.x",
                    }
                ],
            }
        ]
    }
    out = make_chainer_node(fake_llm(payload))(_state_with(scenario, request_nl))
    sc = out["final_scenarios"][0]
    s1 = next(s for s in sc.steps if s.ref == "step_1")
    assert s1.chained_variables == []  # 거부됨
    assert any(e["code"] == "FUTURE_REFERENCE" for e in out["errors"])


def test_chainer_passthrough_when_no_scenarios(request_nl, fake_llm):
    st = initial_state(request_nl, trace_id="t")
    st["planned_scenarios"] = []
    out = make_chainer_node(fake_llm({"step_mappings": []}))(st)
    assert out["final_scenarios"] == []