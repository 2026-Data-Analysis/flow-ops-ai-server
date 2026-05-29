"""Incident Response Agent 스키마.

IncidentAnalysisRequest: Agent 입력.
IncidentAnalysisResult: Agent 출력 (AgentResponse[T]의 T).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class LogEntry(BaseModel):
    """구조화된 로그 엔트리 1건 (백엔드가 직접 파싱해서 보낼 때 사용)."""

    timestamp: str | None = None
    level: str | None = Field(default=None, description="ERROR / WARN / INFO 등")
    message: str
    logger: str | None = None
    stack_trace: str | None = None
    extra: dict[str, Any] | None = None


class FailureContext(BaseModel):
    """테스트 실패 컨텍스트 (시나리오/단건 테스트 실패 분석 시 첨부)."""

    test_case_id: str | None = None
    endpoint: str | None = None
    expected_status: int | None = None
    actual_status: int | None = None
    request_body: dict[str, Any] | None = None
    response_body: dict[str, Any] | None = None
    error_message: str | None = None


class IncidentAnalysisRequest(BaseModel):
    """Incident Agent 입력."""

    project_id: str
    service_name: str = Field(description="서비스/컴포넌트 이름. 보고서에 포함됨.")
    occurred_at: str | None = Field(default=None, description="장애 발생 시각 (ISO 8601)")

    # 로그 입력: 둘 중 하나 이상 필수
    raw_log: str | None = Field(default=None, description="원시 로그 문자열")
    log_entries: list[LogEntry] | None = Field(
        default=None,
        description="백엔드가 파싱한 구조화 로그 엔트리",
    )

    # 선택: 테스트 실패 컨텍스트
    failure_context: FailureContext | None = None


class RootCauseSummary(BaseModel):
    """클라이언트에게 노출할 원인 요약 (State의 RootCauseCandidate를 직렬화)."""

    summary: str
    severity: str
    suggested_fix: str
    evidence: list[str]


class IncidentAnalysisResult(BaseModel):
    """Incident Agent 출력."""

    root_causes: list[RootCauseSummary]
    internal_report: str
    external_notice: str
