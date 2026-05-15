from typing import Any, TYPE_CHECKING
from typing_extensions import TypedDict
from app.schemas.testcase import TestCaseGenerationRequest, TestCaseDraft

if TYPE_CHECKING:
    from app.llm import LLMClient


class TestCaseAgentState(TypedDict):
    llm: "LLMClient"
    request: TestCaseGenerationRequest
    raw_drafts: list[dict[str, Any]]   # LLM raw output before dedup
    drafts: list[TestCaseDraft]        # final output
    error: str | None
