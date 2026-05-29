"""Intent Classifier 노드.

역할:
- 사용자 자연어 프롬프트를 분석해 어떤 Agent(들)를 어떤 순서로 호출할지 결정.
- 각 Agent 호출에 필요한 파라미터를 context에서 추출해 매핑.

Agent 타입:
  - testcase:  테스트 케이스 자동 생성
  - scenario:  시나리오(E2E) 테스트 생성
  - incident:  로그 기반 장애 분석

하나의 프롬프트로 여러 Agent를 순차 실행 가능.
예: "로그 분석하고 수정 후 테스트 케이스도 만들어줘"
 → [incident(priority=1), testcase(priority=2)]
"""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field, ValidationError

from app.agents.orchestrator.state import OrchestratorAgentState, OrchestratorError
from app.llm import LLMClient
from app.llm.prompts.orchestrator_classifier import SYSTEM_PROMPT, build_user_prompt

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# LLM 출력 스키마
# ---------------------------------------------------------------------------

class _IntentItem(BaseModel):
    agent: str = Field(description="testcase | scenario | incident | application | environment | general")
    priority: int = Field(ge=1, description="실행 우선순위 (1이 가장 먼저)")
    reason: str = Field(description="이 Agent를 선택한 이유 한 줄")
    user_intent: str | None = Field(
        default=None,
        description="scenario Agent에 전달할 user_intent. scenario일 때만 채움.",
    )


class _ClassifierOutput(BaseModel):
    intents: list[_IntentItem]


_ALLOWED_AGENTS = {"testcase", "scenario", "incident", "general", "application", "environment", "api_management"}


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

        prompt = build_user_prompt(
            user_prompt=user_prompt_text,
            has_api_inventory=bool(context.get("api_inventory")),
            has_log=bool(context.get("raw_log") or context.get("log_entries")),
        )

        try:
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
            logger.exception("intent_classifier LLM call failed")
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
            return {
                "errors": [OrchestratorError(
                    node="intent_classifier",
                    code="OUTPUT_VALIDATION_FAILED",
                    message=str(e),
                )],
                "token_usages": [usage],
            }

        # 유효하지 않은 agent 타입 필터링
        valid_intents = []
        for item in sorted(parsed.intents, key=lambda x: x.priority):
            if item.agent not in _ALLOWED_AGENTS:
                logger.warning("unknown agent type in intent plan: %s", item.agent)
                continue
            valid_intents.append({
                "agent": item.agent,
                "priority": item.priority,
                "reason": item.reason,
                "user_intent": item.user_intent,
            })

        if not valid_intents:
            # 수정 후: general로 fallback
            logger.warning("intent_classifier: no valid intent found, falling back to general")
            valid_intents = [{
                "agent": "general",
                "priority": 1,
                "reason": "분류 실패 fallback",
                "user_intent": None,
            }]

        return {
            "intent_plan": valid_intents,
            "token_usages": [usage],
        }

    return intent_classifier_node
