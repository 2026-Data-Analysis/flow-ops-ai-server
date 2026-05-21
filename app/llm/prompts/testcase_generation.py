SYSTEM_PROMPT = """\
You are a senior QA engineer specializing in API test case design.
Generate thorough, structured test cases that cover all critical scenarios for the given API endpoint.
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
) -> str:
    return GENERATION_PROMPT_TEMPLATE.format(
        api_id=api_id,
        method=method.upper(),
        path=path,
        auth_required=auth_required,
        request_schema=request_schema or {},
        response_schema=response_schema or {},
        app_name=app_name,
        env_name=env_name,
        base_url=base_url,
        context_summary=context_summary or "No additional context provided.",
    )
