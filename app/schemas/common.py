"""공통 enum, 응답 래퍼, 기본 타입.

여러 에이전트가 공유하는 가장 기본적인 타입들을 정의한다.
도메인에 종속되지 않는 것만 여기에 둔다.
"""

from __future__ import annotations

from enum import Enum
from typing import Generic, TypeVar

from pydantic import BaseModel, Field


class HttpMethod(str, Enum):
    """HTTP 메서드. API 명세 및 테스트 스텝에서 공통 사용."""

    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    PATCH = "PATCH"
    DELETE = "DELETE"


class RiskLevel(str, Enum):
    """위험도 심각도 레벨 (제안서 2.2 비교표 'AI 위험도 분류' 항목과 일치).

    테스트 레벨(TestLevel)과는 다른 축이다. 이 enum은 '문제 발생 시 영향도'를
    나타내며, 위험도 분류 에이전트(app/core/risk.py의 assess_risk)가 산정한다.
    """

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class TestLevel(str, Enum):
    """테스트 레벨 (smoke / sanity / regression / full suite).

    RiskLevel(위험도 심각도)과는 별개의 축이다. 시나리오·테스트케이스의
    '어느 범위의 테스트인지'를 나타낸다.

    NOTE: testcase.py의 testLevel은 현재 자유문자열(str)이므로,
    백엔드 Classifier가 사용하는 문자열 값과 표기가 일치해야 한다.
    """

    SMOKE = "SMOKE"
    SANITY = "SANITY"
    REGRESSION = "REGRESSION"
    FULL_SUITE = "FULL_SUITE"


T = TypeVar("T")


class AgentResponse(BaseModel, Generic[T]):
    """에이전트 응답 공통 래퍼.

    백엔드(Spring)가 항상 동일한 형태로 받을 수 있도록 표준화.
    """

    success: bool = Field(description="에이전트 실행 성공 여부")
    data: T | None = Field(default=None, description="실제 결과 페이로드")
    error_code: str | None = Field(default=None, description="실패 시 식별자")
    error_message: str | None = Field(default=None, description="사람이 읽을 수 있는 메시지")
    trace_id: str | None = Field(default=None, description="LangSmith·로그 추적용 ID")


class TokenUsage(BaseModel):
    """LLM 호출 토큰 사용량. 비용 추적·평가용."""

    input_tokens: int = 0
    output_tokens: int = 0
    model: str = Field(description="사용한 모델명, 예: claude-sonnet-4-5")