"""Reporter 노드.

역할:
- analyzer의 root_cause_candidates를 받아 두 종류의 보고서 생성
  (a) internal_report: 개발팀용 - 로그 요약 + 원인 분석 + 수정 방향
  (b) external_notice: 사용자 공지용 - 기술 용어 없는 친화적 안내

LLM 1회 호출로 두 문서를 동시에 생성 (비용 최소화).
"""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field, ValidationError

from app.agents.incident.state import IncidentAgentError, IncidentAgentState
from app.llm import LLMClient
from app.llm.prompts.incident_reporter import SYSTEM_PROMPT, build_user_prompt

logger = logging.getLogger(__name__)


class _ReporterOutput(BaseModel):
    internal_report: str = Field(description="개발팀 내부 공유용 로그 요약 및 원인 분석")
    external_notice: str = Field(description="외부 공지용 사용자 친화적 안내 문구")


def make_reporter_node(llm: LLMClient):
    def reporter_node(state: IncidentAgentState) -> dict:
        # 앞 단계 에러 → 통과
        errors = state.get("errors", [])
        if any(e["node"] in ("log_parser", "analyzer") for e in errors):
            return {}

        candidates = state.get("root_cause_candidates", [])
        if not candidates:
            return {
                "errors": [IncidentAgentError(
                    node="reporter",
                    code="NO_CANDIDATES",
                    message="원인 후보가 없어 보고서를 생성할 수 없습니다.",
                )]
            }

        req = state["request"]
        user_prompt = build_user_prompt(
            candidates=candidates,
            service_name=req.service_name,
            occurred_at=req.occurred_at,
        )

        try:
            raw_output, usage = llm.generate_structured(
                system=SYSTEM_PROMPT,
                user=user_prompt,
                output_schema=_ReporterOutput.model_json_schema(),
                output_name="emit_incident_reports",
                output_description="내부용 분석 보고서와 외부 공지문",
                max_tokens=2000,
                temperature=0.2,
            )
        except Exception as e:
            logger.exception("reporter LLM call failed")
            return {
                "errors": [IncidentAgentError(
                    node="reporter",
                    code="LLM_CALL_FAILED",
                    message=str(e),
                )]
            }

        try:
            parsed = _ReporterOutput.model_validate(raw_output)
        except ValidationError as e:
            return {
                "errors": [IncidentAgentError(
                    node="reporter",
                    code="OUTPUT_VALIDATION_FAILED",
                    message=str(e),
                )],
                "token_usages": [usage],
            }

        return {
            "internal_report": parsed.internal_report,
            "external_notice": parsed.external_notice,
            "token_usages": [usage],
        }

    return reporter_node
