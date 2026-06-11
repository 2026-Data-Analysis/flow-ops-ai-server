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

import concurrent.futures
import logging
import time
import uuid

from langgraph.graph.state import CompiledStateGraph

from app.agents.incident.state import initial_state as incident_initial_state
from app.agents.orchestrator.state import OrchestratorAgentState, OrchestratorError
from app.schemas.orchestrator import AgentResultItem as AgentCallResult
from app.agents.scenario.state import initial_state as scenario_initial_state
from app.core.logging import log_event
from app.schemas.scenario import ScenarioGenerationMode, ScenarioGenerationRequest
from app.schemas.testcase import TestCaseGenerationRequest

logger = logging.getLogger(__name__)


def make_dispatcher_node(
    testcase_graph: CompiledStateGraph,
    scenario_graph: CompiledStateGraph,
    incident_graph: CompiledStateGraph,
    api_management_graph: CompiledStateGraph,
    llm,
):
    def dispatcher_node(state: OrchestratorAgentState) -> dict:
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

        total = len(intent_plan)
        logger.info(f"[dispatcher] 총 {total}개 Agent 실행 예정: "
                    f"{[i['agent'] for i in intent_plan]}")

        for idx, intent in enumerate(intent_plan, start=1):
            agent_type = intent["agent"]
            dispatched.append(agent_type)

            # ✅ Agent 호출 시작
            logger.info(f"[dispatcher] ({idx}/{total}) {agent_type} Agent 호출 시작"
                        f" — 이유: {intent.get('reason', '')}")

            start = time.perf_counter()
            try:
                if agent_type == "testcase":
                    result = _run_testcase(testcase_graph, llm, project_id, context, intent, state)
                elif agent_type == "scenario":
                    result = _run_scenario(scenario_graph, project_id, context, intent)
                elif agent_type == "incident":
                    result = _run_incident(incident_graph, project_id, context, intent)
                elif agent_type == "application":
                    result = _run_application(state, llm)
                elif agent_type == "environment":
                    result = _run_environment(state, llm)
                elif agent_type == "api_management":
                    result = _run_api_management(api_management_graph, state)
                elif agent_type == "general":
                    result = _run_general(state, llm)
                else:
                    result = AgentCallResult(
                        agent_type=agent_type,
                        success=False,
                        data=None,
                        error_message=f"알 수 없는 Agent 타입: {agent_type}",
                    )

                elapsed = (time.perf_counter() - start) * 1000

                # ✅ Agent 호출 결과
                if result.success:
                    logger.info(f"[dispatcher] ({idx}/{total}) {agent_type} Agent 성공 "
                                f"({elapsed:.0f}ms) — {_result_summary(agent_type, result)}")
                else:
                    logger.warning(f"[dispatcher] ({idx}/{total}) {agent_type} Agent 실패 "
                                   f"({elapsed:.0f}ms) — {result.error_message}")

            except Exception as e:
                elapsed = (time.perf_counter() - start) * 1000
                logger.error(f"[dispatcher] ({idx}/{total}) {agent_type} Agent 예외 발생 "
                             f"({elapsed:.0f}ms) — {e}")
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

        success_count = sum(1 for r in results if r.success)
        logger.info(f"[dispatcher] 전체 실행 완료 — 성공: {success_count}/{total}")

        return {
            "dispatched_agents": dispatched,
            "agent_results": results,
            "errors": errors,
        }

    return dispatcher_node


def _result_summary(agent_type: str, result: AgentCallResult) -> str:
    """Agent 결과 한 줄 요약."""
    data = result.data or {}
    if agent_type == "testcase":
        return f"{len(data.get('drafts', []))}개 테스트 케이스 생성"
    if agent_type == "scenario":
        return f"{len(data.get('scenarios', []))}개 시나리오 생성"
    if agent_type == "incident":
        causes = data.get("root_causes", [])
        return f"원인 후보 {len(causes)}건 도출"
    if agent_type in ("application", "environment", "api_management"):
        return f"status={data.get('status')} / {str(data.get('userMessage', ''))[:40]}"
    if agent_type == "general":
        return f"답변 {len(data.get('answer', ''))}자"
    return "완료"


