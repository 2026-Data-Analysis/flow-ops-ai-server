from app.agents.testcase.state import TestCaseAgentState
from app.core.risk import RiskSignals, assess_risk
from app.schemas.testcase import DraftType, TestCaseDraft

_MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
_NEGATIVE_TYPES = {
    DraftType.VALIDATION, DraftType.EDGE_CASE,
    DraftType.FAILURE_HANDLING, DraftType.AUTHORIZATION,
}

def risk_node(state: TestCaseAgentState) -> dict:
    drafts = state.get("drafts", [])
    if not drafts:
        return {}
    request = state["request"]
    apis_by_id = {api.apiId: api for api in request.apis}
    updated = []
    for draft in drafts:
        api = apis_by_id.get(draft.apiId)
        signals = RiskSignals(
            mutating=api.method.upper() in _MUTATING_METHODS if api else False,
            destructive=api.method.upper() == "DELETE" if api else False,
            auth_protected=api.authRequired if api else False,
            probes_auth=draft.type == DraftType.AUTHORIZATION,
            negative_count=1 if draft.type in _NEGATIVE_TYPES else 0,
            chain_depth=1,
            step_count=1,
        )
        level = assess_risk(signals)
        updated.append(draft.model_copy(update={"risk_level": level}))
    return {"drafts": updated}
