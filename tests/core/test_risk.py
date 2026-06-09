"""assess_risk 순수 함수 유닛 테스트.

위험 신호(RiskSignals) 조합별로 LOW/MEDIUM/HIGH/CRITICAL 경계가
의도대로 갈리는지 결정론적으로 검증한다.

실행: pytest app/tests/core/test_risk.py
"""

from __future__ import annotations

from app.core.risk import RiskSignals, assess_risk
from app.schemas.common import RiskLevel


def _sig(**kw) -> RiskSignals:
    base = dict(
        mutating=False,
        destructive=False,
        auth_protected=False,
        probes_auth=False,
        negative_count=0,
        chain_depth=0,
        step_count=1,
    )
    base.update(kw)
    return RiskSignals(**base)


def test_read_only_simple_is_low():
    """읽기 전용·비인증·단순 → LOW."""
    assert assess_risk(_sig()) == RiskLevel.SMOKE


def test_mutating_only_is_medium():
    """변경만 있으면 → MEDIUM."""
    assert assess_risk(_sig(mutating=True)) == RiskLevel.SANITY


def test_auth_protected_read_is_medium():
    """인증 보호된 읽기 → MEDIUM."""
    assert assess_risk(_sig(auth_protected=True)) == RiskLevel.SANITY


def test_single_negative_is_medium():
    """음성 테스트 1건 → MEDIUM."""
    assert assess_risk(_sig(negative_count=1)) == RiskLevel.SANITY


def test_chaining_only_is_medium():
    """체이닝만 있어도 → MEDIUM."""
    assert assess_risk(_sig(chain_depth=1)) == RiskLevel.SANITY


def test_mutating_and_auth_is_high():
    """변경 + 인증 보호 동시 → HIGH."""
    assert assess_risk(_sig(mutating=True, auth_protected=True)) == RiskLevel.REGRESSION


def test_two_negatives_is_high():
    """음성 2건 이상 → HIGH."""
    assert assess_risk(_sig(negative_count=2)) == RiskLevel.REGRESSION


def test_long_scenario_is_high():
    """긴 시나리오(>=6 step) → HIGH."""
    assert assess_risk(_sig(mutating=True, step_count=6)) == RiskLevel.REGRESSION


def test_deep_chaining_is_high():
    """깊은 체이닝(>=3) → HIGH."""
    assert assess_risk(_sig(chain_depth=3)) == RiskLevel.REGRESSION


def test_destructive_is_high_at_least():
    """파괴적(DELETE)이면 최소 HIGH (인증/음성 없을 때)."""
    assert assess_risk(_sig(mutating=True, destructive=True)) == RiskLevel.REGRESSION


def test_destructive_with_auth_is_critical():
    """파괴적 + 인증 보호 → CRITICAL."""
    assert assess_risk(
        _sig(mutating=True, destructive=True, auth_protected=True)
    ) == RiskLevel.FULL_SUITE


def test_destructive_with_negative_is_critical():
    """파괴적 + 음성 테스트 → CRITICAL."""
    assert assess_risk(
        _sig(mutating=True, destructive=True, negative_count=1)
    ) == RiskLevel.FULL_SUITE


def test_auth_bypass_probe_on_write_is_critical():
    """인증 보호된 변경 자원에 인증 우회 탐침 → CRITICAL."""
    assert assess_risk(
        _sig(mutating=True, auth_protected=True, probes_auth=True, negative_count=1)
    ) == RiskLevel.FULL_SUITE