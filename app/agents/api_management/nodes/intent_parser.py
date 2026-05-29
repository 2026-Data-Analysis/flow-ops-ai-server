"""Intent Parser 노드.

사용자 메시지에서 API 검색 조건을 추출.
서버 호출 전에 어떤 조건으로 API를 가져올지 결정.
"""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field, ValidationError

from app.agents.api_management.state import APIManagementError, APIManagementState
from app.llm import LLMClient

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
당신은 FlowOps의 API 검색 조건 추출기입니다.

사용자 메시지에서 API 검색에 필요한 조건을 추출하세요.

추출 가능한 조건:
- method: GET | POST | PUT | PATCH | DELETE (언급된 경우만)
- keyword: 경로나 기능 관련 키워드 (예: user, order, login)
- tag: API 태그/도메인 (예: auth, payment)

조건이 언급되지 않은 필드는 null로 두세요.
반드시 emit_search_query 도구를 호출해 반환하세요.
"""


class _SearchQuery(BaseModel):
    method: str | None = Field(default=None, description="GET | POST | PUT | PATCH | DELETE")
    keyword: str | None = Field(default=None, description="경로나 기능 관련 키워드")
    tag: str | None = Field(default=None, description="API 태그/도메인")


def make_intent_parser_node(llm: LLMClient):
    def intent_parser_node(state: APIManagementState) -> dict:
        message = state.get("message", "")

        try:
            raw_output, usage = llm.generate_structured(
                system=SYSTEM_PROMPT,
                user=message,
                output_schema=_SearchQuery.model_json_schema(),
                output_name="emit_search_query",
                output_description="API 검색 조건 추출",
                max_tokens=300,
                temperature=0.0,
            )
        except Exception as e:
            logger.exception("intent_parser LLM call failed")
            return {
                "errors": [APIManagementError(
                    node="intent_parser",
                    code="LLM_CALL_FAILED",
                    message=str(e),
                )]
            }

        try:
            parsed = _SearchQuery.model_validate(raw_output)
        except ValidationError as e:
            return {
                "errors": [APIManagementError(
                    node="intent_parser",
                    code="OUTPUT_VALIDATION_FAILED",
                    message=str(e),
                )],
                "token_usages": [usage],
            }

        return {
            "search_query": parsed.model_dump(exclude_none=True),
            "token_usages": [usage],
        }

    return intent_parser_node