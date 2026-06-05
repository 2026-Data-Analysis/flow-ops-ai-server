"""Response Chainer 프롬프트.

chainer는 planner가 만든 시나리오의 step들을 살펴보고,
이전 step의 응답에서 어떤 값을 꺼내 다음 step의 어디에 주입할지를 결정한다.

스키마 변경 반영: step.name→step.title, step.endpoint_id→step.apiId,
step.static_payload→step.requestSpec.
"""

from __future__ import annotations

import json

from app.core.response_spec import success_schema
from app.schemas import APIInventory, Scenario


SYSTEM_PROMPT = """\
당신은 QA/QC 자동화 시스템 'FlowOps'의 Response Chainer입니다.

당신의 역할:
- 시나리오 안의 각 API 호출 스텝이 서로 어떻게 데이터를 주고받는지를 결정합니다.
- 구체적으로, 이전 스텝의 응답에서 어떤 값을 추출해 다음 스텝의 어디에 주입할지를 매핑합니다.

기본 원칙:
1. 미래 참조 금지: source_step_ref는 반드시 현재 스텝보다 앞선(order가 더 작은) 스텝이어야 합니다.
2. 인증 토큰 우선: 인증이 필요한 스텝(auth.type != 'none')에는 거의 항상 이전 로그인/인증 응답의 토큰을 헤더로 주입해야 합니다.
   - target_template은 보통 'Bearer {value}' 형태입니다.
3. 식별자 연결: 이전 응답의 ID(예: userId, postId)가 다음 스텝의 path 파라미터나 body의 외래 키로 자연스럽게 연결되면 매핑하세요.
4. JSONPath 정확성: source_json_path는 반드시 source 스텝의 response_schema에 실제 존재하는 경로여야 합니다. 임의의 경로를 만들면 안 됩니다.
5. 매핑이 필요 없는 스텝은 빈 배열을 반환합니다. 억지로 만들지 마세요.
6. 매핑 이름(name)은 한 시나리오 안에서 의미가 통하면 좋습니다 (예: auth_token, created_user_id).

target_location 가이드:
- "header": HTTP 헤더 (예: Authorization)
- "path":   경로 파라미터 (예: /users/{userId}의 userId)
- "query":  쿼리 파라미터
- "body":   요청 바디 안의 필드. target_field에 JSONPath 사용 (예: $.author.id)

target_template 가이드:
- 값을 그대로 쓰면 생략 또는 "{value}"
- 접두사가 필요하면 "Bearer {value}" 같은 식

출력 형식:
- 반드시 제공된 도구(emit_chained_variables)를 호출하여 결과를 반환하세요.
- 결과는 step_ref별로 그룹핑된 매핑 배열입니다.
"""


def build_user_prompt(
    *,
    scenario: Scenario,
    inventory: APIInventory,
) -> str:
    """user 프롬프트를 조립.

    LLM이 정확한 매핑을 만들려면 다음 정보가 필요:
    1. 각 step이 어떤 endpoint를 호출하는지
    2. 각 endpoint의 request 명세 (auth, body schema)
    3. 각 endpoint의 response schema
    """
    by_id = inventory.by_id()

    step_blocks: list[str] = []
    for step in sorted(scenario.steps, key=lambda s: s.order):
        ep = by_id.get(step.apiId)
        if ep is None:
            # planner가 이미 검증했으므로 여기까진 오면 안 되지만 방어적으로 처리
            continue

        block = [
            f"### {step.ref} (order={step.order}): {step.title}",
            f"  endpoint: {ep.method.value} {ep.path}",
        ]
        if ep.auth and ep.auth.type != "none":
            location = f", location={ep.auth.location}" if ep.auth.location else ""
            block.append(f"  auth required: type={ep.auth.type}{location}")
        if ep.parameters:
            params_desc = [
                f"{p.name}({p.location}, {p.type}{', required' if p.required else ''})"
                for p in ep.parameters
            ]
            block.append(f"  parameters: {', '.join(params_desc)}")
        if ep.request_body_schema:
            block.append(
                f"  request_body_schema: {json.dumps(ep.request_body_schema, ensure_ascii=False)}"
            )
        success = success_schema(ep.response_schema)
        if success:
            block.append(
                f"  response_schema(성공 응답): {json.dumps(success, ensure_ascii=False)}"
            )
        if step.requestSpec:
            block.append(
                f"  requestSpec (이미 채워진 고정값): {json.dumps(step.requestSpec, ensure_ascii=False)}"
            )
        step_blocks.append("\n".join(block))

    steps_text = "\n\n".join(step_blocks)

    return f"""\
다음 시나리오의 스텝 간 변수 매핑(chained_variables)을 생성하세요.

시나리오 이름: {scenario.name}
설명: {scenario.description or '(없음)'}

스텝 상세:
{steps_text}

요구사항:
- 각 스텝에 대해, 그 스텝이 필요로 하는 chained_variables 배열을 만드세요.
- 매핑이 필요 없는 스텝은 변수 배열을 빈 배열([])로 두세요.
- 인증이 필요한 스텝에 인증 매핑을 빠뜨리지 마세요.
- 모든 source_step_ref는 현재 스텝보다 order가 작아야 합니다.

도구(emit_chained_variables)를 호출해 결과를 반환하세요.
"""