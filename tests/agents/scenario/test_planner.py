"""planner 노드 테스트.

스키마 리팩터(endpoint_id→apiId, name→title, type/requestSpec 등) 이후
- 새 필드로 올바르게 조립되는지
- type → test_case_type 매핑이 채워지는지
- 기존 검증(미존재 endpoint / ref 중복 / order 불연속 / user_intent 누락)이 유지되는지
를 확인한다."""

from __future__ import annotations

from app.agents.scenario.nodes.planner import make_planner_node
from app.agents.scenario.state import initial_state
from app.schemas import (
    DraftType,
    ScenarioGenerationMode,
    ScenarioGenerationRequest,
    TestCaseType,
)


def _ok_payload() -> dict:
    return {
        "scenarios": [
            {
                "name": "회원가입-로그인-주문 정상 흐름",
                "description": "정상 E2E",
                "rationale": "핵심 사용자 여정 검증",
                "steps": [
                    {
                        "ref": "step_1",
                        "order": 1,
                        "apiId": "POST:/api/v1/auth/signup",
                        "title": "회원가입",
                        "type": "HAPPY_PATH",
                        "requestSpec": {
                            "method": "POST",
                            "pathParams": {},
                            "queryParams": {},
                            "body": {"email": "a@b.com", "password": "pw"},
                        },
                        "expectedSpec": {"statusCode": 201, "body": {"userId": 1}, "errorMessage": None},
                        "assertionSpec": {"statusCode": 201, "bodyContains": ["userId"]},
                    },
                    {
                        "ref": "step_2",
                        "order": 2,
                        "apiId": "POST:/api/v1/auth/login",
                        "title": "로그인",
                        "type": "HAPPY_PATH",
                    },
                    {
                        "ref": "step_3",
                        "order": 3,
                        "apiId": "POST:/api/v1/orders",
                        "title": "주문",
                        "type": "HAPPY_PATH",
                    },
                ],
            }
        ]
    }


def test_planner_assembles_new_fields(request_nl, fake_llm):
    out = make_planner_node(fake_llm(_ok_payload()))(initial_state(request_nl, trace_id="t"))

    scenarios = out["planned_scenarios"]
    assert len(scenarios) == 1
    sc = scenarios[0]
    assert [s.order for s in sc.steps] == [1, 2, 3]

    s1 = sc.steps[0]
    assert s1.apiId == "POST:/api/v1/auth/signup"
    assert s1.title == "회원가입"
    assert s1.type == DraftType.HAPPY_PATH
    # type → test_case_type 매핑 (HAPPY_PATH → NORMAL)
    assert s1.test_case_type == TestCaseType.NORMAL
    # requestSpec 보존, chainer 자리(chained_variables)는 비어 있어야 함
    assert s1.requestSpec["body"]["email"] == "a@b.com"
    assert s1.chained_variables == []
    # 구 필드는 더 이상 존재하지 않음
    assert not hasattr(s1, "endpoint_id")
    assert not hasattr(s1, "static_payload")
    assert not hasattr(s1, "expected_assertions")
    assert out["errors"] == []
    # LLM 호출은 1회
    assert len(out["token_usages"]) == 1


def test_planner_missing_user_intent(inventory, fake_llm):
    req = ScenarioGenerationRequest(
        project_id="p",
        mode=ScenarioGenerationMode.NATURAL_LANGUAGE,
        user_intent=None,
        api_inventory=inventory,
    )
    client = fake_llm({"scenarios": []})
    out = make_planner_node(client)(initial_state(req, trace_id="t"))
    assert any(e["code"] == "MISSING_USER_INTENT" for e in out["errors"])
    # LLM 호출 자체가 일어나지 않아야 함
    assert client.calls == []


def test_planner_unknown_endpoint(request_nl, fake_llm):
    payload = {
        "scenarios": [
            {
                "name": "bad",
                "rationale": "r",
                "steps": [
                    {"ref": "step_1", "order": 1, "apiId": "GET:/nope", "title": "x", "type": "HAPPY_PATH"}
                ],
            }
        ]
    }
    out = make_planner_node(fake_llm(payload))(initial_state(request_nl, trace_id="t"))
    assert out["planned_scenarios"] == []
    assert any(e["code"] == "UNKNOWN_ENDPOINT_ID" for e in out["errors"])


def test_planner_invalid_order(request_nl, fake_llm):
    payload = {
        "scenarios": [
            {
                "name": "bad",
                "rationale": "r",
                "steps": [
                    {"ref": "step_1", "order": 1, "apiId": "POST:/api/v1/auth/signup", "title": "x", "type": "HAPPY_PATH"},
                    {"ref": "step_2", "order": 3, "apiId": "POST:/api/v1/auth/login", "title": "y", "type": "HAPPY_PATH"},
                ],
            }
        ]
    }
    out = make_planner_node(fake_llm(payload))(initial_state(request_nl, trace_id="t"))
    assert out["planned_scenarios"] == []
    assert any(e["code"] == "INVALID_STEP_ORDER" for e in out["errors"])


def test_planner_duplicate_ref(request_nl, fake_llm):
    payload = {
        "scenarios": [
            {
                "name": "bad",
                "rationale": "r",
                "steps": [
                    {"ref": "step_1", "order": 1, "apiId": "POST:/api/v1/auth/signup", "title": "x", "type": "HAPPY_PATH"},
                    {"ref": "step_1", "order": 2, "apiId": "POST:/api/v1/auth/login", "title": "y", "type": "HAPPY_PATH"},
                ],
            }
        ]
    }
    out = make_planner_node(fake_llm(payload))(initial_state(request_nl, trace_id="t"))
    assert out["planned_scenarios"] == []
    assert any(e["code"] == "DUPLICATE_STEP_REF" for e in out["errors"])