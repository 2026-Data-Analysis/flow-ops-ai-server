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
    """위험도 레벨 (제안서 2.2 비교표 'AI 위험도 분류' 항목과 일치)."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


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
