from typing import Any
from typing_extensions import TypedDict
from app.llm import LLMClient
from app.schemas.testcase import TestCaseGenerationRequest, TestCaseDraft


class TestCaseAgentState(TypedDict):
    llm: LLMClient
    request: TestCaseGenerationRequest
    raw_drafts: list[dict[str, Any]]   # LLM raw output before dedup
    drafts: list[TestCaseDraft]        # final output
    error: str | None
    retry_count: int
