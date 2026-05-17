"""시나리오 플래너 프롬프트.

프롬프트는 코드와 분리해 두는 게 향후 평가·튜닝에 유리.
프롬프트 변경 시 diff가 명확하고, 모델 비교 시 동일 프롬프트를 양쪽에 주입 가능.
"""

from __future__ import annotations

from app.schemas import APIInventory


SYSTEM_PROMPT = """\
당신은 QA/QC 자동화 시스템 'FlowOps'의 시나리오 테스트 플래너입니다.

당신의 역할:
- 주어진 API 목록을 활용해 실제 사용자 흐름을 재현하는 End-to-End 테스트 시나리오를 설계합니다.
- 단일 API 동작이 아니라, 여러 API가 연결되는 실제 서비스 흐름을 검증하는 것이 목표입니다.

설계 원칙:
1. 각 스텝은 반드시 제공된 API 목록(endpoint_id)에서 선택해야 합니다. 임의로 만들면 안 됩니다.
2. 스텝 순서는 실제 사용자 행동 흐름과 일치해야 합니다 (예: 로그인 → 인증 필요한 API).
3. 인증이 필요한 API 앞에는 토큰 발급 API를 배치합니다.
4. 한 시나리오의 스텝 수는 2~8개가 적절합니다. 너무 길면 검증이 어려워집니다.
5. 이 단계에서는 변수 전달(예: 토큰을 다음 요청에 주입) 매핑은 만들지 않습니다.
   별도 단계가 이를 처리하므로, 당신은 흐름 설계와 각 스텝의 입력값 결정에만 집중하세요.
6. expected_assertions는 자연어로 1~3개 (예: "응답에 userId가 포함됨").

출력 형식:
- 반드시 제공된 도구(emit_scenarios)를 호출하여 결과를 반환하세요.
- ref는 'step_1', 'step_2'처럼 순번을 매기되 한 시나리오 안에서 유일해야 합니다.
- order는 1부터 시작하는 정수입니다.
"""


def build_user_prompt(
    *,
    user_intent: str,
    inventory: APIInventory,
    max_scenarios: int,
    max_steps_per_scenario: int,
) -> str:
    """user 프롬프트를 조립.

    API 목록은 LLM이 이해하기 쉽도록 간결한 텍스트로 직렬화.
    (전체 JSON Schema를 그대로 넣으면 토큰만 잡아먹고 정확도가 떨어짐.)
    """
    api_lines: list[str] = []
    for ep in inventory.endpoints:
        line = f"- {ep.endpoint_id}"
        if ep.summary:
            line += f"  ({ep.summary})"
        if ep.auth and ep.auth.type != "none":
            line += f"  [인증: {ep.auth.type}]"
        if ep.tags:
            line += f"  태그: {', '.join(ep.tags)}"
        api_lines.append(line)

    api_block = "\n".join(api_lines) if api_lines else "(API 없음)"

    return f"""\
프로젝트의 사용 가능한 API 목록:
{api_block}

사용자가 원하는 흐름:
{user_intent}

요구사항:
- 위 흐름을 검증하는 시나리오를 {max_scenarios}개 이내로 만드세요.
- 각 시나리오는 {max_steps_per_scenario}개 스텝 이하여야 합니다.
- 사용자의 의도를 다각도로 검증할 수 있도록, 가능하면 정상 흐름과 함께 변형 흐름(예: 잘못된 입력)도 시나리오로 추가하세요.

도구(emit_scenarios)를 호출해 결과를 반환하세요.
"""
