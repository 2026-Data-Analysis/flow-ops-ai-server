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


# ──── TestCase Generation Agent 전용 확장 ────────────────────────────────────


class DraftType(str, Enum):
    """생성 단계 세부 분류. TestCaseType으로 매핑되어 Backend에 저장된다."""

    HAPPY_PATH = "HAPPY_PATH"         # → NORMAL
    VALIDATION = "VALIDATION"         # → EXCEPTION
    FAILURE_HANDLING = "FAILURE_HANDLING"  # → EXCEPTION
    EDGE_CASE = "EDGE_CASE"           # → BOUNDARY
    AUTHORIZATION = "AUTHORIZATION"   # → EXCEPTION
    PERFORMANCE = "PERFORMANCE"       # → NORMAL


DRAFT_TO_TEST_CASE_TYPE: dict[DraftType, TestCaseType] = {
    DraftType.HAPPY_PATH: TestCaseType.NORMAL,
    DraftType.VALIDATION: TestCaseType.EXCEPTION,
    DraftType.FAILURE_HANDLING: TestCaseType.EXCEPTION,
    DraftType.EDGE_CASE: TestCaseType.BOUNDARY,
    DraftType.AUTHORIZATION: TestCaseType.EXCEPTION,
    DraftType.PERFORMANCE: TestCaseType.NORMAL,
}


# ── Request sub-models ───────────────────────────────────────────────────────

class ProjectInfo(BaseModel):
    projectId: str
    appId: str
    appName: str


class EnvironmentInfo(BaseModel):
    environmentId: str
    name: str
    baseUrl: str
    defaultTestLevel: str


class RequestMetadata(BaseModel):
    language: str
    createdAt: str
    source: str


class GenerationContext(BaseModel):
    generationId: str
    mode: str
    testLevel: str
    currentCoverage: float
    targetCoverage: float
    contextSummary: str | None = None
    # ▼ 오케스트레이터 연동을 위해 새로 뚫어두는 바구니 2개 ▼
    userInstruction: str | None = Field(
        default=None, 
        description="사용자가 직접 입력한 자연어 요구사항 (예: '장바구니 결제 테스트해줘')"
    )
    validIdentifiers: dict[str, list[Any]] | None = Field(
        default=None,
        description="DB에 존재하는 실제 유효값 샘플 (예: {'appId': ['app-1', 'app-2']})"
    )


class ExpandedResponse(BaseModel):
    statusCode: str
    category: str
    description: str
    schema_obj: dict[str, Any] | None = Field(default=None, alias="schema")
    sampleBody: Any | None = None

class ExpandedResponseSchema(BaseModel):
    expectedStatusCodes: list[int] = Field(default_factory=list)
    errorStatusCodes: list[int] = Field(default_factory=list)
    responses: list[ExpandedResponse] = Field(default_factory=list)


class ApiSpec(BaseModel):
    """Backend(Spring Boot)가 보내는 API 명세. camelCase 컨벤션 유지."""

    apiId: str
    method: str
    path: str
    domainTag: str | None = None
    requestSchema: dict[str, Any] | None = None
    # 기존 단일 dict와 신규 ExpandedResponseSchema를 모두 허용 (Backward Compatibility)
    responseSchema: dict[str, Any] | ExpandedResponseSchema | None = None
    authRequired: bool = False
    deprecated: bool = False


class ExistingTestCase(BaseModel):
    testCaseId: str
    apiId: str
    name: str
    type: DraftType          # Backend 저장 시 DraftType 그대로 보존
    testLevel: str
    requestSpec: dict[str, Any] | None = None
    expectedSpec: dict[str, Any] | None = None
    assertionSpec: dict[str, Any] | None = None


class FailureContext(BaseModel):
    executionId: str
    stepId: str
    statusCode: int | None = None
    requestBody: dict[str, Any] | None = None
    responseBody: dict[str, Any] | None = None
    errorMessage: str | None = None
    expected: Any = None
    actual: Any = None


# ── Request ──────────────────────────────────────────────────────────────────

class TestCaseGenerationRequest(BaseModel):
    agent: str
    requestId: str
    requestedBy: str
    project: ProjectInfo
    environment: EnvironmentInfo
    metadata: RequestMetadata
    generationContext: GenerationContext
    apis: list[ApiSpec] = []
    existingTestCases: list[ExistingTestCase] = []
    failureContext: FailureContext | None = None


# ── Response sub-models ──────────────────────────────────────────────────────

class TestCaseDraft(BaseModel):
    """생성된 테스트 케이스 초안. testLevel은 Backend의 Classifier가 채운다."""

    apiId: str
    title: str
    description: str
    type: DraftType
    test_case_type: TestCaseType | None = Field(
        default=None,
        description="DRAFT_TO_TEST_CASE_TYPE 매핑 결과. 커버리지 분석에 사용.",
    )
    userRole: str | None = None
    stateCondition: str | None = None
    dataVariant: str | None = None
    requestSpec: dict[str, Any] | None = None
    expectedSpec: dict[str, Any] | None = None
    assertionSpec: dict[str, Any] | None = None
    duplicate: bool = False
    risk_level: str | None = None


# ── Response ─────────────────────────────────────────────────────────────────

class TestCaseGenerationResponse(BaseModel):
    requestId: str
    generationId: str
    drafts: list[TestCaseDraft]
