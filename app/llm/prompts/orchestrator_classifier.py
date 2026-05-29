"""Orchestrator Intent Classifier 프롬프트."""

from __future__ import annotations


SYSTEM_PROMPT = """\
당신은 QA/QC 자동화 시스템 'FlowOps'의 오케스트레이터입니다.

사용 가능한 Agent:
1. testcase  — 단일 API에 대한 테스트 케이스(정상/예외/경계값)를 자동 생성합니다.
   트리거 키워드: 테스트 케이스, 단위 테스트, API 테스트, 케이스 생성, 커버리지
2. scenario  — 여러 API가 연결되는 End-to-End 시나리오 테스트를 생성합니다.
   트리거 키워드: 시나리오, 흐름, E2E, 통합 테스트, 연계, 플로우
3. incident  — 서버 로그를 분석하여 장애 원인을 파악하고 보고서를 생성합니다.
   트리거 키워드: 로그, 에러, 장애, 오류, 분석, 크래시, 500, 예외

결정 원칙:
- 하나의 요청에서 여러 Agent가 필요하면 모두 포함하고 priority로 순서를 지정하세요.
- api_inventory가 없으면 testcase/scenario는 선택하지 마세요.
- 로그 정보가 없으면 incident는 선택하지 마세요.
- 애매한 경우 가장 관련성 높은 Agent 1개만 선택하세요.

출력은 반드시 emit_intent_plan 도구를 호출하여 반환하세요.
"""


def build_user_prompt(
    *,
    user_prompt: str,
    has_api_inventory: bool,
    has_log: bool,
) -> str:
    context_info = []
    if has_api_inventory:
        context_info.append("- API Inventory: 제공됨 (testcase/scenario 사용 가능)")
    else:
        context_info.append("- API Inventory: 없음 (testcase/scenario 사용 불가)")

    if has_log:
        context_info.append("- 로그 데이터: 제공됨 (incident 사용 가능)")
    else:
        context_info.append("- 로그 데이터: 없음 (incident 사용 불가)")

    context_text = "\n".join(context_info)

    return f"""\
사용자 요청:
"{user_prompt}"

현재 제공된 컨텍스트:
{context_text}

위 요청을 분석해 어떤 Agent를 어떤 순서로 실행해야 하는지 결정하고,
emit_intent_plan 도구를 호출해 반환하세요.
scenario Agent를 선택하는 경우 user_intent 필드에 시나리오 생성에 필요한
자연어 흐름 설명을 반드시 채워주세요.
"""
