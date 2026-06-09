"""Orchestrator Agent HTTP 인터페이스.

엔드포인트:
- POST /v1/agents/orchestrator/chat
  자연어 프롬프트를 받아 적절한 Agent(들)를 실행하고 결과 반환.
  응답에 dispatched_agents가 포함되어 서버가 어떤 Agent가 사용됐는지 파악 가능.
"""

from __future__ import annotations

import logging
import uuid
import json as _json

from fastapi import APIRouter, Depends, HTTPException
from langgraph.graph.state import CompiledStateGraph

from app.agents.orchestrator.state import initial_state
from app.api.deps import get_orchestrator_graph
from app.core.logging import log_event
from app.schemas import AgentResponse
from app.schemas.orchestrator import AgentResultItem, OrchestratorRequest, OrchestratorResult

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/agents/orchestrator", tags=["orchestrator"])


@router.post(
    "/chat",
    response_model=AgentResponse[OrchestratorResult],
    summary="자연어로 Agent 실행",
    description=(
        "자연어 프롬프트를 받아 적절한 Agent를 자동으로 선택·실행합니다. "
        "응답의 dispatched_agents 필드에서 어떤 Agent가 실행됐는지 확인할 수 있습니다."
    ),
)
def chat(
    payload: OrchestratorRequest,
    graph: CompiledStateGraph = Depends(get_orchestrator_graph),
) -> AgentResponse[OrchestratorResult]:
    _validate_request(payload)

    trace_id = f"trace_{uuid.uuid4().hex[:12]}"

    # ✅ 요청 수신 로그
    log_event(logger, "info", "orchestrator.REQUEST",
        trace_id=trace_id,
        project_id=payload.project_id,
        prompt=payload.user_prompt[:100],
        has_api_inventory=bool(payload.context.get("api_inventory")),
        has_log=bool(payload.context.get("raw_log") or payload.context.get("log_entries")),
    )

    init = initial_state(
        user_prompt=payload.user_prompt,
        project_id=payload.project_id,
        context=payload.context,
        trace_id=trace_id,
    )

    try:
        final = graph.invoke(init)
    except Exception as e:
        # ✅ 그래프 크래시 로그
        log_event(logger, "error", "orchestrator.CRASH",
            trace_id=trace_id,
            error=str(e),
        )
        raise HTTPException(status_code=500, detail=f"orchestrator agent crashed: {e}") from e

    errors = final.get("errors", [])
    dispatched = final.get("dispatched_agents", [])
    agent_results = final.get("agent_results", [])
    summary = final.get("summary", "")

    # intent_classifier 에러면 완전 실패
    classifier_errors = [e for e in errors if e["node"] == "intent_classifier"]
    if classifier_errors:
        # ✅ 분류 실패 로그
        log_event(logger, "warning", "orchestrator.CLASSIFIER_FAILED",
            trace_id=trace_id,
            code=classifier_errors[0]["code"],
            message=classifier_errors[0]["message"],
        )
        return AgentResponse[OrchestratorResult](
            success=False,
            error_code=classifier_errors[0]["code"],
            error_message=classifier_errors[0]["message"],
            trace_id=trace_id,
        )

    # 실행된 Agent가 하나도 없으면 실패
    if not dispatched:
        log_event(logger, "warning", "orchestrator.NO_AGENTS_DISPATCHED",
            trace_id=trace_id,
        )
        return AgentResponse[OrchestratorResult](
            success=False,
            error_code="NO_AGENTS_DISPATCHED",
            error_message="실행할 Agent를 결정하지 못했습니다. 요청을 더 구체적으로 작성해주세요.",
            trace_id=trace_id,
        )

    result = OrchestratorResult(
        dispatched_agents=dispatched,
        agent_results=agent_results,
        summary=summary,
    )
    all_failed = all(not r.success for r in agent_results) if agent_results else True

    # ✅ 최종 응답 로그
    log_event(logger, "info", "orchestrator.RESPONSE",
        trace_id=trace_id,
        dispatched=dispatched,
        success=not all_failed,
        total_agents=len(agent_results),
        success_count=sum(1 for r in agent_results if r.success),
        fail_count=sum(1 for r in agent_results if not r.success),
        error_count=len(errors),
    )

    return AgentResponse[OrchestratorResult](
        success=not all_failed,
        data=result,
        error_message=f"{len(errors)}건의 오류가 있었습니다." if errors else None,
        trace_id=trace_id,
    )


def _validate_request(payload: OrchestratorRequest) -> None:
    if not payload.user_prompt.strip():
        raise HTTPException(status_code=422, detail="user_prompt가 비어있습니다.")