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

responses[]의 category는 백엔드가 파생시키는 커스텀 필드라 대소문자 차이/누락 가능성이 있다.
_category()가 이를 흡수한다: 명시되면 대문자로 정규화, 없으면 statusCode로 추론(2xx=SUCCESS).
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


def _unique_ints(values: Any) -> list[int]:
    """int로 변환 가능한 값만 추려 순서 보존 중복 제거."""
    out = [c for c in (_to_int(x) for x in values) if c is not None]
    return list(dict.fromkeys(out))


def _category(r: dict) -> str | None:
    """response 항목의 category.

    - 명시돼 있으면 대문자로 정규화 (대소문자 차이 흡수).
    - 없으면 statusCode로 추론: 2xx → SUCCESS, 그 외 → ERROR.
    - statusCode도 없으면 None.
    """
    cat = r.get("category")
    if isinstance(cat, str):
        return cat.upper()
    code = _to_int(r.get("statusCode"))
    if code is None:
        return None
    return "SUCCESS" if 200 <= code < 300 else "ERROR"


def success_schema(response_schema: Any) -> dict[str, Any] | None:
    """체이닝/검증에 쓸 '성공 응답' schema.

    - 신 형태: responses[] 중 category=="SUCCESS"인 첫 항목의 schema
    - 구 형태: 그 dict 자체를 성공 schema로 간주
    """
    if not isinstance(response_schema, dict):
        return None
    if _is_new_form(response_schema):
        for r in response_schema.get("responses", []) or []:
            if isinstance(r, dict) and _category(r) == "SUCCESS":
                sch = r.get("schema")
                return sch if isinstance(sch, dict) else None
        return None
    return response_schema


def expected_status_codes(response_schema: Any) -> list[int]:
    """정상 케이스 기대 status code 목록. 정보가 없으면 [200]."""
    if isinstance(response_schema, dict) and _is_new_form(response_schema):
        codes = response_schema.get("expectedStatusCodes")
        if isinstance(codes, list):
            out = _unique_ints(codes)
            if out:
                return out
        # expectedStatusCodes가 없으면 responses의 SUCCESS에서 추출
        out = _unique_ints(
            r.get("statusCode")
            for r in response_schema.get("responses", []) or []
            if isinstance(r, dict) and _category(r) == "SUCCESS"
        )
        if out:
            return out
    return [200]


def error_responses(response_schema: Any) -> list[dict[str, Any]]:
    """category=="ERROR"인 응답 목록 (신 형태에서만; 구 형태는 빈 리스트)."""
    if isinstance(response_schema, dict) and _is_new_form(response_schema):
        return [
            r
            for r in response_schema.get("responses", []) or []
            if isinstance(r, dict) and _category(r) == "ERROR"
        ]
    return []


def error_status_codes(response_schema: Any) -> list[int]:
    """예외 케이스용 status code 목록. 없으면 []."""
    if isinstance(response_schema, dict) and _is_new_form(response_schema):
        codes = response_schema.get("errorStatusCodes")
        if isinstance(codes, list):
            out = _unique_ints(codes)
            if out:
                return out
        return _unique_ints(r.get("statusCode") for r in error_responses(response_schema))
    return []