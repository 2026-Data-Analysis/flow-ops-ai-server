"""Incident Analyzer 프롬프트."""

from __future__ import annotations

import json
from typing import Any


SYSTEM_PROMPT = """\
당신은 QA/QC 자동화 시스템 'FlowOps'의 장애 분석 전문가입니다.

당신의 역할:
- 서버 로그와 테스트 실패 컨텍스트를 분석하여 장애 원인 후보를 도출합니다.
- 개발자가 빠르게 문제를 파악하고 대응할 수 있도록 구체적이고 실행 가능한 분석을 제공합니다.

분석 원칙:
1. 근거 기반: 모든 원인 후보는 실제 로그 라인 또는 에러 메시지를 근거로 제시해야 합니다.
2. 우선순위: CRITICAL > HIGH > MEDIUM > LOW 순서로 정렬하세요.
3. 구체성: "서버 에러 발생" 같은 모호한 표현 대신, 어떤 컴포넌트에서 어떤 이유로 실패했는지 명시하세요.
4. 실행 가능성: suggested_fix는 실제로 개발자가 취할 수 있는 행동을 제시하세요.
5. 범위 제한: 최대 5개의 원인 후보만 제시하세요. 너무 많으면 오히려 혼란을 줍니다.

severity 기준:
- CRITICAL: 서비스 전체 다운, 데이터 손실/유출 가능성
- HIGH: 핵심 기능 장애, 다수 사용자 영향
- MEDIUM: 일부 기능 장애, 특정 조건에서만 발생
- LOW: 경고성 이슈, 당장 서비스 영향 없음

출력은 반드시 emit_root_causes 도구를 호출하여 반환하세요.
"""


def build_user_prompt(
    *,
    log_entries: list[dict],
    failure_context: Any | None,
    service_name: str,
) -> str:
    # 로그 엔트리 직렬화 (너무 길면 상위 50개만)
    entries_to_show = log_entries[:50]
    # severity, raw 모두 .get()으로 방어
    log_text = "\n".join(
        f"[{e.get('severity') or 'UNKNOWN'}] {e.get('timestamp') or ''} {e.get('raw') or e.get('message') or ''}"
        for e in entries_to_show
    )
    if len(log_entries) > 50:
        log_text += f"\n... (총 {len(log_entries)}개 중 상위 50개만 표시)"

    failure_text = ""
    if failure_context:
        fc = failure_context if isinstance(failure_context, dict) else failure_context.model_dump(exclude_none=True)
        failure_text = f"""
## 테스트 실패 컨텍스트
{json.dumps(fc, ensure_ascii=False, indent=2)}
"""

    return f"""\
서비스명: {service_name}

## 로그 엔트리 ({len(entries_to_show)}건)
{log_text}
{failure_text}

위 로그를 분석하여 장애 원인 후보를 도출하고, emit_root_causes 도구를 호출해 반환하세요.
"""
