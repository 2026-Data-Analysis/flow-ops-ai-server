SYSTEM_PROMPT = """\
You are a senior QA engineer specializing in API test case design.
Generate thorough, structured test cases that cover all critical scenarios for the given API endpoint.
Always call the provided tool and pass the 'drafts' field as a JSON array of objects — never as a string, never wrapped in markdown fences.
"""

GENERATION_PROMPT_TEMPLATE = """\
Generate test cases for the following API endpoint.

## API Specification
- API ID: {api_id}
- Method: {method}
- Path: {path}
- Auth Required: {auth_required}
- Request Schema: {request_schema}
- Response Schema: {response_schema}

## Context
- App: {app_name}
- Environment: {env_name} ({base_url})
- Additional Context: {context_summary}
- Valid Identifiers: {valid_identifiers}
- User Instruction: {user_instruction}

## Specific Instructions (Highest Priority)
1. User Instruction: If a 'User Instruction' is provided above, you MUST generate test cases that explicitly fulfill this natural language scenario.
2. Valid Identifiers: If 'Valid Identifiers' are provided, you MUST use these exact real values for path parameters, query parameters, or body fields when generating HAPPY_PATH or positive test cases. Do not invent fake IDs if real ones are provided.

## Requirements
Generate 5-8 test cases. Use only these type values:
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
  GOOD: "path": "/apps/{{appId}}/scenarios", "requestSpec": {{"pathParams": {{"appId": ""}}}}

  BAD:  "description": "잘못된 바디로 요청", requestSpec 없음
  GOOD: "requestSpec": {{"body": {{"email": "not-an-email"}}}}

## Output Fields
Fill every field below for each test case. Do NOT leave expectedSpec null.

**requestSpec** — concrete values to send:
```json
{{"method": "POST", "pathParams": {{"userId": 1}}, "queryParams": {{"page": 1}}, "body": {{"email": "test@example.com", "password": "secret123"}}}}
```

**expectedSpec** — what the response should look like:
```json
{{"statusCode": 200, "body": {{"id": 1, "email": "test@example.com"}}, "errorMessage": null}}
```
For error cases use the appropriate status code and fill errorMessage:
```json
{{"statusCode": 400, "body": {{"error": "email is required"}}, "errorMessage": "Validation failed: email must not be blank"}}
```

**assertionSpec** — specific assertions to verify:
```json
{{"statusCode": 200, "bodyContains": ["id", "email"], "bodyEquals": {{"email": "test@example.com"}}, "headerContains": {{"Content-Type": "application/json"}}}}
```

## Output Format (STRICT)
- Call the tool with the `drafts` key set to a **JSON array** of test case objects.
- Do NOT serialize the array as a string value.
- Do NOT wrap any value in markdown fences (```json ... ```).
- Do NOT include explanatory text outside the tool call.
- Do NOT use code expressions in any JSON value.
  Forbidden patterns: + operator, .repeat(), .concat(), ${...}, template literals,
  or any JavaScript/Python expression.
  If you need a boundary-value string, write it out as a literal string.

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
    # ▼ 추가된 파라미터 ▼
    user_instruction: str | None = None,
    valid_identifiers: dict | None = None,
) -> str:
    req_schema_str = json.dumps(request_schema, ensure_ascii=False, indent=2) if request_schema else "{}"
    res_schema_str = json.dumps(response_schema, ensure_ascii=False, indent=2) if response_schema else "{}"
    
    # 파이썬 딕셔너리를 예쁜 JSON 문자열로 변환 (없으면 빈 텍스트)
    valid_ids_str = json.dumps(valid_identifiers, ensure_ascii=False) if valid_identifiers else "None"

    return GENERATION_PROMPT_TEMPLATE.format(
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
        # ▼ 템플릿에 매핑 ▼
        user_instruction=user_instruction or "None",
        valid_identifiers=valid_ids_str,
    )
