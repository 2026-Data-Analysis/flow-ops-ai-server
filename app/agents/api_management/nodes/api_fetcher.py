"""API Fetcher 노드.

search_query 조건으로 서버에 API 목록을 요청.
실제 서버 URL은 context["api_server_url"]에서 가져옴.
"""

from __future__ import annotations

import logging

import httpx

from app.agents.api_management.state import APIManagementError, APIManagementState

logger = logging.getLogger(__name__)


def api_fetcher_node(state: APIManagementState) -> dict:
    if any(e["node"] == "intent_parser" for e in state.get("errors", [])):
        return {}

    context = state.get("context", {})
    search_query = state.get("search_query", {})

    api_server_url = context.get("api_server_url")
    project_id = context.get("projectId") or context.get("project_id")
    app_id = context.get("applicationId")

    if not api_server_url:
        return {
            "errors": [APIManagementError(
                node="api_fetcher",
                code="MISSING_API_SERVER_URL",
                message="context에 api_server_url이 필요합니다.",
            )]
        }

    # 쿼리 파라미터 조립
    params: dict = {}
    if project_id:
        params["projectId"] = project_id
    if app_id:
        params["applicationId"] = app_id
    if search_query.get("keyword"):
        params["keyword"] = search_query["keyword"]
    if search_query.get("tag"):
        params["tag"] = search_query["tag"]

    try:
        response = httpx.get(
            f"{api_server_url}",
            params=params,
            timeout=10.0,
        )
        response.raise_for_status()
        logger.info("api_fetcher raw response: %s", response.text[:500])
        api_list = response.json()
        logger.info("api_fetcher parsed type=%s", type(api_list).__name__)

        # 서버 응답 구조 로깅 (디버깅용)
        logger.info("api_fetcher raw response type=%s keys=%s",
            type(api_list).__name__,
            list(api_list.keys()) if isinstance(api_list, dict) else "N/A"
        )

        if isinstance(api_list, dict):
            logger.info("api_fetcher dict keys=%s", list(api_list.keys()))
            # 가능한 키 순서대로 탐색
            inner = (
                api_list.get("data")
                or api_list.get("result")
                or {}
            )
            # data 안에 content가 있는 페이지네이션 구조
            if isinstance(inner, dict):
                api_list = (
                    inner.get("content")
                    or inner.get("items")
                    or inner.get("apis")
                    or []
                )
            elif isinstance(inner, list):
                api_list = inner
            else:
                api_list = []

        if not isinstance(api_list, list):
            logger.warning("api_fetcher: unexpected response format, wrapping as empty list")
            api_list = []

        return {"raw_api_list": api_list}
    except httpx.HTTPStatusError as e:
        logger.error("api_fetcher HTTP error: %s", e)
        return {
            "errors": [APIManagementError(
                node="api_fetcher",
                code="HTTP_ERROR",
                message=f"서버 응답 오류: {e.response.status_code} — {e.response.text}",  # ✅ 응답 본문 추가
            )]
        }
    except Exception as e:
        logger.exception("api_fetcher failed")
        return {
            "errors": [APIManagementError(
                node="api_fetcher",
                code="FETCH_FAILED",
                message=str(e),
            )]
        }