import json
from string import Template

SYSTEM_PROMPT = """\
You are a senior QA engineer specializing in API test case design.
Generate thorough, structured test cases that cover all critical scenarios for the given API endpoint.
Always call the provided tool and pass the 'drafts' field as a JSON array of objects — never as a string, never wrapped in markdown fences.
"""

GENERATION_PROMPT_TEMPLATE = """\
Generate test cases for the following API endpoint.

## API Specification
- API ID: ${api_id}
- Method: ${method}
- Path: ${path}
- Auth Required: ${auth_required}
- Request Schema: ${request_schema}
- Response Schema: ${response_schema}
- Expected Status Codes: ${expected_status_codes}
- Error Status Codes: ${error_status_codes}
- Error Codes: ${error_codes}

## Domain APIs (참고용)
같은 도메인의 API 목록. path parameter에 유효한 ID가 필요할 때
목록 조회 API(GET)를 찾아서 requestSpec에 반영할 것.
${domain_apis}

## Context
- App: ${app_name}
- Environment: ${env_name} (${base_url})
- Additional Context: ${context_summary}
- Valid Identifiers: ${valid_identifiers}
- User Instruction: ${user_instruction}

## Specific Instructions (Highest Priority)
1. User Instruction: If a 'User Instruction' is provided above, you MUST generate test cases that explicitly fulfill this natural language scenario.
2. Valid Identifiers: If 'Valid Identifiers' are provided, you MUST use these exact real values for path parameters, query parameters, or body fields when generating HAPPY_PATH or positive test cases. Do not invent fake IDs if real ones are provided.

## Response Schema Guide
If Response Schema contains expectedStatusCodes/errorStatusCodes/responses:
- Use expectedStatusCodes for HAPPY_PATH expectedSpec.statusCode
- Use errorStatusCodes and responses[].category=="ERROR" for exception test cases
- Use responses[].description, schema, sampleBody as basis for expectedSpec and assertionSpec

## Requirements
Generate 5-8 test cases. Use ONLY these exact type values (no other values allowed):
HAPPY_PATH, VALIDATION, FAILURE_HANDLING, EDGE_CASE, AUTHORIZATION, PERFORMANCE
- HAPPY_PATH: Normal successful request with valid inputs
- VALIDATION: Invalid/missing/wrong-type inputs
- FAILURE_HANDLING: Server errors, timeouts, unexpected failures
- EDGE_CASE: Boundary values, empty arrays, max-length strings, null fields
- AUTHORIZATION: Missing/expired/insufficient-permission tokens (only if authRequired=true)
- PERFORMANCE: High-load or large-payload scenarios

## Language
Write title and description in Korean.
- title example: "유효한 자격증명으로 로그인 성공"
- description example: "올바른 이메일과 비밀번호로 로그인 시 200 응답과 토큰 반환 확인"

## Negative Test Case Rules (CRITICAL)
When generating negative/exception test cases, DO NOT hardcode invalid values directly into the API path string.
Instead, you MUST place the invalid values in the exact parameter fields where the error occurs:
  - Path parameter errors -> 'requestSpec.pathParams'
  - Query parameter errors -> 'requestSpec.queryParams'
  - Body validation errors -> 'requestSpec.body'
  - Header/Auth errors -> 'requestSpec.headers'

Example:
  BAD:  "path": "/apps//scenarios"
  GOOD: "path": "/apps/{appId}/scenarios", "requestSpec": {"pathParams": {"appId": ""}}

  BAD:  "description": "잘못된 바디로 요청", requestSpec 없음
  GOOD: "requestSpec": {"body": {"email": "not-an-email"}}

## Path Parameter Type Rules (CRITICAL)
Path parameters that represent IDs (e.g. executionId, orderId, appId, userId) MUST always be numeric (Long type).
- GOOD: "pathParams": {"executionId": 99999}
- BAD:  "pathParams": {"executionId": "nonexistent-exec-99999"}
- GOOD: "pathParams": {"executionId": 0}  (for invalid/nonexistent cases)
- GOOD: "pathParams": {"executionId": 999999999}  (for nonexistent cases)
Do NOT use string values for ID path parameters under any circumstances.

## Output Fields
Fill every field below for each test case. Do NOT leave expectedSpec null.

**requestSpec** — concrete values to send:
{"method": "POST", "pathParams": {"userId": 1}, "queryParams": {"page": 1}, "body": {"email": "test@example.com", "password": "secret123"}}

**expectedSpec** — what the response should look like:
{"statusCode": 200, "body": {"id": 1, "email": "test@example.com"}, "errorMessage": null}

For error cases use the appropriate status code and fill errorMessage:
{"statusCode": 400, "body": {"error": "email is required"}, "errorMessage": "Validation failed: email must not be blank"}

**assertionSpec** — specific assertions to verify:
{"statusCode": 200, "bodyContains": ["id", "email"], "bodyEquals": {"email": "test@example.com"}, "headerContains": {"Content-Type": "application/json"}}

## Output Format (STRICT)
- Call the tool with the `drafts` key set to a **JSON array** of test case objects.
- Do NOT serialize the array as a string value.
- Do NOT wrap any value in markdown fences.
- Do NOT include explanatory text outside the tool call.
- Do NOT use code expressions in any JSON value.

  BAD:  "appId": "app-" + "a".repeat(250)
  GOOD: "appId": "app-aaaaaaaaaaaaaaaa..."
"""


def build_generation_prompt(
    api_id: str,
    method: str,
    path: str,
    auth_required: bool,
    request_schema: dict | None,
    response_schema: dict | None,
    app_name: str,
    env_name: str,
    base_url: str,
    context_summary: str | None,
    user_instruction: str | None = None,
    valid_identifiers: dict | None = None,
    domain_apis: list | None = None,
    expected_status_codes: list | None = None,
    error_status_codes: list | None = None,
    error_codes: list | None = None,
) -> str:
    # ✅ None이면 "없음" — 중괄호 없는 문자열
    req_schema_str = json.dumps(request_schema, ensure_ascii=False, indent=2) if request_schema else "없음"
    res_schema_str = json.dumps(response_schema, ensure_ascii=False, indent=2) if response_schema else "없음"
    valid_ids_str = json.dumps(valid_identifiers, ensure_ascii=False) if valid_identifiers else "없음"
    domain_apis_str = (
        "\n".join(f"- [{a.method}] {a.path}" for a in domain_apis)
        if domain_apis else "없음"
    )
    expected_status_codes_str = json.dumps(expected_status_codes) if expected_status_codes else "없음"
    error_status_codes_str = json.dumps(error_status_codes) if error_status_codes else "없음"
    error_codes_str = json.dumps(error_codes, ensure_ascii=False) if error_codes else "없음"

    # ✅ string.Template 사용 — {중괄호} 충돌 완전 차단
    # $변수명 패턴만 치환, { } 는 건드리지 않음
    tmpl = Template(GENERATION_PROMPT_TEMPLATE)
    return tmpl.substitute(
        api_id=api_id,
        method=method.upper(),
        path=path,
        auth_required=auth_required,
        request_schema=req_schema_str,
        response_schema=res_schema_str,
        app_name=app_name,
        env_name=env_name,
        base_url=base_url,
        context_summary=context_summary or "No additional context provided.",
        user_instruction=user_instruction or "None",
        valid_identifiers=valid_ids_str,
        domain_apis=domain_apis_str,
        expected_status_codes=expected_status_codes_str,
        error_status_codes=error_status_codes_str,
        error_codes=error_codes_str,
    )
