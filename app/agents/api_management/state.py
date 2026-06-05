"""API Management Agent State."""

from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict

from app.schemas import TokenUsage


class APIManagementError(TypedDict):
    node: str
    code: str
    message: str


class APIManagementState(TypedDict, total=False):
    # 입력
    message: str
    context: dict[str, Any]

    # intent_parser 출력
    search_query: dict[str, Any]
    # 예: {"method": "GET", "keyword": "user", "tag": "auth"}

    # api_fetcher 출력 (서버에서 받아온 원본 목록)
    raw_api_list: list[dict[str, Any]]

    # responder 출력
    intent: str
    confidence: float
    status: str
    target: dict[str, Any]
    action: dict[str, Any]
    user_message: str

    # 누적
    errors: Annotated[list[APIManagementError], operator.add]
    token_usages: Annotated[list[TokenUsage], operator.add]
    trace_id: str


def initial_state(
    message: str,
    context: dict[str, Any],
    trace_id: str,
) -> APIManagementState:
    return APIManagementState(
        message=message,
        context=context,
        errors=[],
        token_usages=[],
        trace_id=trace_id,
    )