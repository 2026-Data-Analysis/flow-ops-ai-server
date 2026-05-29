"""Dispatcher 노드.

역할:
- intent_plan에 따라 각 Agent 그래프를 순서대로 invoke
- 각 결과를 agent_results에 누적
- 어떤 Agent가 실행됐는지 dispatched_agents에 기록

설계 결정:
- 각 Agent의 CompiledStateGraph를 주입받음 (deps에서 가져옴)
- 한 Agent 실패가 전체를 중단시키지 않음 (에러 기록 후 다음 Agent 진행)
- context에서 각 Agent 입력을 동적으로 조립
"""

from __future__ import annotations

import logging
import uuid
import concurrent.futures

from langgraph.graph.state import CompiledStateGraph

from app.agents.incident.state import initial_state as incident_initial_state
from app.agents.orchestrator.state import AgentCallResult, OrchestratorAgentState, OrchestratorError
from app.agents.scenario.state import initial_state as scenario_initial_state
from app.schemas.incident import IncidentAnalysisRequest
from app.schemas.scenario import (
    ScenarioGenerationMode,
    ScenarioGenerationRequest,
)
from app.schemas.testcase import TestCaseGenerationRequest

logger = logging.getLogger(__name__)


def make_dispatcher_node(
    testcase_graph: CompiledStateGraph,
    scenario_graph: CompiledStateGraph,
    incident_graph: CompiledStateGraph,
    llm,  # TestCase agent는 llm을 state에 넣음
):
    def dispatcher_node(state: OrchestratorAgentState) -> dict:
        # 앞 단계 에러 → 통과
        if any(e["node"] == "intent_classifier" for e in state.get("errors", [])):
            return {}

        intent_plan = state.get("intent_plan", [])
        if not intent_plan:
            return {}

        context = state.get("context", {})
        project_id = state.get("project_id", "")
        results: list[AgentCallResult] = []
        dispatched: list[str] = []
        errors: list[OrchestratorError] = []

        for intent in intent_plan:
            agent_type = intent["agent"]
            dispatched.append(agent_type)

            try:
                if agent_type == "testcase":
                    result = _run_testcase(testcase_graph, llm, project_id, context, intent)
                elif agent_type == "scenario":
                    result = _run_scenario(scenario_graph, project_id, context, intent)
                elif agent_type == "incident":
                    result = _run_incident(incident_graph, project_id, context, intent)
                else:
                    result = AgentCallResult(
                        agent_type=agent_type,
                        success=False,
                        data=None,
                        error_message=f"알 수 없는 Agent 타입: {agent_type}",
                    )
            except Exception as e:
                logger.exception("dispatcher: agent %s invocation failed", agent_type)
                result = AgentCallResult(
                    agent_type=agent_type,
                    success=False,
                    data=None,
                    error_message=str(e),
                )
                errors.append(OrchestratorError(
                    node="dispatcher",
                    code=f"{agent_type.upper()}_AGENT_FAILED",
                    message=str(e),
                ))

            results.append(result)

        return {
            "dispatched_agents": dispatched,
            "agent_results": results,
            "errors": errors,
        }

    return dispatcher_node


# ---------------------------------------------------------------------------
# Agent별 호출 헬퍼
# ---------------------------------------------------------------------------

def _run_testcase_in_new_loop(request, graph, llm):
    """별도 스레드에서 새 이벤트 루프를 만들어 async testcase agent 실행."""
    import asyncio
    from app.agents.testcase.graph import run_testcase_agent

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(run_testcase_agent(request, graph, llm))
    finally:
        loop.close()
        
