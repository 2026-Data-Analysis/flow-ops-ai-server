"""단건 테스트 케이스 스키마.

주 담당은 테스트 코드 생성 Agent이지만, 시나리오 Agent가
'기존 이력 기반 추천'을 위해 참조해야 하므로 공용 위치에 둔다.

여기서는 시나리오 Agent가 필요로 하는 '최소 필드'만 정의한다.
테스트 코드 Agent 담당자가 어서션·태그·생성 메타 등을 자유롭게 확장 가능.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class TestCaseType(str, Enum):
    """제안서 2.3 '정상·예외·경계값' 분류."""

    NORMAL = "NORMAL"
    EXCEPTION = "EXCEPTION"
    BOUNDARY = "BOUNDARY"


class TestCase(BaseModel):
    """단건 API 테스트 케이스.

    시나리오 Agent는 이 정보를 통해 '이 API에 정상 케이스만 있고
    예외 케이스가 없네' 같은 커버리지 분석을 수행한다.
    """

    test_case_id: str
    endpoint_id: str = Field(description="대상 API. APIEndpoint.endpoint_id와 일치")
    type: TestCaseType
    name: str = Field(description="사람이 읽을 수 있는 케이스 이름")

    request_payload: dict[str, Any] | None = Field(
        default=None,
        description="요청 바디 (있을 경우)",
    )
    request_params: dict[str, Any] = Field(
        default_factory=dict,
        description="경로/쿼리 파라미터 값",
    )

    expected_status_code: int = Field(description="기대 HTTP 상태 코드")
