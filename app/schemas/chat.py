"""챗봇 Agent 공통 응답 스키마.

Application / Environment Agent가 공유하는 구조화 응답 형식.
"""

from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field


class ChatTarget(BaseModel):
    resourceType: str
    resourceId: str | None = None
    displayName: str | None = None


class ChatConfirmation(BaseModel):
    title: str
    message: str
    confirmLabel: str
    cancelLabel: str
    danger: bool = False


class ChatAction(BaseModel):
    type: str  # redirect | open_form | create | update | delete
    route: str | None = None
    payload: dict[str, Any] | None = None
    form: dict[str, Any] | None = None


class ChatValidation(BaseModel):
    required: bool = False
    type: str | None = None
    payload: dict[str, Any] | None = None


class ChatResponse(BaseModel):
    intent: str
    confidence: float
    status: str  # ready | need_clarification | collect_input | need_validation | redirect | unsupported
    target: ChatTarget
    action: ChatAction
    validation: ChatValidation | None = None
    clarification: str | None = None
    requiresUserConfirmation: bool = False
    confirmation: ChatConfirmation | None = None
    userMessage: str


class ChatRequest(BaseModel):
    """챗봇 요청. 초기 요청 + formSubmission 재요청 모두 이 구조 사용."""

    message: str
    context: dict[str, Any] = Field(default_factory=dict)
    formSubmission: dict[str, Any] | None = None