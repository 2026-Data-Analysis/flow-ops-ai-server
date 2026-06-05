"""시나리오 Agent 노드 테스트 공통 픽스처.

실제 Claude 호출 없이 노드 로직만 검증하기 위한 FakeLLMClient와
샘플 인벤토리/요청을 제공한다.

배치 위치: tests/agents/scenario/conftest.py
(이미 tests/conftest.py가 있으면 fixture만 그쪽으로 합쳐도 됨)
"""

from __future__ import annotations

from typing import Any

import pytest

from app.schemas import (
    APIEndpoint,
    APIInventory,
    AuthScheme,
    ScenarioGenerationMode,
    ScenarioGenerationRequest,
    TokenUsage,
)


class FakeLLMClient:
    """generate_structured 호출 시 미리 정해둔 payload를 그대로 돌려주는 가짜 클라이언트.

    app.llm.LLMClient Protocol을 덕타이핑으로 만족한다.
    네트워크/키 없이 노드의 파싱·검증·조립 로직만 검증할 수 있다.
    """

    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload
        self.calls: list[dict[str, Any]] = []

    def generate_structured(
        self,
        *,
        system: str,
        user: str,
        output_schema: dict[str, Any],
        output_name: str,
        output_description: str,
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> tuple[dict[str, Any], TokenUsage]:
        self.calls.append({"output_name": output_name, "user": user})
        usage = TokenUsage(input_tokens=10, output_tokens=20, model="fake")
        return self._payload, usage


@pytest.fixture
def fake_llm():
    """payload를 받아 FakeLLMClient를 만들어 주는 팩토리 픽스처."""

    def _make(payload: dict[str, Any]) -> FakeLLMClient:
        return FakeLLMClient(payload)

    return _make


@pytest.fixture
def inventory() -> APIInventory:
    return APIInventory(
        project_id="proj_test",
        endpoints=[
            APIEndpoint(
                endpoint_id="POST:/api/v1/auth/signup",
                path="/api/v1/auth/signup",
                method="POST",
                summary="회원가입",
                auth=AuthScheme(type="none"),
                response_schema={
                    "type": "object",
                    "properties": {"userId": {"type": "integer"}},
                },
            ),
            APIEndpoint(
                endpoint_id="POST:/api/v1/auth/login",
                path="/api/v1/auth/login",
                method="POST",
                summary="로그인",
                auth=AuthScheme(type="none"),
                response_schema={
                    "type": "object",
                    "properties": {"accessToken": {"type": "string"}},
                },
            ),
            APIEndpoint(
                endpoint_id="POST:/api/v1/orders",
                path="/api/v1/orders",
                method="POST",
                summary="주문 생성",
                auth=AuthScheme(type="bearer"),
            ),
        ],
    )


@pytest.fixture
def request_nl(inventory: APIInventory) -> ScenarioGenerationRequest:
    return ScenarioGenerationRequest(
        project_id="proj_test",
        mode=ScenarioGenerationMode.NATURAL_LANGUAGE,
        user_intent="회원가입 → 로그인 → 주문",
        api_inventory=inventory,
        max_scenarios=2,
        max_steps_per_scenario=5,
    )