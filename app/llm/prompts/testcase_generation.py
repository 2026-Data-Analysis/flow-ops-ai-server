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
