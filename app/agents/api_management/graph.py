"""API Management Agent LangGraph 그래프.

그래프 흐름:
    START → intent_parser → api_fetcher → responder → END

intent_parser: 사용자 메시지 → 검색 조건 추출 (LLM)
api_fetcher:   검색 조건 → 서버 API 목록 요청 (HTTP, LLM 없음)
responder:     API 목록 → 응답 구성 (LLM)
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from app.agents.api_management.nodes import (
    api_fetcher_node,
    make_intent_parser_node,
    make_responder_node,
)
from app.agents.api_management.state import APIManagementState
from app.llm import LLMClient


def build_graph(llm: LLMClient) -> StateGraph:
    graph = StateGraph(APIManagementState)

    graph.add_node("intent_parser", make_intent_parser_node(llm))
    graph.add_node("api_fetcher", api_fetcher_node)
    graph.add_node("responder", make_responder_node(llm))

    graph.add_edge(START, "intent_parser")
    graph.add_edge("intent_parser", "api_fetcher")
    graph.add_edge("api_fetcher", "responder")
    graph.add_edge("responder", END)

    return graph