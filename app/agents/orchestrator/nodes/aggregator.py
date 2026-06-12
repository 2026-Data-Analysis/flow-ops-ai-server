"""Aggregator 노드.

역할:
- 여러 Agent 결과를 종합해 사용자가 읽기 좋은 자연어 요약 생성
- 어떤 Agent가 실행됐고 각각 어떤 결과를 냈는지 간결하게 정리

LLM을 쓰지 않고 규칙 기반으로 요약 (비용 절약 + 충분히 구조적).
"""

from __future__ import annotations

import logging

from app.agents.orchestrator.state import OrchestratorAgentState
from app.schemas.orchestrator import AgentResultItem as AgentCallResult

logger = logging.getLogger(__name__)

_AGENT_LABELS = {
    "testcase": "테스트 케이스 생성",
    "scenario": "시나리오(E2E) 테스트 생성",
    "incident": "장애 원인 분석",
    "general": "일반 질문 답변",
    "application": "Application 관리",
    "environment": "Environment 관리",
    "api_management": "API 조회",
}


def aggregator_node(state: OrchestratorAgentState) -> dict:
    results: list[AgentCallResult] = state.get("agent_results", [])
    errors = state.get("errors", [])

    if not results and not errors:
        logger.info("[aggregator] 실행된 Agent 없음")
        return {"summary": "실행된 Agent가 없습니다."}

    lines: list[str] = []
    for r in results:
        label = _AGENT_LABELS.get(r.agent_type, r.agent_type)
        if r.success:
            detail = _success_detail(r)
            lines.append(f"✅ [{label}] 완료 — {detail}")
        else:
            lines.append(f"❌ [{label}] 실패 — {r.error_message}")

    if errors:
        for e in errors:
            lines.append(f"⚠️ [{e['node']}] {e['code']}: {e['message']}")

    summary = "\n".join(lines) if lines else "처리 결과 없음"

    logger.info(f"[aggregator] 최종 요약 완료\n{summary}")

    return {"summary": summary}


def _success_detail(result: AgentCallResult) -> str:
    data = result.data or {}
    agent = result.agent_type

    if agent == "testcase":
        drafts = data.get("drafts", [])
        # API별 테스트 케이스 수 집계
        api_counts: dict = {}
        for d in drafts:
            api_id = d.get("apiId", "unknown")
            api_counts[api_id] = api_counts.get(api_id, 0) + 1
        api_summary = ", ".join(
            f"{api_id}({count}개)" for api_id, count in api_counts.items()
        )
        return (
            f"총 {len(drafts)}개 테스트 케이스 생성 "
            f"(API {len(api_counts)}개 대상 — {api_summary})"
        )

    if agent == "scenario":
        scenarios = data.get("scenarios", [])
        endpoints = data.get("used_endpoint_ids", [])
        step_counts = [len(s.get("steps", [])) for s in scenarios]
        avg_steps = sum(step_counts) / len(step_counts) if step_counts else 0
        return (
            f"총 {len(scenarios)}개 시나리오 생성 "
            f"(사용 API {len(endpoints)}개, 평균 {avg_steps:.1f}스텝)"
        )

    if agent == "incident":
        causes = data.get("root_causes", [])
        top = causes[0]["summary"] if causes else "원인 미상"
        severities = [c.get("severity", "") for c in causes]
        critical = severities.count("CRITICAL")
        high = severities.count("HIGH")
        return (
            f"원인 후보 {len(causes)}건 도출 "
            f"(CRITICAL {critical}건, HIGH {high}건) "
            f"— 주요 원인: {top[:40]}"
        )

    if agent in ("application", "environment", "api_management"):
        status = data.get("status", "")
        user_message = str(data.get("userMessage", ""))[:60]
        return f"{status} — {user_message}"

    if agent == "general":
        answer = data.get("answer", "")
        return answer[:60] + "..." if len(answer) > 60 else answer

    return "완료"