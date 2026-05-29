"""Incident Response Agent HTTP 인터페이스.

엔드포인트:
- POST /v1/agents/incident/analyze
  로그와 실패 컨텍스트를 받아 원인 분석 + 보고서 생성.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from langgraph.graph.state import CompiledStateGraph

from app.agents.incident.state import initial_state
from app.api.deps import get_incident_graph
from app.schemas import AgentResponse
from app.schemas.incident import (
    IncidentAnalysisRequest,
    IncidentAnalysisResult,
    RootCauseSummary,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/agents/incident", tags=["incident"])


@router.post(
    "/analyze",
    response_model=AgentResponse[IncidentAnalysisResult],
    summary="장애 원인 분석 및 보고서 생성",
    description=(
        "서버 로그와 테스트 실패 컨텍스트를 분석하여 원인 후보를 도출하고 "
        "개발팀용 / 사용자 공지용 보고서를 생성합니다."
    ),
)
def analyze_incident(
    payload: IncidentAnalysisRequest,
    graph: CompiledStateGraph = Depends(get_incident_graph),
) -> AgentResponse[IncidentAnalysisResult]:
    _validate_request(payload)

    trace_id = f"trace_{uuid.uuid4().hex[:12]}"
    logger.info(
        "incident.analyze start project=%s service=%s trace=%s",
        payload.project_id, payload.service_name, trace_id,
    )

    init = initial_state(payload, trace_id=trace_id)

    try:
        final = graph.invoke(init)
    except Exception as e:
        logger.exception("incident graph crashed trace=%s", trace_id)
        raise HTTPException(status_code=500, detail=f"incident agent crashed: {e}") from e

    errors = final.get("errors", [])
    internal_report = final.get("internal_report")
    external_notice = final.get("external_notice")
    candidates = final.get("root_cause_candidates", [])

    if not internal_report:
        first_err = errors[0] if errors else None
        return AgentResponse[IncidentAnalysisResult](
            success=False,
            error_code=(first_err["code"] if first_err else "ANALYSIS_FAILED"),
            error_message=(
                first_err["message"] if first_err
                else "장애 분석에 실패했습니다."
            ),
            trace_id=trace_id,
        )

    result = IncidentAnalysisResult(
        root_causes=[
            RootCauseSummary(
                summary=c["summary"],
                severity=c["severity"],
                suggested_fix=c["suggested_fix"],
                evidence=c["evidence"],
            )
            for c in candidates
        ],
        internal_report=internal_report,
        external_notice=external_notice or "",
    )

    logger.info(
        "incident.analyze done trace=%s causes=%d errors=%d",
        trace_id, len(candidates), len(errors),
    )
    return AgentResponse[IncidentAnalysisResult](
        success=True,
        data=result,
        error_message=f"{len(errors)}건의 부분 오류가 있었습니다." if errors else None,
        trace_id=trace_id,
    )


def _validate_request(payload: IncidentAnalysisRequest) -> None:
    if not payload.raw_log and not payload.log_entries:
        raise HTTPException(
            status_code=422,
            detail="raw_log 또는 log_entries 중 하나는 필수입니다.",
        )
