"""validator_node 유닛 테스트.

LLM을 거치지 않고 손으로 만든 시나리오를 validator에 직접 넣어
다음 동작을 결정론적으로 검증한다:

1. HAPPY_PATH step이 required 필드를 누락하면 PAYLOAD_MISSING_REQUIRED.
2. 같은 누락이라도 VALIDATION(음성 테스트) step이면 검사 제외 (오탐 방지).
3. required 필드가 chained_variables로 채워지면 누락으로 보지 않음.
4. 정상 흐름은 에러 0건.

실행: pytest app/tests/agents/scenario/test_validator.py
"""

from __future__ import annotations

from app.agents.scenario.nodes.validator import validator_node
from app.schemas import (
    APIEndpoint,
    APIInventory,
    ChainedVariable,
    DraftType,
    HttpMethod,
    Scenario,
    ScenarioGenerationMode,
    ScenarioGenerationRequest,
    ScenarioMeta,
    ScenarioStep,
    VariableSource,
)

# ---------------------------------------------------------------------------
# 공용 픽스처성 헬퍼
# ---------------------------------------------------------------------------

_LOGIN = APIEndpoint(
    endpoint_id="POST:/api/v1/auth/login",
    path="/api/v1/auth/login",
    method=HttpMethod.POST,
    response_schema={
        "type": "object",
        "properties": {"accessToken": {"type": "string"}, "userId": {"type": "integer"}},
    },
)

_ORDERS = APIEndpoint(
    endpoint_id="POST:/api/v1/orders",
    path="/api/v1/orders",
    method=HttpMethod.POST,
    request_body_schema={
        "type": "object",
        "properties": {
            "userId": {"type": "integer"},
            "items": {"type": "array"},
            "paymentMethod": {"type": "string"},
        },
        "required": ["userId", "items", "paymentMethod"],
    },
)

_INVENTORY = APIInventory(project_id="p", endpoints=[_LOGIN, _ORDERS])


def _state(scenario: Scenario) -> dict:
    request = ScenarioGenerationRequest(
        project_id="p",
        mode=ScenarioGenerationMode.NATURAL_LANGUAGE,
        user_intent="x",
        api_inventory=_INVENTORY,
    )
    return {"final_scenarios": [scenario], "request": request}


def _order_step(*, ref: str, order: int, step_type: DraftType, body: dict, chained=None) -> ScenarioStep:
    return ScenarioStep(
        ref=ref,
        order=order,
        apiId="POST:/api/v1/orders",
        title="주문",
        type=step_type,
        requestSpec={"method": "POST", "pathParams": {}, "queryParams": {}, "body": body},
        chained_variables=chained or [],
    )


def _scenario(steps: list[ScenarioStep]) -> Scenario:
    return Scenario(name="t", steps=steps, meta=ScenarioMeta(rationale="r"))


def _codes(result: dict) -> list[str]:
    return [e["code"] for e in result.get("errors", [])]


# ---------------------------------------------------------------------------
# 테스트
# ---------------------------------------------------------------------------


def test_happy_path_missing_required_is_flagged():
    """HAPPY_PATH인데 required(items) 누락 → PAYLOAD_MISSING_REQUIRED."""
    step = _order_step(
        ref="step_1", order=1, step_type=DraftType.HAPPY_PATH,
        body={"userId": 1, "paymentMethod": "card"},  # items 누락
    )
    result = validator_node(_state(_scenario([step])))
    assert "PAYLOAD_MISSING_REQUIRED" in _codes(result)


def test_negative_type_missing_required_is_skipped():
    """같은 누락이라도 VALIDATION(음성)이면 검사 제외 → 에러 없음."""
    step = _order_step(
        ref="step_1", order=1, step_type=DraftType.VALIDATION,
        body={"paymentMethod": "card"},  # 일부러 items/userId 누락
    )
    result = validator_node(_state(_scenario([step])))
    assert "PAYLOAD_MISSING_REQUIRED" not in _codes(result)


def test_required_filled_by_chaining_is_ok():
    """required(userId)가 정적 body엔 없어도 chained_variables로 채워지면 통과."""
    login = ScenarioStep(
        ref="step_1", order=1, apiId="POST:/api/v1/auth/login", title="로그인",
        type=DraftType.HAPPY_PATH,
        requestSpec={"method": "POST", "pathParams": {}, "queryParams": {}, "body": {}},
    )
    order = _order_step(
        ref="step_2", order=2, step_type=DraftType.HAPPY_PATH,
        body={"items": [], "paymentMethod": "card"},  # userId 없음 → 체이닝으로 채움
        chained=[ChainedVariable(
            name="user_id",
            source=VariableSource.PREVIOUS_STEP,
            source_step_ref="step_1",
            source_json_path="$.userId",
            target_location="body",
            target_field="$.userId",
        )],
    )
    result = validator_node(_state(_scenario([login, order])))
    assert "PAYLOAD_MISSING_REQUIRED" not in _codes(result)


def test_unknown_source_path_is_flagged():
    """체이닝 source_json_path가 source 응답 스키마에 없으면 INVALID_SOURCE_PATH."""
    login = ScenarioStep(
        ref="step_1", order=1, apiId="POST:/api/v1/auth/login", title="로그인",
        type=DraftType.HAPPY_PATH,
        requestSpec={"method": "POST", "pathParams": {}, "queryParams": {}, "body": {}},
    )
    order = _order_step(
        ref="step_2", order=2, step_type=DraftType.HAPPY_PATH,
        body={"userId": 1, "items": [], "paymentMethod": "card"},
        chained=[ChainedVariable(
            name="nope",
            source=VariableSource.PREVIOUS_STEP,
            source_step_ref="step_1",
            source_json_path="$.doesNotExist",  # 로그인 응답에 없는 경로
            target_location="header",
            target_field="X-Nope",
        )],
    )
    result = validator_node(_state(_scenario([login, order])))
    assert "INVALID_SOURCE_PATH" in _codes(result)


def test_valid_scenario_has_no_errors():
    """모든 필드가 스키마에 맞으면 에러 0건."""
    step = _order_step(
        ref="step_1", order=1, step_type=DraftType.HAPPY_PATH,
        body={"userId": 1, "items": [], "paymentMethod": "card"},
    )
    result = validator_node(_state(_scenario([step])))
    assert result.get("errors", []) == []