# ---------------------------------------------------------------------------
# Agent별 호출 헬퍼 (로그 추가)
# ---------------------------------------------------------------------------

def _run_testcase_in_new_loop(request, graph, llm):
    import asyncio
    import traceback
    from app.agents.testcase.graph import run_testcase_agent
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(run_testcase_agent(request, graph, llm))
    except Exception as e:
        logger.error(f"[testcase_loop] 예외 발생: {e}")
        logger.error(f"[testcase_loop] 상세 traceback:\n{traceback.format_exc()}")
        raise
    finally:
        loop.close()


def _run_testcase(graph, llm, project_id: str, context: dict, intent: dict, state: OrchestratorAgentState) -> AgentCallResult:
    user_prompt = state.get("user_prompt", intent.get("reason", ""))

    # ── api_inventory가 있으면 바로 필터링 ───────────────────────────────
    api_inventory = context.get("api_inventory")
    if api_inventory:
        logger.info("[testcase] api_inventory에서 관련 API 추출 시작")
        apis = _filter_similar_apis(
            api_list=api_inventory.get("endpoints", []),
            user_prompt=user_prompt,
            llm=llm,
        )
        existing_test_cases = []
    else:
        api_server_url = context.get("api_server_url")
        if not api_server_url:
            return AgentCallResult(
                agent_type="testcase", success=False, data=None,
                error_message="testcase Agent 실행에 api_inventory 또는 api_server_url이 필요합니다.",
            )
        apis, existing_test_cases = _fetch_similar_apis_from_server(  
            api_server_url=api_server_url,
            project_id=project_id,
            user_prompt=user_prompt,
            llm=llm,
        )

    if not apis:
        return AgentCallResult(
            agent_type="testcase", success=False, data=None,
            error_message="관련 API를 찾지 못했습니다. 더 구체적으로 요청해주세요.",
        )

    logger.info(f"[testcase] {len(apis)}개 API 선택됨, 기존 testcase {len(existing_test_cases)}개 참조")
    return _generate_testcase(graph, llm, project_id, context, apis, existing_test_cases)


def _run_scenario(graph, project_id: str, context: dict, intent: dict) -> AgentCallResult:
    from app.schemas.api_spec import APIInventory

    api_inventory_dict = context.get("api_inventory")
    if not api_inventory_dict:
        return AgentCallResult(
            agent_type="scenario", success=False, data=None,
            error_message="scenario Agent 실행에 api_inventory가 필요합니다.",
        )

    try:
        inventory = APIInventory.model_validate(api_inventory_dict)
    except Exception as e:
        return AgentCallResult(
            agent_type="scenario", success=False, data=None,
            error_message=f"api_inventory 파싱 실패: {e}",
        )

    user_intent = intent.get("user_intent") or context.get("user_intent") or intent.get("reason", "")
    logger.info(f"[scenario] 시나리오 생성 시작 — intent: {user_intent[:60]}")

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
        logger.warning(f"[scenario] 시나리오 생성 실패: {errors[0]['message'] if errors else '알 수 없는 오류'}")
        return AgentCallResult(
            agent_type="scenario", success=False, data=None,
            error_message=errors[0]["message"] if errors else "시나리오 생성 실패",
        )

    used_endpoints = list({st.endpoint_id for s in final_scenarios for st in s.steps})
    logger.info(f"[scenario] 생성 완료 → {len(final_scenarios)}개 시나리오, "
                f"사용 API {len(used_endpoints)}개")

    return AgentCallResult(
        agent_type="scenario",
        success=True,
        data={
            "scenarios": [s.model_dump() for s in final_scenarios],
            "used_endpoint_ids": used_endpoints,
        },
        error_message=None,
        action={
            "type": "confirm_save",
            "label": "시나리오 저장",
            "description": f"{len(final_scenarios)}개 시나리오를 저장하시겠습니까?",
            "endpoint": "/api/v1/scenarios",
            "method": "POST",
            "payload": {
                "projectId": project_id,
                "scenarios": [s.model_dump() for s in final_scenarios],
            },
        },
    )


