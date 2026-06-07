import httpx
import json
import logging
from app.agents.testcase.state import TestCaseAgentState
from app.schemas.testcase import ApiSpec

logger = logging.getLogger(__name__)


def _parse_schema(raw: str | None) -> dict | None:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        logger.debug("fetch_apis.schema_parse_failed raw=%s", raw[:80])
        return None


def _to_api_spec(item: dict) -> ApiSpec | None:
    try:
        return ApiSpec(
            apiId=str(item["id"]),
            method=item["method"],
            path=item["endpointPath"],
            domainTag=item.get("domainTag"),
            requestSchema=_parse_schema(item.get("requestSchema")),
            responseSchema=_parse_schema(item.get("responseSchema")),
            authRequired=item.get("authRequired", False),
        )
    except Exception as exc:
        logger.debug("fetch_apis.item_parse_failed item_id=%s error=%s", item.get("id"), exc)
        return None


def _select_relevant_apis(
    llm,
    apis: list[ApiSpec],
    user_instruction: str,
) -> list[ApiSpec]:
    """userInstruction 기반으로 관련 API만 LLM이 골라낸다."""
    from pydantic import BaseModel

    class SelectedApis(BaseModel):
        selected_ids: list[str]

    api_summary = "\n".join(
        f"- id={api.apiId} method={api.method} path={api.path} tag={api.domainTag}"
        for api in apis
    )
    user_prompt = (
        f"User instruction: {user_instruction}\n\n"
        f"Available APIs:\n{api_summary}\n\n"
        f"Select the apiIds most relevant to the user instruction."
    )

    try:
        result, _ = llm.generate_structured(
            system="You are an API selector. Given a user instruction and a list of APIs, return only the IDs of APIs relevant to the instruction. If unsure, include all.",
            user=user_prompt,
            output_schema=SelectedApis.model_json_schema(),
            output_name="select_apis",
            output_description="List of selected API IDs relevant to the user instruction",
        )
        selected_ids = set(result.get("selected_ids", []))
        filtered = [api for api in apis if api.apiId in selected_ids]
        logger.info("fetch_apis.filtered total=%d selected=%d", len(apis), len(filtered))
        return filtered if filtered else apis
    except Exception as exc:
        logger.warning("fetch_apis.select_failed error=%s", exc)
        return apis


async def fetch_apis(state: TestCaseAgentState) -> dict:
    """백엔드에서 전체 API 인벤토리를 조회해서 state에 주입한다."""
    if state.get("error"):
        return state

    req = state["request"]
    project_id = req.project.projectId
    base_url = req.environment.baseUrl

    # apis가 이미 있으면 조회 생략
    if req.apis:
        logger.info("fetch_apis.skipped reason=apis_already_provided count=%d", len(req.apis))
        return state

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{base_url}/projects/{project_id}/api-inventories",
                timeout=5.0,
            )
            response.raise_for_status()
            data = response.json()

            # ApiResponse<ApiInventoryListResponse> 래퍼 벗기기
            items = data.get("data", {}).get("items", [])
            apis = [spec for item in items if isinstance(item, dict) and (spec := _to_api_spec(item))]
            logger.info("fetch_apis.fetched count=%d", len(apis))

    except Exception as exc:
        logger.warning("fetch_apis.failed error=%s", exc)
        apis = []

    if not apis:
        return {**state, "error": "API 목록을 가져오지 못했습니다. baseUrl 또는 projectId를 확인해주세요."}

    user_instruction = req.generationContext.userInstruction
    if user_instruction:
        apis = _select_relevant_apis(state["llm"], apis, user_instruction)

    updated_request = req.model_copy(update={"apis": apis})
    return {**state, "request": updated_request}