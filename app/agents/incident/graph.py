"""Incident Response Agent LangGraph 그래프.

그래프 흐름:

    START → log_parser → analyzer → reporter → END

설계 결정:
1. log_parser는 LLM 없이 규칙 기반 처리 (비용 절약).
2. analyzer / reporter 는 LLM 호출 (make_* 팩토리 패턴 — 기존 Agent와 동일).
3. 에러가 있어도 그래프는 멈추지 않고 흐름을 타며 각 노드가 에러를 확인 후 통과.
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from app.agents.incident.nodes.log_parser import log_parser_node
from app.agents.incident.nodes.analyzer import make_analyzer_node
from app.agents.incident.nodes.reporter import make_reporter_node
from app.agents.incident.state import IncidentAgentState
from app.llm import LLMClient


def build_graph(llm: LLMClient) -> StateGraph:
    graph = StateGraph(IncidentAgentState)

    graph.add_node("log_parser", log_parser_node)
    graph.add_node("analyzer", make_analyzer_node(llm))
    graph.add_node("reporter", make_reporter_node(llm))

    graph.add_edge(START, "log_parser")
    graph.add_edge("log_parser", "analyzer")
    graph.add_edge("analyzer", "reporter")
    graph.add_edge("reporter", END)

    return graph
