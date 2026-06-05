"""response_spec 헬퍼 테스트.

구 형태(단일 JSON Schema)와 신 형태(responses[] 요약)를 모두
일관되게 해석하는지 검증한다.

배치 위치: tests/core/test_response_spec.py
"""

from __future__ import annotations

from app.core.response_spec import (
    error_responses,
    error_status_codes,
    expected_status_codes,
    success_schema,
)

# 구 형태: 단일 성공 JSON Schema
OLD = {"type": "object", "properties": {"userId": {"type": "integer"}}}

# 신 형태: OpenAPI responses 요약
NEW = {
    "expectedStatusCodes": [200, 201],
    "errorStatusCodes": [400, 404],
    "responses": [
        {
            "statusCode": "201",
            "category": "SUCCESS",
            "description": "Created",
            "schema": {"type": "object", "properties": {"orderId": {"type": "integer"}}},
            "sampleBody": {"orderId": 1},
        },
        {
            "statusCode": "400",
            "category": "ERROR",
            "description": "Bad Request",
            "schema": {},
            "sampleBody": {},
        },
    ],
}

# expectedStatusCodes/errorStatusCodes 없이 responses만 있는 신 형태
NEW_MINIMAL = {
    "responses": [
        {"statusCode": 200, "category": "SUCCESS", "schema": {"type": "object"}},
        {"statusCode": 409, "category": "ERROR", "schema": {}},
    ]
}


# --- 구 형태 ---

def test_old_form_success_schema_is_itself():
    assert success_schema(OLD) == OLD


def test_old_form_expected_defaults_to_200():
    assert expected_status_codes(OLD) == [200]


def test_old_form_has_no_errors():
    assert error_status_codes(OLD) == []
    assert error_responses(OLD) == []


# --- 신 형태 ---

def test_new_form_success_schema_from_success_response():
    assert success_schema(NEW) == {"type": "object", "properties": {"orderId": {"type": "integer"}}}


def test_new_form_expected_codes():
    assert expected_status_codes(NEW) == [200, 201]


def test_new_form_error_codes():
    assert error_status_codes(NEW) == [400, 404]


def test_new_form_error_responses():
    errs = error_responses(NEW)
    assert len(errs) == 1
    assert errs[0]["statusCode"] == "400"


# --- 신 형태(최소: 명시 코드 목록 없이 responses만) ---

def test_new_minimal_falls_back_to_responses():
    assert expected_status_codes(NEW_MINIMAL) == [200]
    assert error_status_codes(NEW_MINIMAL) == [409]
    assert success_schema(NEW_MINIMAL) == {"type": "object"}


# --- None/비정상 입력 안전성 ---

def test_none_is_safe():
    assert success_schema(None) is None
    assert expected_status_codes(None) == [200]
    assert error_status_codes(None) == []
    assert error_responses(None) == []