"""위험도(RiskLevel) 산정 공용 로직.

시나리오/테스트 양쪽에서 재사용할 수 있도록, 구체 스키마가 아니라
'위험 신호(RiskSignals)'만 입력으로 받는다. 호출 측이 자기 구조에서
신호를 뽑아 넘기면 동일한 기준으로 SMOKE/SANITY/REGRESSION/FULL_SUITE를 돌려준다.

(scenario 위험 노드가 이걸 호출. testcase의 suite 위험도 등에서도 동일 기준 재사용 가능.)

기준 (우선순위 순):
- FULL_SUITE: 파괴적(DELETE)이면서 인증/음성 테스트를 동반,
              또는 인증 보호 + 변경(write) 자원에 대해 인증 우회를 탐침(AUTHORIZATION)
- REGRESSION: 파괴적이거나 / 변경 + 인증 보호 동시 / 음성 테스트 2건 이상 /
              깊은 체이닝(>=3) 또는 긴 시나리오(>=6 step)
- SANITY:     변경이 있거나 / 인증 보호가 있거나 / 음성 1건 / 체이닝 존재
- SMOKE:      그 외 (대개 읽기 전용·비인증·단순 흐름)

가중치/임계값을 바꾸고 싶으면 assess_risk 본문의 조건만 손보면 된다 (전부 한 곳).
"""

from __future__ import annotations

from dataclasses import dataclass

from app.schemas.common import RiskLevel


@dataclass(frozen=True)
class RiskSignals:
    """위험도 산정에 쓰는 구조 무관 신호 묶음."""

    mutating: bool       # POST/PUT/PATCH/DELETE 중 하나라도 있음
    destructive: bool    # DELETE 있음
    auth_protected: bool  # bearer/api_key/session 보호 엔드포인트 사용
    probes_auth: bool    # 인증 우회를 노리는 step(AUTHORIZATION) 있음
    negative_count: int  # 음성 테스트(VALIDATION/EDGE_CASE/FAILURE_HANDLING/AUTHORIZATION) 수
    chain_depth: int     # 체이닝 변수를 쓰는 step 수
    step_count: int      # 총 step 수


def assess_risk(s: RiskSignals) -> RiskLevel:
    """위험 신호로부터 RiskLevel 산정 (결정론적, 우선순위 규칙)."""
    # --- FULL_SUITE ---
    if s.destructive and (s.auth_protected or s.negative_count > 0):
        return RiskLevel.FULL_SUITE
    if s.probes_auth and s.auth_protected and s.mutating:
        return RiskLevel.FULL_SUITE

    # --- REGRESSION ---
    if s.destructive:
        return RiskLevel.REGRESSION
    if s.mutating and s.auth_protected:
        return RiskLevel.REGRESSION
    if s.negative_count >= 2:
        return RiskLevel.REGRESSION
    if s.chain_depth >= 3 or s.step_count >= 6:
        return RiskLevel.REGRESSION

    # --- SANITY ---
    if s.mutating or s.auth_protected or s.negative_count >= 1 or s.chain_depth >= 1:
        return RiskLevel.SANITY

    # --- SMOKE ---
    return RiskLevel.SMOKE