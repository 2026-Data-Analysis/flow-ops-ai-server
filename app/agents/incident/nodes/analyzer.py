"""Analyzer 노드.

역할:
- 정제된 로그 엔트리를 LLM에 넣어 원인 후보(RootCauseCandidate) 도출
- 실패한 테스트의 기대값/실제값 컨텍스트가 있으면 함께 분석
"""

from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from app.agents.incident.state import IncidentAgentError, IncidentAgentState, RootCauseCandidate
from app.llm import LLMClient
from app.llm.prompts.incident_analyzer import SYSTEM_PROMPT, build_user_prompt

logger = logging.getLogger(__name__)

_ALLOWED_SEVERITIES = {"CRITICAL", "HIGH", "MEDIUM", "LOW"}


# ---------------------------------------------------------------------------
# LLM 출력 스키마
# ---------------------------------------------------------------------------

class _Candidate(BaseModel):
    summary: str = Field(description="원인 한 줄 요약")
    evidence: list[str] = Field(description="근거 로그 라인 또는 메시지 (최대 5개)")
    severity: str = Field(description="CRITICAL / HIGH / MEDIUM / LOW")
    suggested_fix: str = Field(description="수정 방향 제안 (1~3문장)")


class _AnalyzerOutput(BaseModel):
    candidates: list[_Candidate]


# ---------------------------------------------------------------------------
# 노드 팩토리
# ---------------------------------------------------------------------------

def make_analyzer_node(llm: LLMClient):
    def analyzer_node(state: IncidentAgentState) -> dict:
        if state.get("errors"):
            # 앞 노드에서 이미 에러 → 통과
            return {}

        entries = state.get("parsed_log_entries", [])
        if not entries:
            return {
                "errors": [IncidentAgentError(
                    node="analyzer",
                    code="NO_PARSED_ENTRIES",
                    message="분석할 로그 엔트리가 없습니다.",
                )]
            }

        req = state["request"]
        user_prompt = build_user_prompt(
            log_entries=entries,
            failure_context=req.failure_context,
            service_name=req.service_name,
        )

        try:
            raw_output, usage = llm.generate_structured(
                system=SYSTEM_PROMPT,
                user=user_prompt,
                output_schema=_AnalyzerOutput.model_json_schema(),
                output_name="emit_root_causes",
                output_description="로그에서 도출한 장애 원인 후보 목록",
                max_tokens=2000,
                temperature=0.0,
            )
        except Exception as e:
            logger.exception("analyzer LLM call failed")
            return {
                "errors": [IncidentAgentError(
                    node="analyzer",
                    code="LLM_CALL_FAILED",
                    message=str(e),
                )]
            }

        try:
            parsed = _AnalyzerOutput.model_validate(raw_output)
        except ValidationError as e:
            logger.error("analyzer output validation failed: %s", e)
            return {
                "errors": [IncidentAgentError(
                    node="analyzer",
                    code="OUTPUT_VALIDATION_FAILED",
                    message=str(e),
                )],
                "token_usages": [usage],
            }

        candidates: list[RootCauseCandidate] = []
        for c in parsed.candidates:
            sev = c.severity.upper()
            if sev not in _ALLOWED_SEVERITIES:
                sev = "MEDIUM"
            candidates.append(RootCauseCandidate(
                summary=c.summary,
                evidence=c.evidence[:5],
                severity=sev,
                suggested_fix=c.suggested_fix,
            ))

        return {
            "root_cause_candidates": candidates,
            "token_usages": [usage],
        }

    return analyzer_node
