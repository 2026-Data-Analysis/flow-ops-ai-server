"""시나리오 Agent의 HTTP 인터페이스.

엔드포인트:
- POST /v1/agents/scenario/generate
  자연어 또는 추천 모드로 시나리오 생성.

핸들러 책임은 얇게:
1. 요청을 받아 그래프 입력 State로 변환
2. 그래프 invoke
3. 결과 State에서 final_scenarios 꺼내 AgentResponse로 포장

[1단계 변경]
used_endpoint_ids 집계 시 step.endpoint_id -> step.apiId.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from langgraph.graph.state import CompiledStateGraph

from app.agents.scenario.state import initial_state
from app.api.deps import get_scenario_graph
from app.schemas import (
    AgentResponse,
    Scenario,
    ScenarioGenerationMode,
    ScenarioGenerationRequest,
    ScenarioGenerationResult,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/agents/scenario", tags=["scenario"])


@router.post(
    "/generate",
    response_model=AgentResponse[ScenarioGenerationResult],
    summary="시나리오 테스트 생성",
    description=(
        "자연어 입력 또는 추천 모드로 End-to-End 시나리오를 생성합니다. "
        "응답의 success=true여도 errors 배열에 부분 검증 실패가 포함될 수 있습니다."
    ),
)
def generate_scenarios(
    payload: ScenarioGenerationRequest,
    graph: CompiledStateGraph = Depends(get_scenario_graph),
) -> AgentResponse[ScenarioGenerationResult]:
    # 요청 자체에 대한 사전 검증 (Pydantic이 못 잡는 비즈니스 룰)
    _validate_request(payload)

    trace_id = f"trace_{uuid.uuid4().hex[:12]}"
    logger.info(
        "scenario.generate start project=%s mode=%s trace=%s",
        payload.project_id, payload.mode.value, trace_id,
    )

    init = initial_state(payload, trace_id=trace_id)

    try:
        final = graph.invoke(init)
    except Exception as e:
        # 그래프 자체가 터지는 경우는 진짜 서버 에러
        logger.exception("scenario graph invocation crashed trace=%s", trace_id)
        raise HTTPException(
            status_code=500,
            detail=f"scenario agent crashed: {e}",
        ) from e

    final_scenarios: list[Scenario] = final.get("final_scenarios", [])
    errors = final.get("errors", [])

    # 시나리오가 하나도 안 만들어졌고 에러만 잔뜩이면 success=false
    if not final_scenarios:
        first_err = errors[0] if errors else None
        logger.warning(
            "scenario.generate no result trace=%s errors=%d",
            trace_id, len(errors),
        )
        return AgentResponse[ScenarioGenerationResult](
            success=False,
            error_code=(first_err["code"] if first_err else "NO_SCENARIOS_GENERATED"),
            error_message=(
                first_err["message"] if first_err
                else "조건에 맞는 시나리오를 생성하지 못했습니다."
            ),
            trace_id=trace_id,
        )

    # 사용된 apiId 집계 (중복 제거, 등장 순서 유지)
    used: list[str] = []
    seen: set[str] = set()
    for sc in final_scenarios:
        for st in sc.steps:
            if st.apiId not in seen:
                seen.add(st.apiId)
                used.append(st.apiId)

    result = ScenarioGenerationResult(
        scenarios=final_scenarios,
        used_endpoint_ids=used,
    )
    logger.info(
        "scenario.generate done trace=%s scenarios=%d errors=%d",
        trace_id, len(final_scenarios), len(errors),
    )
    return AgentResponse[ScenarioGenerationResult](
        success=True,
        data=result,
        # 부분 실패가 있었다면 error_message에 요약만 첨부
        error_message=(
            f"{len(errors)}건의 부분 검증 실패가 있었습니다." if errors else None
        ),
        trace_id=trace_id,
    )


def _validate_request(payload: ScenarioGenerationRequest) -> None:
    """Pydantic이 자동으로 못 잡는 mode-conditional 검증."""
    if payload.mode == ScenarioGenerationMode.NATURAL_LANGUAGE and not payload.user_intent:
        raise HTTPException(
            status_code=422,
            detail="NATURAL_LANGUAGE 모드에서는 user_intent가 필수입니다.",
        )
    if not payload.api_inventory.endpoints:
        raise HTTPException(
            status_code=422,
            detail="api_inventory.endpoints가 비어있어 시나리오를 생성할 수 없습니다.",
        )