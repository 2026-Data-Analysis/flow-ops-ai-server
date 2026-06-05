"""response_schema 해석 유틸 (신/구 형태 모두 지원).

APIEndpoint.response_schema는 두 형태를 가질 수 있다:

[구 형태] 단일 성공 응답 JSON Schema
    {"type": "object", "properties": {"userId": {"type": "integer"}}}

[신 형태] OpenAPI responses 요약 (회의 Item 1)
    {
      "expectedStatusCodes": [200, 201],
      "errorStatusCodes": [400, 401, 404, 409, 500],
      "responses": [
        {"statusCode": "201", "category": "SUCCESS", "description": "Created",
         "schema": {...}, "sampleBody": {...}},
        {"statusCode": "400", "category": "ERROR", "description": "Bad Request",
         "schema": {...}, "sampleBody": {...}}
      ]
    }

이 모듈은 두 형태를 모두 받아 일관된 값을 돌려준다 (backward-compatible).
시나리오/테스트 양쪽 소비부(chainer/validator/planner + testcase)에서 동일하게 재사용한다.
"""

from __future__ import annotations

from typing import Any


def _is_new_form(rs: Any) -> bool:
    """신 형태(responses/expectedStatusCodes/errorStatusCodes 키 보유) 여부."""
    return isinstance(rs, dict) and (
        "responses" in rs or "expectedStatusCodes" in rs or "errorStatusCodes" in rs
    )


def _to_int(v: Any) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def success_schema(response_schema: Any) -> dict[str, Any] | None:
    """체이닝/검증에 쓸 '성공 응답' schema.

    - 신 형태: responses[] 중 category=="SUCCESS"인 첫 항목의 schema
    - 구 형태: 그 dict 자체를 성공 schema로 간주
    """
    if not isinstance(response_schema, dict):
        return None
    if _is_new_form(response_schema):
        for r in response_schema.get("responses", []) or []:
            if isinstance(r, dict) and r.get("category") == "SUCCESS":
                sch = r.get("schema")
                return sch if isinstance(sch, dict) else None
        return None
    return response_schema


def expected_status_codes(response_schema: Any) -> list[int]:
    """정상 케이스 기대 status code 목록. 정보가 없으면 [200]."""
    if isinstance(response_schema, dict) and _is_new_form(response_schema):
        codes = response_schema.get("expectedStatusCodes")
        if isinstance(codes, list):
            out = [c for c in (_to_int(x) for x in codes) if c is not None]
            if out:
                return out
        # expectedStatusCodes가 없으면 responses의 SUCCESS에서 추출
        out = [
            c
            for c in (
                _to_int(r.get("statusCode"))
                for r in response_schema.get("responses", []) or []
                if isinstance(r, dict) and r.get("category") == "SUCCESS"
            )
            if c is not None
        ]
        if out:
            return out
    return [200]


def error_responses(response_schema: Any) -> list[dict[str, Any]]:
    """category=="ERROR"인 응답 목록 (신 형태에서만; 구 형태는 빈 리스트)."""
    if isinstance(response_schema, dict) and _is_new_form(response_schema):
        return [
            r
            for r in response_schema.get("responses", []) or []
            if isinstance(r, dict) and r.get("category") == "ERROR"
        ]
    return []


def error_status_codes(response_schema: Any) -> list[int]:
    """예외 케이스용 status code 목록. 없으면 []."""
    if isinstance(response_schema, dict) and _is_new_form(response_schema):
        codes = response_schema.get("errorStatusCodes")
        if isinstance(codes, list):
            out = [c for c in (_to_int(x) for x in codes) if c is not None]
            if out:
                return out
        return [
            c
            for c in (_to_int(r.get("statusCode")) for r in error_responses(response_schema))
            if c is not None
        ]
    return []