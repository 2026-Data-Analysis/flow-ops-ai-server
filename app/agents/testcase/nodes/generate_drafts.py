import asyncio
import logging
from typing import Any

from pydantic import BaseModel, Field

from app.agents.testcase.state import TestCaseAgentState
from app.llm.prompts.testcase_generation import SYSTEM_PROMPT, build_generation_prompt

logger = logging.getLogger(__name__)


class _RawDraft(BaseModel):
    title: str
    description: str
    type: str
    userRole: str | None = None
    stateCondition: str | None = None
    dataVariant: str | None = None
    requestSpec: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Exact values to send in the request. Include: "
            "method (GET/POST/...), pathParams (e.g. {userId: 1}), "
            "queryParams (e.g. {page: 1, size: 10}), "
            "body (request body object with concrete example values)."
        ),
    )
    expectedSpec: dict[str, Any] | None = Field(
        default=None,
        description=(
            "What the response should look like. Include: "
            "statusCode (e.g. 200, 400, 401, 404, 500), "
            "body (expected response body structure with example values or key fields), "
            "errorMessage (expected error message string for failure cases)."
        ),
    )
    assertionSpec: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Specific assertions to verify after the request. Include: "
            "statusCode (exact expected HTTP status code as int), "
            "bodyContains (list of keys or substrings that must appear in the response body), "
            "bodyEquals (exact field-value pairs to match), "
            "headerContains (response headers to check, e.g. {Content-Type: application/json})."
        ),
    )


class _DraftListOutput(BaseModel):
    drafts: list[_RawDraft]


async def generate_drafts(state: TestCaseAgentState) -> dict:
    """LLM Tool Use로 각 API별 테스트 케이스 초안을 생성한다."""
    if state.get("error"):
        return state

    llm = state["llm"]
    req = state["request"]
    ctx = req.generationContext
    env = req.environment
    raw_drafts: list[dict[str, Any]] = []

    for api in req.apis:
        prompt = build_generation_prompt(
            api_id=api.apiId,
            method=api.method,
            path=api.path,
            auth_required=api.authRequired,
            request_schema=api.requestSchema,
            response_schema=api.responseSchema,
            app_name=req.project.appName,
            env_name=env.name,
            base_url=env.baseUrl,
            context_summary=ctx.contextSummary,
        )

        try:
            result, _ = await asyncio.to_thread(
                llm.generate_structured,
                system=SYSTEM_PROMPT,
                user=prompt,
                output_schema=_DraftListOutput.model_json_schema(),
                output_name="generate_test_drafts",
                output_description=(
                    "Generate API test case drafts covering normal, "
                    "exception, and boundary scenarios"
                ),
            )
            output = _DraftListOutput.model_validate(result)
            for draft in output.drafts:
                raw_drafts.append({**draft.model_dump(), "apiId": api.apiId})
        except Exception as exc:
            logger.warning("LLM generation failed for api %s: %s", api.apiId, exc)

    return {**state, "raw_drafts": raw_drafts}