def _run_incident(graph, project_id: str, context: dict, intent: dict) -> AgentCallResult:
    from app.schemas.incident import IncidentAnalysisRequest

    raw_log = context.get("raw_log")
    if not raw_log and not context.get("log_entries"):
        return AgentCallResult(
            agent_type="incident", success=False, data=None,
            error_message="incident Agent 실행에 raw_log 또는 log_entries가 필요합니다.",
        )

    logger.info(f"[incident] 로그 분석 시작 — service: {context.get('service_name', project_id)}")

    request = IncidentAnalysisRequest(
        project_id=project_id,
        service_name=context.get("service_name", project_id),
        occurred_at=context.get("occurred_at"),
        raw_log=raw_log,
        log_entries=None,
    )

    trace_id = f"trace_{uuid.uuid4().hex[:12]}"
    init = incident_initial_state(request, trace_id=trace_id)
    final = graph.invoke(init)

    internal_report = final.get("internal_report")
    if not internal_report:
        errors = final.get("errors", [])
        logger.warning(f"[incident] 분석 실패: {errors[0]['message'] if errors else '알 수 없는 오류'}")
        return AgentCallResult(
            agent_type="incident", success=False, data=None,
            error_message=errors[0]["message"] if errors else "장애 분석 실패",
        )

    causes = final.get("root_cause_candidates", [])
    logger.info(f"[incident] 분석 완료 → 원인 후보 {len(causes)}건 도출")

    return AgentCallResult(
        agent_type="incident",
        success=True,
        data={
            "root_causes": causes,
            "internal_report": internal_report,
            "external_notice": final.get("external_notice", ""),
        },
        error_message=None,
    )


def _run_general(state: OrchestratorAgentState, llm) -> AgentCallResult:
    from app.agents.general import ask

    user_prompt = state.get("user_prompt", "")
    logger.info("[general] 일반 질문 답변 시작")
    try:
        answer = ask(user_prompt, llm)
        logger.info(f"[general] 답변 완료 → {len(answer)}자")
        return AgentCallResult(
            agent_type="general", success=True,
            data={"answer": answer}, error_message=None,
        )
    except Exception as e:
        logger.error(f"[general] 답변 실패: {e}")
        return AgentCallResult(
            agent_type="general", success=False, data=None, error_message=str(e),
        )


def _run_application(state: OrchestratorAgentState, llm) -> AgentCallResult:
    from app.agents.application import handle
    from app.schemas.chat import ChatRequest

    logger.info("[application] Application 관리 요청 처리 시작")
    request = ChatRequest(
        message=state.get("user_prompt", ""),
        context=state.get("context", {}),
        formSubmission=state.get("context", {}).get("formSubmission"),
    )
    try:
        response = handle(request, llm)
        logger.info(f"[application] 처리 완료 → intent={response.intent}, status={response.status}")
        return AgentCallResult(
            agent_type="application", success=True,
            data=response.model_dump(), error_message=None,
        )
    except Exception as e:
        logger.error(f"[application] 처리 실패: {e}")
        return AgentCallResult(
            agent_type="application", success=False, data=None, error_message=str(e),
        )


def _run_environment(state: OrchestratorAgentState, llm) -> AgentCallResult:
    from app.agents.environment import handle
    from app.schemas.chat import ChatRequest

    logger.info("[environment] Environment 관리 요청 처리 시작")
    request = ChatRequest(
        message=state.get("user_prompt", ""),
        context=state.get("context", {}),
        formSubmission=state.get("context", {}).get("formSubmission"),
    )
    try:
        response = handle(request, llm)
        logger.info(f"[environment] 처리 완료 → intent={response.intent}, status={response.status}")
        return AgentCallResult(
            agent_type="environment", success=True,
            data=response.model_dump(), error_message=None,
        )
    except Exception as e:
        logger.error(f"[environment] 처리 실패: {e}")
        return AgentCallResult(
            agent_type="environment", success=False, data=None, error_message=str(e),
        )


