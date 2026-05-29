"""Incident Response Agent의 LangGraph State.

처리 흐름:
  log_parser → analyzer → reporter → END

설계 결정:
1. 로그는 raw 문자열 또는 구조화 리스트 모두 수용 (log_raw / log_entries).
2. analyzer가 원인 후보(root_cause_candidates)를 만들고,
   reporter가 이를 내부/외부 보고서 두 종류로 변환.
3. errors / token_usages는 시나리오 Agent와 동일한 Annotated + operator.add 패턴.
"""

from __future__ import annotations

import operator
from typing import Annotated, TypedDict

from app.schemas import TokenUsage
from app.schemas.incident import IncidentAnalysisRequest


class RootCauseCandidate(TypedDict):
    """원인 후보 1건."""

    summary: str          # 한 줄 요약
    evidence: list[str]   # 근거 로그 라인 or 메시지
    severity: str         # CRITICAL / HIGH / MEDIUM / LOW
    suggested_fix: str    # 수정 방향 제안


class IncidentAgentError(TypedDict):
    node: str
    code: str
    message: str


class IncidentAgentState(TypedDict, total=False):
    # 입력
    request: IncidentAnalysisRequest

    # log_parser 출력: 정제된 로그 엔트리 리스트
    parsed_log_entries: list[dict]

    # analyzer 출력
    root_cause_candidates: list[RootCauseCandidate]

    # reporter 출력
    internal_report: str    # 개발팀용: 로그 요약 + 원인 + 수정 방향
    external_notice: str    # 사용자 공지용: 친화적 안내 문구

    # 누적
    errors: Annotated[list[IncidentAgentError], operator.add]
    token_usages: Annotated[list[TokenUsage], operator.add]
    trace_id: str


def initial_state(
    request: IncidentAnalysisRequest,
    trace_id: str,
) -> IncidentAgentState:
    return IncidentAgentState(
        request=request,
        errors=[],
        token_usages=[],
        trace_id=trace_id,
    )
