"""General Agent — 단순 질문 답변."""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field, ValidationError

from app.llm import LLMClient

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
당신은 QA/QC 자동화 시스템 'FlowOps'의 어시스턴트입니다.

사용자의 질문에 친절하고 명확하게 답변하세요.
FlowOps의 기능(테스트 케이스 생성, 시나리오 테스트, 장애 분석)에 관한 질문이라면
구체적인 사용 방법도 함께 안내해주세요.
"""


class _ResponderOutput(BaseModel):
    answer: str = Field(description="사용자 질문에 대한 답변")


def ask(user_prompt: str, llm: LLMClient) -> str:
    """질문을 받아 답변 문자열을 반환. 실패 시 예외 발생."""
    raw_output, _ = llm.generate_structured(
        system=SYSTEM_PROMPT,
        user=user_prompt,
        output_schema=_ResponderOutput.model_json_schema(),
        output_name="emit_answer",
        output_description="사용자 질문에 대한 답변",
        max_tokens=1000,
        temperature=0.3,
    )
    parsed = _ResponderOutput.model_validate(raw_output)
    return parsed.answer