def _run_testcase(graph, llm, project_id: str, context: dict, intent: dict) -> AgentCallResult:
    """TestCase Agent 호출."""
    import asyncio

    from app.agents.testcase.graph import run_testcase_agent_sync 
    from app.schemas.testcase import (
        ApiSpec,
        EnvironmentInfo,
        GenerationContext,
        ProjectInfo,
        RequestMetadata,
    )
    from datetime import datetime, timezone

    api_inventory = context.get("api_inventory")
    if not api_inventory:
        return AgentCallResult(
            agent_type="testcase",
            success=False,
            data=None,
            error_message="testcase Agent 실행에 api_inventory가 필요합니다.",
        )

    # APIInventory → ApiSpec 변환
    apis = []
    for ep in api_inventory.get("endpoints", []):
        apis.append(ApiSpec(
            apiId=ep.get("endpoint_id", ""),
            method=ep.get("method", "GET"),
            path=ep.get("path", "/"),
            requestSchema=ep.get("request_body_schema"),
            responseSchema=ep.get("response_schema"),
            authRequired=bool(ep.get("auth") and ep["auth"].get("type", "none") != "none"),
        ))

    request = TestCaseGenerationRequest(
        agent="orchestrator",
        requestId=f"orch_{uuid.uuid4().hex[:8]}",
        requestedBy="orchestrator",
        project=ProjectInfo(projectId=project_id, appId=project_id, appName=project_id),
        environment=EnvironmentInfo(
            environmentId="default",
            name=context.get("env_name", "default"),
            baseUrl=context.get("base_url", "http://localhost"),
            defaultTestLevel="UNIT",
        ),
        metadata=RequestMetadata(
            language="ko",
            createdAt=datetime.now(timezone.utc).isoformat(),
            source="orchestrator",
        ),
        generationContext=GenerationContext(
            generationId=f"gen_{uuid.uuid4().hex[:8]}",
            mode="STANDARD",
            testLevel="UNIT",
            currentCoverage=0.0,
            targetCoverage=80.0,
        ),
        apis=apis,
    )

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_run_testcase_in_new_loop, request, graph, llm)
            response = future.result(timeout=60)
        return AgentCallResult(
            agent_type="testcase",
            success=True,
            data=response.model_dump(),
            error_message=None,
        )
    except Exception as e:
        return AgentCallResult(
            agent_type="testcase",
            success=False,
            data=None,
            error_message=str(e),
        )


def _run_scenario(graph, project_id: str, context: dict, intent: dict) -> AgentCallResult:
    """Scenario Agent 호출."""
    from app.schemas.api_spec import APIInventory

    api_inventory_dict = context.get("api_inventory")
    if not api_inventory_dict:
        return AgentCallResult(
            agent_type="scenario",
            success=False,
            data=None,
            error_message="scenario Agent 실행에 api_inventory가 필요합니다.",
        )

    try:
        inventory = APIInventory.model_validate(api_inventory_dict)
    except Exception as e:
        return AgentCallResult(
            agent_type="scenario",
            success=False,
            data=None,
            error_message=f"api_inventory 파싱 실패: {e}",
        )

    user_intent = intent.get("user_intent") or context.get("user_intent") or intent.get("reason", "")

    request = ScenarioGenerationRequest(
        project_id=project_id,
        mode=ScenarioGenerationMode.NATURAL_LANGUAGE,
        user_intent=user_intent,
        api_inventory=inventory,
    )

    trace_id = f"trace_{uuid.uuid4().hex[:12]}"
    init = scenario_initial_state(request, trace_id=trace_id)
    final = graph.invoke(init)

    final_scenarios = final.get("final_scenarios", [])
    errors = final.get("errors", [])

    if not final_scenarios:
        return AgentCallResult(
            agent_type="scenario",
            success=False,
            data=None,
            error_message=errors[0]["message"] if errors else "시나리오 생성 실패",
        )

    return AgentCallResult(
        agent_type="scenario",
        success=True,
        data={
            "scenarios": [s.model_dump() for s in final_scenarios],
            "used_endpoint_ids": list({
                st.endpoint_id
                for s in final_scenarios for st in s.steps
            }),
        },
        error_message=None,
    )


def _run_incident(graph, project_id: str, context: dict, intent: dict) -> AgentCallResult:
    """Incident Agent 호출."""
    from app.schemas.incident import IncidentAnalysisRequest

    raw_log = context.get("raw_log")
    log_entries_raw = context.get("log_entries")

    if not raw_log and not log_entries_raw:
        return AgentCallResult(
            agent_type="incident",
            success=False,
            data=None,
            error_message="incident Agent 실행에 raw_log 또는 log_entries가 필요합니다.",
        )

    request = IncidentAnalysisRequest(
        project_id=project_id,
        service_name=context.get("service_name", project_id),
        occurred_at=context.get("occurred_at"),
        raw_log=raw_log,
        log_entries=None,  # raw 우선
    )

    trace_id = f"trace_{uuid.uuid4().hex[:12]}"
    init = incident_initial_state(request, trace_id=trace_id)
    final = graph.invoke(init)

    internal_report = final.get("internal_report")
    if not internal_report:
        errors = final.get("errors", [])
        return AgentCallResult(
            agent_type="incident",
            success=False,
            data=None,
            error_message=errors[0]["message"] if errors else "장애 분석 실패",
        )

    return AgentCallResult(
        agent_type="incident",
        success=True,
        data={
            "root_causes": final.get("root_cause_candidates", []),
            "internal_report": internal_report,
            "external_notice": final.get("external_notice", ""),
        },
        error_message=None,
    )
