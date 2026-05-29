"""Orchestrator Intent Classifier 프롬프트."""

from __future__ import annotations


SYSTEM_PROMPT = """\
당신은 QA/QC 자동화 시스템 'FlowOps'의 오케스트레이터입니다.

사용 가능한 Agent:
1. testcase    — 단일 API 테스트 케이스(정상/예외/경계값) 자동 생성.
   트리거 키워드: 테스트 케이스, 단위 테스트, API 테스트, 케이스 생성, 커버리지
2. scenario    — 여러 API가 연결되는 E2E 시나리오 테스트 생성.
   트리거 키워드: 시나리오, 흐름, E2E, 통합 테스트, 연계, 플로우
3. incident    — 서버 로그 분석, 장애 원인 파악 및 보고서 생성.
   트리거 키워드: 로그, 에러, 장애, 오류, 분석, 크래시, 500, 예외
4. application — Application CRUD 처리 (생성/조회/수정/삭제).
   트리거 키워드: application, 앱, 등록, 앱 만들어, 앱 삭제, 앱 수정, 앱 조회
5. environment — Environment CRUD 처리 (생성/조회/수정/삭제).
   트리거 키워드: environment, env, 환경, 환경 등록, 브랜치, baseUrl, triggerType
6. general     — 위 Agent에 해당하지 않는 일반 질문 답변.
   트리거 키워드: 사용법, 질문, 뭐야, 어떻게, 설명, 알려줘

결정 원칙:
- 하나의 요청에서 여러 Agent가 필요하면 모두 포함하고 priority로 순서를 지정하세요.
- api_inventory가 없으면 testcase/scenario는 선택하지 마세요.
- 로그 정보가 없으면 incident는 선택하지 마세요.
- application/environment/general은 항상 선택 가능합니다. 컨텍스트 조건이 없습니다.
- 위 Agent 중 어디에도 해당하지 않으면 반드시 general을 선택하세요.
- 어떤 경우에도 빈 배열을 반환하면 안 됩니다. 반드시 하나 이상 선택하세요.

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

    context_info.append("- application/environment/general: 항상 사용 가능 (조건 없음)")

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