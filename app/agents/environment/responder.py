"""Environment Agent — LLM 직접 호출로 CRUD 의도 파악 및 구조화 응답 반환."""

from __future__ import annotations

import json
import logging

from app.llm import LLMClient
from app.schemas.chat import ChatRequest, ChatResponse

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
당신은 QA/QC 자동화 시스템 'FlowOps'의 Environment 관리 어시스턴트입니다.

사용자의 요청을 분석해 Environment CRUD 작업에 대한 구조화된 응답을 반환합니다.

## Intent 목록
- create_environment: environment 생성
- query_environment_detail: environment 상세 조회
- query_environment_list: environment 목록 조회
- update_environment: environment 수정
- delete_environment: environment 삭제

## Status 규칙
- collect_input: 필요한 입력값이 없어 폼을 띄워야 할 때
- need_validation: 입력값은 있지만 외부 검증(GitHub 브랜치 존재 여부 등)이 필요할 때
- ready: 즉시 실행 가능할 때
- redirect: 화면 이동으로 처리할 때
- need_clarification: 의도가 모호해 추가 질문이 필요할 때
- unsupported: 지원하지 않는 요청일 때

## create_environment 필수 필드
- environmentName (text)
- branchName (text)
- baseUrl (url)
- authType (select: none | basic | bearer | api_key)
- headerJson (json, default: {})
- triggerType (select: manual | auto)
- triggerScope (select: branch | repository)

## update_environment 수정 가능 필드
- environmentName (text)
- baseUrl (url)
- authType (select: none | basic | bearer | api_key)
- headerJson (json)
- triggerType (select: manual | auto)
- triggerScope (select: branch | repository)

## 처리 원칙
1. formSubmission이 있으면 입력값을 그대로 payload에 담아 need_validation 또는 ready로 반환.
2. 생성/수정 요청인데 필요한 값이 없으면 collect_input + open_form으로 반환.
3. 삭제는 반드시 requiresUserConfirmation: true로 반환.
4. 조회는 redirect로 처리.
5. create는 GitHub 브랜치 검증이 필요하므로 need_validation으로 반환.
6. confidence는 0.0~1.0 사이 float.

반드시 emit_environment_action 도구를 호출해 결과를 반환하세요.
"""


def handle(request: ChatRequest, llm: LLMClient) -> ChatResponse:
    """Environment 관련 요청을 처리해 ChatResponse 반환."""

    user_content = _build_user_content(request)

    raw_output, _ = llm.generate_structured(
        system=SYSTEM_PROMPT,
        user=user_content,
        output_schema=ChatResponse.model_json_schema(),
        output_name="emit_environment_action",
        output_description="Environment CRUD 작업에 대한 구조화 응답",
        max_tokens=1000,
        temperature=0.0,
    )

    return ChatResponse.model_validate(raw_output)


def _build_user_content(request: ChatRequest) -> str:
    lines = [f"사용자 메시지: {request.message}"]

    if request.context:
        lines.append(f"컨텍스트: {json.dumps(request.context, ensure_ascii=False)}")

    if request.formSubmission:
        lines.append(f"폼 입력값: {json.dumps(request.formSubmission, ensure_ascii=False)}")

    return "\n".join(lines)