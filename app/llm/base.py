"""LLM 클라이언트 추상 인터페이스.

설계 결정:
1. Protocol 사용 (ABC가 아닌). 더 유연하고, 외부 라이브러리 객체도 덕 타이핑으로 만족 가능.
2. 메서드는 단 하나: generate_structured(). 구조화 JSON 출력을 받는 게 우리의 유일한 사용 패턴.
   비구조화 텍스트가 필요해지면 그때 추가.
3. 반환은 (parsed_dict, token_usage) 튜플. 호출 측에서 Pydantic 검증과 토큰 누적을 따로 처리.
"""

from __future__ import annotations

from typing import Any, Protocol

from app.schemas import TokenUsage


class LLMClient(Protocol):
    """LLM 호출 추상화.

    제안서 2.3 모델 비교를 위해 동일 인터페이스로 OpenAI/Anthropic 양쪽을 감쌀 수 있도록 함.
    """

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
        """주어진 JSON Schema에 맞춘 구조화 출력을 생성.

        Args:
            system: 시스템 프롬프트
            user: 사용자 프롬프트
            output_schema: 기대 출력의 JSON Schema (Pydantic.model_json_schema() 결과)
            output_name: 도구 이름 또는 출력 식별자. 영문 snake_case.
            output_description: 무엇을 만드는 도구인지 한 줄 설명
            max_tokens: 응답 최대 토큰
            temperature: 샘플링 온도. 시나리오 생성은 0.0~0.2 권장.

        Returns:
            (LLM이 채운 dict, 토큰 사용량)
            dict는 output_schema를 따르지만 Pydantic 검증은 호출 측 책임.
        """
        ...
