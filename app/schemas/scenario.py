"""시나리오 테스트 Agent 핵심 스키마.

설계 결정:
1. Response Chaining은 구조화 매핑(ChainedVariable)으로 표현.
   - 백엔드가 실제 실행 시 그대로 사용 가능
   - 프론트의 블록 UI에서 변수 흐름을 시각화 가능
   - LLM이 잘못된 경로를 만들어도 검증 가능
2. 시나리오 메타(rationale, coverage_gap)는 시나리오 자체와 분리해서 추천 모드에서만 채움.
3. 모든 ID는 LLM이 생성하지 않고 서버에서 발급(uuid). LLM은 step_ref로만 참조.

[1단계] ScenarioStep을 testcase 초안(TestCaseDraft)과 동일한 필드 세트로 정렬
        (shared memory 호환). 단, 실행 순서(ref/order)와 응답 체이닝(chained_variables)은 유지.
[2단계] LLM이 type/requestSpec/expectedSpec/assertionSpec을 직접 채우므로,
        전환기 필드였던 expected_assertions 제거 (assertionSpec.bodyContains로 흡수됨).
[3단계] test_case_type(NORMAL/EXCEPTION/BOUNDARY 매핑값) 제거.
        위험도 분류가 아니라 type(DraftType)의 단순 파생값이라 응답에 불필요 (현서 피드백 반영).
        NORMAL/EXCEPTION/BOUNDARY가 필요하면 호출 측에서 DRAFT_TO_TEST_CASE_TYPE로 매핑.
"""

from __future__ import annotations

from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from .api_spec import APIInventory
from .common import RiskLevel
from .testcase import DraftType, TestCase


# ---------------------------------------------------------------------------
# 모드 enum
# ---------------------------------------------------------------------------


class ScenarioGenerationMode(str, Enum):
    """시나리오 생성 모드.

    - NATURAL_LANGUAGE: 사용자가 자연어로 흐름을 묘사 (예: "회원가입 후 첫 글 작성")
    - RECOMMEND: 등록된 API와 기존 테스트 이력 기반으로 부족한 시나리오 자동 추천
    """

    NATURAL_LANGUAGE = "NATURAL_LANGUAGE"
    RECOMMEND = "RECOMMEND"


# ---------------------------------------------------------------------------
# Response Chaining
# ---------------------------------------------------------------------------


class VariableSource(str, Enum):
    """체이닝된 변수의 출처."""

    PREVIOUS_STEP = "PREVIOUS_STEP"  # 이전 스텝의 응답에서 추출
    LITERAL = "LITERAL"              # 고정 리터럴 값
    GENERATED = "GENERATED"          # 테스트 실행기가 생성 (예: uuid, 현재시각)


class ChainedVariable(BaseModel):
    """Response Chaining 매핑 1건.

    예시:
        # step_1의 응답 body에서 access_token을 뽑아 step_2의 Authorization 헤더에 주입
        ChainedVariable(
            name="auth_token",
            source=VariableSource.PREVIOUS_STEP,
            source_step_ref="step_1",
            source_json_path="$.data.accessToken",
            target_location="header",
            target_field="Authorization",
            target_template="Bearer {value}",
        )
    """

    name: str = Field(description="변수의 논리 이름. 한 시나리오 안에서 유일")
    source: VariableSource

    # PREVIOUS_STEP인 경우에만 채움
    source_step_ref: str | None = Field(
        default=None,
        description="추출 대상 스텝의 ref (Scenario.steps[i].ref). LLM이 생성·참조하는 단축 식별자",
    )
    source_json_path: str | None = Field(
        default=None,
        description="응답에서 값을 뽑을 JSONPath. 예: $.data.userId",
    )

    # LITERAL인 경우에만 채움
    literal_value: Any | None = None

    # 주입 위치 (모든 source 공통)
    target_location: str = Field(
        description="path, query, header, body 중 하나",
    )
    target_field: str = Field(
        description="주입할 필드명. body면 JSONPath, header면 헤더명, path면 변수명",
    )
    target_template: str | None = Field(
        default=None,
        description="값 포맷 템플릿. {value}가 자리표시자. 예: 'Bearer {value}'",
    )


# ---------------------------------------------------------------------------
# Scenario Step  (testcase draft 호환 + 시나리오 고유 필드 병합)
# ---------------------------------------------------------------------------


