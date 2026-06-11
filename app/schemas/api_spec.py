"""API 명세 스키마.

백엔드(Spring Boot)에서 OpenAPI/Swagger 파싱 또는 Controller 정적 분석을 통해
추출한 API 메타데이터를 AI 서버로 전달할 때 사용한다.

이 스키마는 시나리오 Agent뿐 아니라 테스트 케이스 Agent, 장애 대응 Agent
모두가 공유하므로 절대 시나리오 전용 필드를 추가하지 않는다.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from .common import HttpMethod


class AuthScheme(BaseModel):
    """인증 방식. 단순화하여 'none' / 'bearer' / 'api_key' / 'session' 정도만 다룬다."""

    type: str = Field(description="인증 타입. 예: bearer, api_key, session, none")
    location: str | None = Field(
        default=None,
        description="api_key일 때 헤더명 또는 쿼리 파라미터명",
    )


class ParameterSpec(BaseModel):
    """경로/쿼리/헤더 파라미터 명세."""

    name: str
    location: str = Field(description="path, query, header 중 하나")
    type: str = Field(description="JSON 스키마 타입: string, integer, boolean, ...")
    required: bool = False
    description: str | None = None
    example: Any | None = None


class APIEndpoint(BaseModel):
    """단일 API 엔드포인트 명세.

    Shared Memory 키는 endpoint_id로 관리한다.
    request_body_schema/response_schema는 JSON Schema 그대로 받는다
    (LLM이 JSON Schema를 잘 이해하므로 변환하지 않음).

    response_schema는 두 형태를 모두 허용한다(backward-compatible):
    - [구] 단일 성공 응답 JSON Schema
    - [신] OpenAPI responses 요약 {expectedStatusCodes, errorStatusCodes, responses[]}
    어느 형태든 해석은 app/core/response_spec.py의 헬퍼(success_schema,
    expected_status_codes, error_status_codes 등)로 통일한다. 소비부(planner/
    chainer/validator/testcase)가 키를 직접 파싱하지 말 것 — 형태 분기가 한 곳에 모이도록.
    """

    endpoint_id: str = Field(description="고유 식별자, 예: 'POST:/api/v1/users'")
    path: str = Field(description="경로, 예: /api/v1/users/{userId}")
    method: HttpMethod
    summary: str | None = Field(default=None, description="짧은 한 줄 설명")
    description: str | None = None

    parameters: list[ParameterSpec] = Field(default_factory=list)
    request_body_schema: dict[str, Any] | None = Field(
        default=None,
        description="JSON Schema 형식의 요청 바디 명세",
    )
    response_schema: dict[str, Any] | None = Field(
        default=None,
        description=(
            "응답 명세. 두 형태를 모두 허용한다(backward-compatible). "
            "[구] 단일 성공 응답 JSON Schema(200 기준). "
            "[신] OpenAPI responses 요약 {expectedStatusCodes, errorStatusCodes, responses[]}. "
            "해석은 app/core/response_spec.py 헬퍼로 통일(직접 키 파싱 금지)."
        ),
    )

    auth: AuthScheme | None = None
    tags: list[str] = Field(
        default_factory=list,
        description="OpenAPI 태그. 도메인 그룹핑에 활용 (예: 'auth', 'posts')",
    )


class APIInventory(BaseModel):
    """프로젝트의 전체 API 목록.

    시나리오 Agent의 입력으로 자주 사용된다. endpoint_id → APIEndpoint 매핑은
    호출 시 dict로 변환해서 쓴다.
    """

    project_id: str
    endpoints: list[APIEndpoint]

    def by_id(self) -> dict[str, APIEndpoint]:
        """endpoint_id로 빠르게 조회할 수 있는 dict 반환."""
        return {ep.endpoint_id: ep for ep in self.endpoints}