def _run_api_management(graph, state: OrchestratorAgentState) -> AgentCallResult:
    from app.agents.api_management.state import initial_state as api_mgmt_initial_state

    logger.info(f"[api_management] API 조회 시작 — "
                f"server={state.get('context', {}).get('api_server_url')}")

    trace_id = f"trace_{uuid.uuid4().hex[:12]}"
    init = api_mgmt_initial_state(
        message=state.get("user_prompt", ""),
        context=state.get("context", {}),
        trace_id=trace_id,
    )
    final = graph.invoke(init)

    user_message = final.get("user_message")
    if not user_message:
        errors = final.get("errors", [])
        logger.warning(f"[api_management] 조회 실패: {errors[0]['message'] if errors else '알 수 없는 오류'}")
        return AgentCallResult(
            agent_type="api_management", success=False, data=None,
            error_message=errors[0]["message"] if errors else "API 조회 실패",
        )

    logger.info(f"[api_management] 조회 완료 → status={final.get('status')}, "
                f"intent={final.get('intent')}")

    return AgentCallResult(
        agent_type="api_management",
        success=True,
        data={
            "intent": final.get("intent"),
            "confidence": final.get("confidence"),
            "status": final.get("status"),
            "target": final.get("target"),
            "action": final.get("action"),
            "userMessage": user_message,
        },
        error_message=None,
    )

def _fetch_similar_apis_from_server(
    api_server_url: str,
    project_id: str | None,
    user_prompt: str,
    llm,
) -> tuple[list[dict], list[dict]]:
    import httpx

    params = {"projectId": project_id}

    try:
        response = httpx.get(
            f"{api_server_url}/ai/agents/api-inventories",
            params=params,
            timeout=60.0,
        )
        response.raise_for_status()
        raw = response.json()

        data = raw.get("data", {})
        api_list = data.get("apis", [])
        test_cases = data.get("testCases", [])

        logger.info(f"[testcase] 서버에서 API {len(api_list)}개, 기존 testcase {len(test_cases)}개 조회됨")

        selected_apis = _filter_similar_apis(api_list, user_prompt, llm)
        return selected_apis, test_cases

    except Exception as e:
        logger.error(f"[testcase] 서버 API 조회 실패: {e}")
        return [], []


def _filter_similar_apis(api_list: list[dict], user_prompt: str, llm) -> list[dict]:
    if not api_list:
        return []
    if len(api_list) <= 5:
        return api_list

    from pydantic import BaseModel

    class _FilterOutput(BaseModel):
        selected_indices: list[int]

    api_summary = "\n".join(
        f"{i}. {ep.get('method', 'GET')} "
        f"{ep.get('path') or ep.get('endpointPath', '')} "
        f"— {ep.get('domainTag', '')} {ep.get('operationId', '')}"
        for i, ep in enumerate(api_list)
    )

    try:
        raw_output, _ = llm.generate_structured(
            system="사용자 요청과 가장 관련성 높은 API를 최대 5개 선택하세요. selected_indices에 인덱스 번호를 반환하세요.",
            user=f"사용자 요청: {user_prompt}\n\nAPI 목록:\n{api_summary}",
            output_schema=_FilterOutput.model_json_schema(),
            output_name="emit_selected_apis",
            output_description="관련성 높은 API 인덱스 선택",
            max_tokens=200,
            temperature=0.0,
        )
        parsed = _FilterOutput.model_validate(raw_output)
        selected = [api_list[i] for i in parsed.selected_indices if i < len(api_list)]
        logger.info(f"[testcase] LLM이 {len(selected)}개 API 선택: "
                    f"{[api_list[i].get('path') or api_list[i].get('endpointPath') for i in parsed.selected_indices if i < len(api_list)]}")
        return selected
    except Exception as e:
        logger.warning(f"[testcase] API 유사도 필터링 실패, 상위 5개 반환: {e}")
        return api_list[:5]


