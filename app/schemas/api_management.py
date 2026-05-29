"""API Management Agent 스키마."""

from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field


class APIManagementRequest(BaseModel):
    """API Management Agent 입력."""
    message: str
    context: dict[str, Any] = Field(default_factory=dict)
    # 서버에서 조회해온 API 목록 (dispatcher가 채워줌)
    api_list: list[dict[str, Any]] = Field(default_factory=list)


class APIManagementResult(BaseModel):
    """API Management Agent 출력."""
    intent: str
    confidence: float
    status: str
    target: dict[str, Any]
    action: dict[str, Any]
    userMessage: str