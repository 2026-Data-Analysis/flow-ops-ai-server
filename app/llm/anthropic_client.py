"""Anthropic Claude 기반 LLM 클라이언트 구현.

핵심 기법: Tool Use를 활용한 구조화 출력.
- 모델에게 "이 도구를 호출해" 라고 강제(tool_choice)
- 도구의 input_schema가 곧 우리의 기대 출력 스키마
- 모델은 input_schema에 맞춰 JSON을 만들어 tool_use 블록으로 반환

이 방식이 프롬프트로 'JSON만 출력해' 라고 요청하는 것보다 훨씬 안정적이다.
공식 문서에서도 구조화 출력 표준 패턴으로 제시한다.
"""

from __future__ import annotations

import logging
from typing import Any

from anthropic import Anthropic

from app.schemas import TokenUsage

logger = logging.getLogger(__name__)


class AnthropicClient:
    """Claude API 래퍼.

    이 클래스는 위 LLMClient Protocol을 만족한다 (덕 타이핑).
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str = "claude-sonnet-4-5",
    ) -> None:
        """
        Args:
            api_key: ANTHROPIC_API_KEY. None이면 SDK가 환경변수에서 읽음.
            model: 사용할 모델명.
                - 시나리오 생성 같은 추론이 필요한 작업: claude-sonnet-4-5
                - 단순 분류·요약: 더 가벼운 모델로 교체 가능
        """
        self._client = Anthropic(api_key=api_key) if api_key else Anthropic()
        self._model = model

    def generate_structured(
        self,
        *,
        system: str,
        user: str,
        output_schema: dict[str, Any],
        output_name: str,
        output_description: str,
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> tuple[dict[str, Any], TokenUsage]:
        """Tool Use를 강제하여 구조화 JSON을 받아옴."""

        # Pydantic이 생성하는 JSON Schema에는 $defs, title 등이 포함됨.
        # Anthropic은 표준 JSON Schema를 받으므로 그대로 넘겨도 동작.
        tool = {
            "name": output_name,
            "description": output_description,
            "input_schema": _sanitize_schema(output_schema),
        }

        logger.debug(
            "anthropic.messages.create model=%s tool=%s",
            self._model,
            output_name,
        )

        response = self._client.messages.create(
            model=self._model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system,
            tools=[tool],
            tool_choice={"type": "tool", "name": output_name},
            messages=[{"role": "user", "content": user}],
        )

        # 응답에서 tool_use 블록 추출
        tool_input: dict[str, Any] | None = None
        for block in response.content:
            if block.type == "tool_use" and block.name == output_name:
                tool_input = block.input  # type: ignore[assignment]
                break

        if tool_input is None:
            # tool_choice를 강제했는데 못 받아오면 명확한 예외로
            raise RuntimeError(
                f"LLM did not return tool_use for '{output_name}'. "
                f"stop_reason={response.stop_reason}"
            )

        usage = TokenUsage(
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            model=self._model,
        )
        return tool_input, usage


def _sanitize_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Pydantic JSON Schema → Anthropic tool input_schema로 정리.

    Anthropic은 'title' 같은 메타 필드를 무시하지만 일부 모델은 알 수 없는 키에 민감.
    당장은 그대로 넘기되, 필요 시 여기서 제거.
    """
    # 현재는 통과. 추후 필요한 변환을 여기 추가.
    return schema
