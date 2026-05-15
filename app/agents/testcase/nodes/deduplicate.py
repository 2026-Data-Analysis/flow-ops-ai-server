from app.agents.testcase.state import TestCaseAgentState
from app.schemas.testcase import (
    DraftType,
    DRAFT_TO_TEST_CASE_TYPE,
    ExistingTestCase,
    TestCaseDraft,
)


def _fingerprint(api_id: str, draft_type: str, request_spec: dict | None) -> frozenset:
    """Rule-based 지문: apiId + type + requestSpec 핵심 필드 조합."""
    keys: set = {("apiId", api_id), ("type", draft_type)}
    if request_spec:
        if "method" in request_spec:
            keys.add(("method", str(request_spec["method"]).upper()))
        body = request_spec.get("body") or {}
        if isinstance(body, dict):
            keys.update(("body_key", k) for k in sorted(body.keys()))
        params = request_spec.get("queryParams") or {}
        if isinstance(params, dict):
            keys.update(("query_key", k) for k in sorted(params.keys()))
    return frozenset(keys)


def _existing_fingerprints(existing: list[ExistingTestCase]) -> set[frozenset]:
    return {
        _fingerprint(tc.apiId, tc.type.value, tc.requestSpec)
        for tc in existing
    }


async def deduplicate(state: TestCaseAgentState) -> dict:
    """existingTestCases와 비교해 중복 플래그를 설정한다."""
    if state.get("error"):
        return state

    seen = _existing_fingerprints(state["request"].existingTestCases)
    drafts: list[TestCaseDraft] = []

    for raw in state["raw_drafts"]:
        try:
            draft_type_str = raw.get("type", "HAPPY_PATH")
            draft_type = DraftType(draft_type_str)
            fp = _fingerprint(
                api_id=raw.get("apiId", ""),
                draft_type=draft_type_str,
                request_spec=raw.get("requestSpec"),
            )
            is_duplicate = fp in seen
            if not is_duplicate:
                seen.add(fp)

            drafts.append(
                TestCaseDraft(
                    apiId=raw.get("apiId", ""),
                    title=raw.get("title", ""),
                    description=raw.get("description", ""),
                    type=draft_type,
                    test_case_type=DRAFT_TO_TEST_CASE_TYPE[draft_type],
                    userRole=raw.get("userRole"),
                    stateCondition=raw.get("stateCondition"),
                    dataVariant=raw.get("dataVariant"),
                    requestSpec=raw.get("requestSpec"),
                    expectedSpec=raw.get("expectedSpec"),
                    assertionSpec=raw.get("assertionSpec"),
                    duplicate=is_duplicate,
                )
            )
        except Exception:
            continue

    return {**state, "drafts": drafts}
