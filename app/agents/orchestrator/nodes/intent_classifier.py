"""Intent Classifier 노드.

역할:
- 사용자 자연어 프롬프트를 분석해 어떤 Agent(들)를 어떤 순서로 호출할지 결정.
- LLM 분류 후 코드 레벨 후처리로 명확한 키워드는 강제 적용.

Agent 타입:
  - testcase:       테스트 케이스 자동 생성
  - scenario:       시나리오(E2E) 테스트 생성
  - incident:       로그 기반 장애 분석
  - application:    Application CRUD
  - environment:    Environment CRUD
  - api_management: API 검색/조회
  - general:        일반 질문 답변
"""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field, ValidationError

from app.agents.orchestrator.state import OrchestratorAgentState, OrchestratorError
from app.core.logging import log_event, log_step
from app.llm import LLMClient
from app.llm.prompts.orchestrator_classifier import SYSTEM_PROMPT, build_user_prompt

logger = logging.getLogger(__name__)


class _IntentItem(BaseModel):
    agent: str = Field(
        description="testcase | scenario | incident | application | environment | api_management | general"
    )
    priority: int = Field(ge=1, description="실행 우선순위 (1이 가장 먼저)")
    reason: str = Field(description="이 Agent를 선택한 이유 한 줄")
    user_intent: str | None = Field(
        default=None,
        description="scenario Agent에 전달할 user_intent. scenario일 때만 채움.",
    )


class _ClassifierOutput(BaseModel):
    intents: list[_IntentItem]


_ALLOWED_AGENTS = {
    "testcase", "scenario", "incident",
    "general", "application", "environment",
    "api_management",
}

# testcase 강제 트리거 키워드 — 이 단어가 있으면 무조건 testcase 단독 실행
_TESTCASE_FORCE_KEYWORDS = [
    "테스트 케이스", "테스트케이스", "testcase", "test case",
    "단위 테스트", "유닛 테스트", "케이스 생성", "케이스 만들어", "케이스 만들",
]


def _postprocess_intents(intents: list[dict], user_prompt: str) -> list[dict]:
    """LLM 분류 결과 후처리.

    testcase 키워드가 명시적으로 있으면 LLM 판단과 무관하게 testcase 단독 실행.
    예: "시나리오 실험해보는 테스트 케이스 생성해줘" → testcase만 실행
    """
    prompt_lower = user_prompt.lower()
    has_testcase_keyword = any(kw in prompt_lower for kw in _TESTCASE_FORCE_KEYWORDS)
    agent_types = [i["agent"] for i in intents]

    if has_testcase_keyword:
        # testcase가 없으면 강제 추가
        if "testcase" not in agent_types:
            logger.info("[intent_classifier] testcase 키워드 감지 → testcase 강제 선택")
            return [{
                "agent": "testcase",
                "priority": 1,
                "reason": "테스트 케이스 키워드 감지로 강제 선택",
                "user_intent": None,
            }]
        # testcase + scenario 동시 선택이면 scenario 제거
        if "scenario" in agent_types:
            logger.info("[intent_classifier] testcase 키워드 감지 → scenario 제거, testcase만 유지")
            return [i for i in intents if i["agent"] != "scenario"]

    return intents


def make_intent_classifier_node(llm: LLMClient):
    def intent_classifier_node(state: OrchestratorAgentState) -> dict:
        user_prompt_text = state.get("user_prompt", "")
        context = state.get("context", {})

        if not user_prompt_text.strip():
            return {
                "errors": [OrchestratorError(
                    node="intent_classifier",
                    code="EMPTY_PROMPT",
                    message="user_prompt가 비어있습니다.",
                )]
            }

        log_event(logger, "info", "[intent_classifier] 사용자 의도 분류 시작",
            prompt=user_prompt_text[:80],
            has_api_inventory=bool(context.get("api_inventory")),
            has_log=bool(context.get("raw_log") or context.get("log_entries")),
        )

        prompt = build_user_prompt(
            user_prompt=user_prompt_text,
            has_api_inventory=bool(context.get("api_inventory")),
            has_log=bool(context.get("raw_log") or context.get("log_entries")),
        )

        try:
            with log_step(logger, "intent_classifier", step="LLM 호출"):
                raw_output, usage = llm.generate_structured(
                    system=SYSTEM_PROMPT,
                    user=prompt,
                    output_schema=_ClassifierOutput.model_json_schema(),
                    output_name="emit_intent_plan",
                    output_description="사용자 의도에 맞는 Agent 실행 계획",
                    max_tokens=800,
                    temperature=0.0,
                )
        except Exception as e:
            logger.error(f"[intent_classifier] LLM 호출 실패: {e}")
            return {
                "errors": [OrchestratorError(
                    node="intent_classifier",
                    code="LLM_CALL_FAILED",
                    message=str(e),
                )]
            }

        try:
            parsed = _ClassifierOutput.model_validate(raw_output)
        except ValidationError as e:
            logger.error(f"[intent_classifier] 출력 파싱 실패: {e}")
            return {
                "errors": [OrchestratorError(
                    node="intent_classifier",
                    code="OUTPUT_VALIDATION_FAILED",
                    message=str(e),
                )],
                "token_usages": [usage],
            }

        # 유효한 Agent 타입만 필터링
        valid_intents = []
        for item in sorted(parsed.intents, key=lambda x: x.priority):
            if item.agent not in _ALLOWED_AGENTS:
                logger.warning(f"[intent_classifier] 알 수 없는 Agent 타입 무시: {item.agent}")
                continue
            valid_intents.append({
                "agent": item.agent,
                "priority": item.priority,
                "reason": item.reason,
                "user_intent": item.user_intent,
            })

        # fallback
        if not valid_intents:
            logger.warning("[intent_classifier] 분류 실패 → general로 fallback")
            valid_intents = [{
                "agent": "general",
                "priority": 1,
                "reason": "분류 실패 fallback",
                "user_intent": None,
            }]

        # ✅ 코드 레벨 후처리 — testcase 키워드 강제 적용
        valid_intents = _postprocess_intents(valid_intents, user_prompt_text)

        agents = [i["agent"] for i in valid_intents]
        logger.info(f"[intent_classifier] 분류 완료 → 실행할 Agent: {agents} "
                    f"(입력 토큰: {usage.input_tokens}, 출력 토큰: {usage.output_tokens})")

        return {
            "intent_plan": valid_intents,
            "token_usages": [usage],
        }

    return intent_classifier_node