def _generate_testcase(
    graph, llm, project_id: str, context: dict, apis: list, existing_test_cases: list = []
) -> AgentCallResult:
    from datetime import datetime, timezone
    from app.schemas.testcase import (
        ApiSpec, EnvironmentInfo, GenerationContext,
        ProjectInfo, RequestMetadata, ExistingTestCase, DraftType,
    )

    # ✅ 기존 testcase 변환 — 중복 방지용
    converted_existing = []
    for tc in existing_test_cases:
        try:
            converted_existing.append(ExistingTestCase(
                testCaseId=str(tc.get("testCaseId", "")),
                apiId=str(tc.get("apiId", "")),
                name=tc.get("name", ""),
                type=DraftType(tc.get("type", "HAPPY_PATH")),
                testLevel=tc.get("testLevel", "UNIT"),
                requestSpec=tc.get("requestSpec"),
                expectedSpec=tc.get("expectedSpec"),
                assertionSpec=tc.get("assertionSpec"),
            ))
        except Exception as e:
            logger.warning(f"[testcase] 기존 testcase 변환 실패 (무시): {e}")
            continue

    all_drafts = []
    gen_id = f"gen_{uuid.uuid4().hex[:8]}"

    # ✅ API마다 개별 호출
    for ep in apis:
        raw_path = ep.get("path") or ep.get("endpointPath", "/")
        safe_path = raw_path.replace("{", "{{").replace("}", "}}")

        # request_body_schema, response_schema 변환
        request_schema = ep.get("request_body_schema") or ep.get("requestSchema")
        response_schema = ep.get("response_schema") or ep.get("responseSchema")

        single_api = ApiSpec(
            apiId=str(ep.get("apiId") or ep.get("id", "")),
            method=ep.get("method", "GET"),
            path=safe_path,
            domainTag=ep.get("domainTag"),
            request_body_schema=request_schema,
            response_schema=response_schema,
            authRequired=ep.get("authRequired", False),
            deprecated=ep.get("deprecated", False),
        )

        request = TestCaseGenerationRequest(
            agent="orchestrator",
            requestId=f"orch_{uuid.uuid4().hex[:8]}",
            requestedBy="orchestrator",
            project=ProjectInfo(
                projectId=str(project_id),
                appId=str(project_id),
                appName=str(project_id),
            ),
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
                generationId=gen_id,
                mode="STANDARD",
                testLevel="UNIT",
                currentCoverage=0.0,
                targetCoverage=80.0,
                contextSummary=None,
                userInstruction=None,
                validIdentifiers=None,
            ),
            apis=[single_api],              # ✅ API 1개씩
            existingTestCases=converted_existing,
            failureContext=None,
        )

        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(_run_testcase_in_new_loop, request, graph, llm)
                response = future.result(timeout=120)

            logger.info(f"[testcase] API {single_api.apiId} 완료 → "
                        f"{len(response.drafts)}개 테스트 케이스 생성")
            all_drafts.extend(response.drafts)

        except Exception as e:
            import traceback
            logger.error(f"[testcase] API {single_api.apiId} 생성 실패: {e}")
            logger.error(f"[testcase] 상세:\n{traceback.format_exc()}")
            continue  # ✅ 한 API 실패해도 나머지 계속 진행

    if not all_drafts:
        return AgentCallResult(
            agent_type="testcase",
            success=False,
            data=None,
            error_message="테스트 케이스 생성에 실패했습니다.",
        )

    logger.info(f"[testcase] 전체 완료 → 총 {len(all_drafts)}개 테스트 케이스 생성 "
                f"(API {len(apis)}개)")

    return AgentCallResult(
        agent_type="testcase",
        success=True,
        data={"drafts": [d.model_dump() for d in all_drafts]},
        error_message=None,
        action={
            "type": "confirm_save",
            "label": "테스트 케이스 저장",
            "description": f"{len(all_drafts)}개 테스트 케이스를 저장하시겠습니까?",
            "endpoint": "/api/v1/test-cases",
            "method": "POST",
            "payload": {
                "projectId": project_id,
                "generationId": gen_id,
                "drafts": [d.model_dump() for d in all_drafts],
            },
        },
    )