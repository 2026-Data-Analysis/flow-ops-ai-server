import asyncio
import logging
import re
from typing import Any

from json_repair import repair_json

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


_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.DOTALL)


def _coerce_tool_result(result: dict[str, Any]) -> dict[str, Any]:
    """Guard against the model returning `drafts` as a JSON string instead of an array.

    Tool Use guarantees the outer object is a dict, but the model occasionally
    serialises the array value as a string (plain or markdown-fenced, possibly
    with minor syntax errors such as missing commas).  repair_json handles those
    cases before Pydantic validation.
    """
    drafts = result.get("drafts")
    if not isinstance(drafts, str):
        return result
    cleaned = _FENCE_RE.sub("", drafts).strip()
    parsed = repair_json(cleaned, return_objects=True)
    if not isinstance(parsed, list):
        raise ValueError(
            f"LLM returned drafts as a string that could not be coerced to a list "
            f"(got {type(parsed).__name__!r} after repair). Raw value: {cleaned[:120]!r}"
        )
    return {**result, "drafts": parsed}


async def generate_drafts(state: TestCaseAgentState) -> dict:
    """LLM Tool Use로 각 API별 테스트 케이스 초안을 생성한다."""
    if state.get("error"):
        return state

    llm = state["llm"]
    req = state["request"]
    ctx = req.generationContext
    env = req.environment
    raw_drafts: list[dict[str, Any]] = []

    logger.info(
        "generate_drafts.enter requestId=%s generationId=%s api_count=%d existing_count=%d",
        req.requestId,
        ctx.generationId,
        len(req.apis),
        len(req.existingTestCases),
    )

    for api in req.apis:
        logger.info(
            "generate_drafts.api_start requestId=%s apiId=%s "
            "contextSummaryLen=%d requestSchema=%s responseSchema=%s",
            req.requestId,
            api.apiId,
            len(ctx.contextSummary) if ctx.contextSummary else 0,
            api.requestSchema is not None,
            api.responseSchema is not None,
        )
        logger.debug(
            "generate_drafts.api_start requestId=%s apiId=%s contextSummary=%r",
            req.requestId,
            api.apiId,
            ctx.contextSummary,
        )
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

        logger.debug(
            "generate_drafts.llm_input requestId=%s apiId=%s prompt_len=%d prompt=%s",
            req.requestId,
            api.apiId,
            len(prompt),
            prompt,
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
            drafts_raw = result.get("drafts")
            logger.info(
                "generate_drafts.llm_output requestId=%s apiId=%s "
                "drafts_type=%s drafts_count=%s",
                req.requestId,
                api.apiId,
                type(drafts_raw).__name__,
                len(drafts_raw) if isinstance(drafts_raw, (list, str)) else "n/a",
            )
            logger.debug(
                "generate_drafts.llm_output requestId=%s apiId=%s result=%r",
                req.requestId,
                api.apiId,
                result,
            )
            output = _DraftListOutput.model_validate(_coerce_tool_result(result))
            for draft in output.drafts:
                raw_drafts.append({**draft.model_dump(), "apiId": api.apiId})
        except Exception as exc:
            logger.warning(
                "generate_drafts.llm_failed requestId=%s apiId=%s error=%s",
                req.requestId,
                api.apiId,
                exc,
                exc_info=True,
            )

    return {**state, "raw_drafts": raw_drafts}
