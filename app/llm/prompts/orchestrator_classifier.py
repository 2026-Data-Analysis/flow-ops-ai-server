"""Orchestrator Intent Classifier 프롬프트."""

from __future__ import annotations


SYSTEM_PROMPT = """\
당신은 QA/QC 자동화 시스템 'FlowOps'의 오케스트레이터입니다.

사용 가능한 Agent:
1. testcase    — 단일 API에 대한 테스트 케이스(정상/예외/경계값) 파일을 생성합니다.
2. scenario    — 여러 API가 연결되는 E2E 시나리오 테스트 흐름을 설계합니다.
3. incident    — 서버 로그를 분석하여 장애 원인을 파악하고 보고서를 생성합니다.
4. application — Application CRUD를 처리합니다 (생성/조회/수정/삭제).
5. environment — Environment CRUD를 처리합니다 (생성/조회/수정/삭제).
6. api_management — API를 검색하고 조회합니다.
7. general     — 위 Agent에 해당하지 않는 일반 질문에 답변합니다.

## Agent 선택 기준

**사용자의 최종 목적이 무엇인지**를 기준으로 판단하세요. 문장에 포함된 단어가 아닙니다.

- 최종 목적이 "테스트 케이스 파일 생성"이면 → testcase (단 하나만)
- 최종 목적이 "API 흐름 시나리오 설계"이면 → scenario (단 하나만)
- 로그 분석 요청이면 → incident
- Application/Environment 관리 요청이면 → application 또는 environment
- 위 어디에도 해당하지 않으면 → general

## 절대 규칙
- 하나의 요청에서 testcase와 scenario를 동시에 선택하지 마세요.
  둘 중 사용자의 최종 목적에 더 가까운 하나만 선택하세요.
- testcase/scenario는 API 정보가 없어도 선택 가능합니다. API 조회는 Agent 내부에서 처리합니다.
- 로그 데이터가 없으면 incident는 선택하지 마세요.
- 테스트 관련 요청에 절대 general을 선택하지 마세요.
- 어떤 경우에도 빈 배열을 반환하지 마세요.

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
        context_info.append("- API Inventory: 제공됨")
    else:
        context_info.append("- API Inventory: 없음 (testcase/scenario는 서버에서 API를 직접 조회하므로 선택 가능)")

    if has_log:
        context_info.append("- 로그 데이터: 제공됨 (incident 사용 가능)")
    else:
        context_info.append("- 로그 데이터: 없음 (incident 사용 불가)")

    context_text = "\n".join(context_info)

    return f"""\
사용자 요청:
"{user_prompt}"

컨텍스트:
{context_text}

사용자의 최종 목적이 무엇인지 판단하여 가장 적합한 Agent를 선택하세요.
testcase와 scenario는 동시에 선택하지 마세요. 둘 중 하나만 선택하세요.

emit_intent_plan 도구를 호출해 반환하세요.
scenario Agent를 선택하는 경우 user_intent 필드에 시나리오 생성에 필요한
자연어 흐름 설명을 반드시 채워주세요.
"""