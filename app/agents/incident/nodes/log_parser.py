"""Log Parser 노드.

역할:
- raw 로그 문자열을 구조화된 엔트리 리스트로 변환
- 노이즈(헬스체크, 정적 파일 요청 등) 필터링
- 이후 analyzer가 집중할 수 있도록 에러/경고 중심으로 정제

LLM 없이 규칙 기반으로 처리 (비용 절약 + 결정론적).
구조화가 불가능한 경우 raw를 그대로 단일 엔트리로 넘김.
"""

from __future__ import annotations

import re
from datetime import datetime

from app.agents.incident.state import IncidentAgentState

# 필터링할 노이즈 패턴 (정규식)
_NOISE_PATTERNS: list[re.Pattern] = [
    re.compile(r"GET /health", re.IGNORECASE),
    re.compile(r"GET /favicon\.ico", re.IGNORECASE),
    re.compile(r"GET /static/", re.IGNORECASE),
]

# 심각도 키워드 매핑 (높은 우선순위 먼저)
_SEVERITY_MAP: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\b(CRITICAL|FATAL)\b", re.IGNORECASE), "CRITICAL"),
    (re.compile(r"\b(ERROR|Exception|Traceback|SEVERE)\b", re.IGNORECASE), "HIGH"),
    (re.compile(r"\b(WARN|WARNING)\b", re.IGNORECASE), "MEDIUM"),
    (re.compile(r"\b(INFO)\b", re.IGNORECASE), "LOW"),
]

# 타임스탬프 패턴 (ISO 8601 / common log 포맷)
_TIMESTAMP_RE = re.compile(
    r"(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?)"
    r"|(\d{2}/\w{3}/\d{4}:\d{2}:\d{2}:\d{2})"
)


def _detect_severity(line: str) -> str:
    for pattern, level in _SEVERITY_MAP:
        if pattern.search(line):
            return level
    return "UNKNOWN"


def _extract_timestamp(line: str) -> str | None:
    m = _TIMESTAMP_RE.search(line)
    return m.group(0) if m else None


def _is_noise(line: str) -> bool:
    return any(p.search(line) for p in _NOISE_PATTERNS)


def _parse_lines(raw: str) -> list[dict]:
    entries: list[dict] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        if _is_noise(line):
            continue
        entries.append({
            "raw": line,
            "timestamp": _extract_timestamp(line),
            "severity": _detect_severity(line),
        })
    return entries


def log_parser_node(state: IncidentAgentState) -> dict:
    """raw 로그를 구조화 엔트리로 변환."""
    req = state["request"]

    # 이미 구조화된 엔트리가 있으면 그대로 사용
    if req.log_entries:
        entries = []
        for e in req.log_entries:
            d = e.model_dump()
            # level → severity 로 매핑, 없으면 UNKNOWN
            level = (d.get("level") or "").upper()
            severity_map = {
                "ERROR": "HIGH", "FATAL": "CRITICAL", "CRITICAL": "CRITICAL",
                "WARN": "MEDIUM", "WARNING": "MEDIUM", "INFO": "LOW", "DEBUG": "LOW",
            }
            d["severity"] = severity_map.get(level, "UNKNOWN")
            d["raw"] = d.get("message", "")
            entries.append(d)
    elif req.raw_log:
        entries = _parse_lines(req.raw_log)
    else:
        return {
            "errors": [{
                "node": "log_parser",
                "code": "NO_LOG_INPUT",
                "message": "raw_log 또는 log_entries 중 하나는 제공해야 합니다.",
            }]
        }

    # 에러/경고 없으면 알림
    significant = [e for e in entries if e["severity"] in ("CRITICAL", "HIGH", "MEDIUM")]
    if not significant and entries:
        # 전부 INFO/UNKNOWN이면 전체를 넘김 (분석 대상 없다고 판단하지 않음)
        significant = entries

    return {"parsed_log_entries": significant}
