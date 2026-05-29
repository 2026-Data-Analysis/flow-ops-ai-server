"""Responder 노드.

서버에서 받아온 API 목록을 바탕으로 사용자에게 적절한 응답 구성.
- 결과가 1개면 상세 조회 redirect
- 결과가 여러 개면 목록 redirect
- 결과가 없으면 need_clarification
"""

from __future__ import annotations

import json
import logging

from pydantic import BaseModel, Field, ValidationError

from app.agents.api_management.state import APIManagementError, APIManagementState
from app.llm import LLMClient

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
당신은 FlowOps의 API 관리 어시스턴트입니다.

사용자 메시지와 서버에서 조회된 API 목록을 바탕으로 적절한 응답을 구성하세요.

## Intent 목록
- query_api_detail: API 상세 조회 (결과가 1개일 때)
- query_api_list: API 목록 조회 (결과가 여러 개일 때)

## Status 규칙
- redirect: 조회 결과가 있어 화면 이동이 가능할 때
- need_clarification: 결과가 없거나 조건이 모호해 추가 질문이 필요할 때

## Action 규칙
- 결과가 1개: type=redirect, route=/applications/{applicationId}/apis/{apiId}
- 결과가 여러 개: type=redirect, route=/applications/{applicationId}/apis + 검색 조건을 query string으로
- 결과가 없음: type=clarify, 추가 조건 안내

## 응답 원칙
- userMessage는 한국어로 친절하게.
- confidence는 0.0~1.0 float.

반드시 emit_api_response 도구를 호출해 반환하세요.
"""


class _ResponderOutput(BaseModel):
    intent: str
    confidence: float
    status: str
    target: dict = Field(default_factory=dict)
    action: dict = Field(default_factory=dict)
    user_message: str


def make_responder_node(llm: LLMClient):
    def responder_node(state: APIManagementState) -> dict:
        errors = state.get("errors", [])
        if any(e["node"] in ("intent_parser", "api_fetcher") for e in errors):
            return {}

        message = state.get("message", "")
        raw_api_list = state.get("raw_api_list", [])
        search_query = state.get("search_query", {})
        context = state.get("context", {})
        app_id = context.get("applicationId", "")

        # 수정 후
        api_sample = raw_api_list[:20] if isinstance(raw_api_list, list) else []

        # method 필터링
        if search_query.get("method"):
            method = search_query["method"].upper()
            api_sample = [
                api for api in api_sample
                if str(api.get("method", "")).upper() == method
            ]

        user_content = f"""\
        사용자 메시지: {message}

        검색 조건: {json.dumps(search_query, ensure_ascii=False)}

        조회된 API 목록 ({len(api_sample)}건):
        {json.dumps(api_sample, ensure_ascii=False, indent=2)}

        applicationId: {app_id}
        """

        try:
            raw_output, usage = llm.generate_structured(
                system=SYSTEM_PROMPT,
                user=user_content,
                output_schema=_ResponderOutput.model_json_schema(),
                output_name="emit_api_response",
                output_description="API 조회 결과 기반 응답 구성",
                max_tokens=800,
                temperature=0.0,
            )
        except Exception as e:
            logger.exception("responder LLM call failed")
            return {
                "errors": [APIManagementError(
                    node="responder",
                    code="LLM_CALL_FAILED",
                    message=str(e),
                )]
            }

        try:
            parsed = _ResponderOutput.model_validate(raw_output)
        except ValidationError as e:
            return {
                "errors": [APIManagementError(
                    node="responder",
                    code="OUTPUT_VALIDATION_FAILED",
                    message=str(e),
                )],
                "token_usages": [usage],
            }

        return {
            "intent": parsed.intent,
            "confidence": parsed.confidence,
            "status": parsed.status,
            "target": parsed.target,
            "action": parsed.action,
            "user_message": parsed.user_message,
            "token_usages": [usage],
        }

    return responder_node