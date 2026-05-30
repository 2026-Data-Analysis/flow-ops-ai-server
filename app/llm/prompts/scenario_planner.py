"""시나리오 플래너 프롬프트.

프롬프트는 코드와 분리해 두는 게 향후 평가·튜닝에 유리.
프롬프트 변경 시 diff가 명확하고, 모델 비교 시 동일 프롬프트를 양쪽에 주입 가능.

[2단계 변경]
- 각 스텝의 type(DraftType)을 LLM이 분류하도록.
- requestSpec.body가 해당 endpoint의 request_body_schema 구조/필수필드를 따르도록 강제
  (이전 스텝 응답에서 와야 하는 동적 값은 비워두고 chainer가 채움).
- expectedSpec / assertionSpec를 LLM이 채우도록.
- user 프롬프트에 각 endpoint의 parameters / request_body_schema / response_schema를 포함
  (이전에는 endpoint_id/summary만 줘서 LLM이 body 구조를 알 수 없었음 → 정합성 문제의 근본 원인).
"""

from __future__ import annotations

import json

from app.schemas import APIInventory


SYSTEM_PROMPT = """\
당신은 QA/QC 자동화 시스템 'FlowOps'의 시나리오 테스트 플래너입니다.

당신의 역할:
- 주어진 API 목록을 활용해 실제 사용자 흐름을 재현하는 End-to-End 테스트 시나리오를 설계합니다.
- 단일 API 동작이 아니라, 여러 API가 연결되는 실제 서비스 흐름을 검증하는 것이 목표입니다.

설계 원칙:
1. 각 스텝의 endpoint_id는 반드시 제공된 API 목록에서 선택해야 합니다. 임의로 만들면 안 됩니다.
2. 스텝 순서는 실제 사용자 행동 흐름과 일치해야 합니다 (예: 로그인 → 인증 필요한 API).
3. 인증이 필요한 API 앞에는 토큰을 발급하는 스텝을 배치합니다.
4. 한 시나리오의 스텝 수는 2~8개가 적절합니다. 너무 길면 검증이 어려워집니다.
5. 가능하면 정상 흐름과 함께 변형(실패) 흐름도 시나리오로 추가하세요.

## 각 스텝에 채울 필드

### type (이 스텝의 성격 분류)
- HAPPY_PATH: 유효한 입력으로 정상 동작하는 경우
- VALIDATION: 잘못된/누락된/타입이 틀린 입력
- FAILURE_HANDLING: 서버 오류·타임아웃 등 실패 처리
- EDGE_CASE: 경계값 (빈 배열, 최대 길이, 0, null 등)
- AUTHORIZATION: 인증 누락/만료/권한 부족 (auth가 필요한 API에서만)
- PERFORMANCE: 대용량·고부하 시나리오
→ 흐름의 의도에 맞게 정확히 분류하세요. 예: 토큰 없이 보호된 API를 호출하는 스텝은 AUTHORIZATION 입니다.

### requestSpec  {method, pathParams, queryParams, body}
- method는 해당 endpoint의 메서드를 그대로.
- body는 **반드시 해당 endpoint의 request_body_schema 구조를 따르고, required 필드를 모두 포함**해야 합니다.
- request_body_schema에 **없는 필드는 절대 넣지 마세요.**
- **정적인(고정) 값만** 채우세요. 이전 스텝의 응답에서 와야 하는 동적 값
  (인증 토큰, 이전 단계에서 생성된 userId/orderId 같은 식별자 등)은
  body/pathParams/queryParams에 넣지 말고 **비워두세요. 별도 단계(chainer)가 채웁니다.**
- pathParams는 경로 템플릿({...})에 해당하는 정적 값, queryParams는 쿼리 파라미터 정적 값.

### expectedSpec  {statusCode, body, errorMessage}
- statusCode: 이 스텝의 기대 HTTP 상태 코드.
- body: 주요 기대 응답 필드의 예시 객체 (마땅치 않으면 null).
- errorMessage: 실패 케이스면 기대 에러 메시지 문자열, 정상 케이스면 null.

### assertionSpec  {statusCode, bodyContains, bodyEquals, headerContains}
- statusCode: 기대 상태 코드 (int).
- bodyContains: 응답 body에 포함되어야 하는 키 또는 문자열 목록 (예: ["orderId", "status"]).
- bodyEquals: 정확히 일치해야 하는 필드-값 쌍 (없으면 {}).
- headerContains: 확인할 응답 헤더 (예: {"Content-Type": "application/json"}).

## 출력 형식
- 반드시 제공된 도구(emit_scenarios)를 호출하여 결과를 반환하세요.
- ref는 'step_1', 'step_2'처럼 순번을 매기되 한 시나리오 안에서 유일해야 합니다.
- order는 1부터 시작하는 정수이며 연속이어야 합니다.
- title / description은 한국어로 작성하세요.
"""


def _endpoint_block(ep) -> str:
    """LLM이 정확한 body/스펙을 만들도록 endpoint 1개의 상세를 직렬화."""
    lines = [f"- {ep.endpoint_id}  ({ep.method.value} {ep.path})"]
    if ep.summary:
        lines.append(f"    설명: {ep.summary}")
    if ep.auth and ep.auth.type != "none":
        location = f", location={ep.auth.location}" if ep.auth.location else ""
        lines.append(f"    인증: {ep.auth.type}{location}")
    if ep.parameters:
        params = [
            f"{p.name}({p.location}, {p.type}{', required' if p.required else ''})"
            for p in ep.parameters
        ]
        lines.append(f"    parameters: {', '.join(params)}")
    if ep.request_body_schema:
        lines.append(
            f"    request_body_schema: {json.dumps(ep.request_body_schema, ensure_ascii=False)}"
        )
    if ep.response_schema:
        lines.append(
            f"    response_schema: {json.dumps(ep.response_schema, ensure_ascii=False)}"
        )
    return "\n".join(lines)


def build_user_prompt(
    *,
    user_intent: str,
    inventory: APIInventory,
    max_scenarios: int,
    max_steps_per_scenario: int,
) -> str:
    """user 프롬프트를 조립.

    각 endpoint의 메서드/파라미터/요청·응답 스키마까지 제공해야
    LLM이 request_body_schema에 맞는 body를 만들 수 있다.
    """
    if inventory.endpoints:
        api_block = "\n".join(_endpoint_block(ep) for ep in inventory.endpoints)
    else:
        api_block = "(API 없음)"

    return f"""\
프로젝트의 사용 가능한 API 목록 (각 endpoint의 스키마 포함):
{api_block}

사용자가 원하는 흐름:
{user_intent}

요구사항:
- 위 흐름을 검증하는 시나리오를 {max_scenarios}개 이내로 만드세요.
- 각 시나리오는 {max_steps_per_scenario}개 스텝 이하여야 합니다.
- 각 스텝의 type을 정확히 분류하고, requestSpec.body는 해당 endpoint의 request_body_schema를 따르세요.
- 이전 스텝 응답에서 와야 하는 동적 값(토큰, 생성된 ID 등)은 body에 넣지 말고 비워두세요.
- 사용자의 의도를 다각도로 검증하도록, 정상 흐름과 함께 변형 흐름(잘못된 입력/미인증 등)도 추가하세요.

도구(emit_scenarios)를 호출해 결과를 반환하세요.
"""