class ScenarioStep(BaseModel):
    """시나리오를 구성하는 단일 API 호출 스텝.

    필드 구성:
    - 시나리오 고유: step_id, ref, order, chained_variables
      (실행 순서와 응답 체이닝 — 시나리오의 본질이므로 유지)
    - testcase draft 호환: apiId, title, description, type,
      userRole, stateCondition, dataVariant, requestSpec, expectedSpec,
      assertionSpec, duplicate
      (TestCaseDraft와 동일 구조로 shared memory에서 동일하게 파싱·저장)

    LLM은 ref(예: 'step_1', 'step_2')만 생성하고, 실제 실행 ID(step_id)는
    서버에서 uuid로 발급한다.
    """

    # === 시나리오 고유: 실행 순서 / 체이닝 ===
    step_id: str = Field(default_factory=lambda: str(uuid4()))
    ref: str = Field(description="LLM·다른 스텝이 참조할 단축 식별자. 예: 'step_1'")
    order: int = Field(description="시나리오 내 실행 순서 (1부터)")

    # 이 스텝이 사용하는 체이닝 변수들 (이전 스텝에서 가져옴)
    chained_variables: list[ChainedVariable] = Field(default_factory=list)

    # === testcase draft 호환 필드 ===
    apiId: str = Field(description="호출할 APIEndpoint.endpoint_id (기존 endpoint_id)")
    title: str = Field(description="이 스텝이 무엇을 하는지 짧은 이름 (기존 name). 예: '로그인'")
    description: str | None = None

    type: DraftType = Field(
        default=DraftType.HAPPY_PATH,
        description="생성 분류 (HAPPY_PATH / VALIDATION / FAILURE_HANDLING / EDGE_CASE / AUTHORIZATION / PERFORMANCE)",
    )

    userRole: str | None = None
    stateCondition: str | None = None
    dataVariant: str | None = None

    requestSpec: dict[str, Any] | None = Field(
        default=None,
        description="요청 스펙. {method, pathParams, queryParams, body}. "
                    "body의 고정값 위에 chained_variables가 동적으로 덮어쓴다.",
    )
    expectedSpec: dict[str, Any] | None = Field(
        default=None,
        description="기대 응답. {statusCode, body, errorMessage}",
    )
    assertionSpec: dict[str, Any] | None = Field(
        default=None,
        description="검증 스펙. {statusCode, bodyContains, bodyEquals, headerContains}",
    )

    duplicate: bool = False


# ---------------------------------------------------------------------------
# Scenario
# ---------------------------------------------------------------------------


class ScenarioMeta(BaseModel):
    """추천 모드에서 채워지는 메타.

    자연어 모드에서는 rationale만 채우고 coverage_gap은 비움.
    """

    rationale: str = Field(description="이 시나리오를 만든·추천한 이유 (사람이 읽을 수 있게)")
    coverage_gap: str | None = Field(
        default=None,
        description="추천 모드 한정. 어떤 커버리지 갭을 메우는지. 예: '결제 실패 후 재시도 흐름 없음'",
    )
    estimated_risk: RiskLevel = Field(
        default=RiskLevel.MEDIUM,
        description="이 시나리오에서 문제 발생 시 영향도(시나리오 단위). 값은 대문자 enum(LOW/MEDIUM/HIGH/CRITICAL). "
                    "risk 노드가 app/core/risk.py의 공용 assess_risk로 산정.",
    )


class Scenario(BaseModel):
    """End-to-End 시나리오 1건.

    프론트의 블록 UI 1개에 대응. steps의 order대로 실행한다.
    """

    scenario_id: str = Field(default_factory=lambda: str(uuid4()))
    name: str = Field(description="시나리오 이름. 예: '신규 사용자 첫 게시글 작성 흐름'")
    description: str | None = None

    steps: list[ScenarioStep]
    meta: ScenarioMeta


# ---------------------------------------------------------------------------
# Agent 입출력
# ---------------------------------------------------------------------------


class ScenarioGenerationRequest(BaseModel):
    """시나리오 Agent의 입력.

    백엔드가 이 형태로 AI 서버에 POST 한다.
    """

    project_id: str
    mode: ScenarioGenerationMode

    # NATURAL_LANGUAGE 모드에서 필수
    user_intent: str | None = Field(
        default=None,
        description="자연어 흐름 설명. 예: '회원가입 → 로그인 → 첫 게시글 작성'",
    )

    # 공통: 시나리오 생성의 재료
    api_inventory: APIInventory = Field(description="이 프로젝트의 전체 API 목록")
    existing_test_cases: list[TestCase] = Field(
        default_factory=list,
        description="기존 단건 테스트 이력. 추천 모드/중복 제거에서 사용",
    )

    # 옵션
    max_scenarios: int = Field(
        default=3,
        ge=1,
        le=10,
        description="추천 모드에서 생성할 최대 시나리오 수",
    )
    max_steps_per_scenario: int = Field(
        default=8,
        ge=2,
        le=20,
        description="시나리오 1개당 최대 스텝 수. 너무 길어지면 LLM 정확도 하락",
    )


class ScenarioGenerationResult(BaseModel):
    """시나리오 Agent의 출력 (AgentResponse[T]의 T 자리에 들어감)."""

    scenarios: list[Scenario]
    used_endpoint_ids: list[str] = Field(
        description="시나리오에서 실제로 사용된 모든 apiId (중복 제거)",
    )