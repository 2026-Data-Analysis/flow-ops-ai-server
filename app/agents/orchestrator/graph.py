"""Orchestrator Agent LangGraph 그래프.

그래프 흐름:

    START → intent_classifier → dispatcher → aggregator → END

설계 결정:
1. intent_classifier: LLM으로 사용자 의도 분류 → Agent 실행 계획 수립
2. dispatcher: 계획에 따라 각 Agent 그래프를 순서대로 invoke
3. aggregator: 결과 종합 → 자연어 요약 생성 (LLM 없이 규칙 기반)

주의: dispatcher가 testcase/scenario/incident 그래프를 직접 invoke하므로
      build_graph()에 세 그래프 모두 주입 필요.
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.agents.orchestrator.nodes.aggregator import aggregator_node
from app.agents.orchestrator.nodes.dispatcher import make_dispatcher_node
from app.agents.orchestrator.nodes.intent_classifier import make_intent_classifier_node
from app.agents.orchestrator.state import OrchestratorAgentState
from app.llm import LLMClient


def build_graph(
    llm: LLMClient,
    testcase_graph: CompiledStateGraph,
    scenario_graph: CompiledStateGraph,
    incident_graph: CompiledStateGraph,
) -> StateGraph:
    """Orchestrator 그래프 빌드.

    Args:
        llm: LLM 클라이언트 (intent_classifier, 그리고 testcase agent 내부에서 사용)
        testcase_graph: 컴파일된 TestCase Agent 그래프
        scenario_graph: 컴파일된 Scenario Agent 그래프
        incident_graph: 컴파일된 Incident Agent 그래프
    """
    graph = StateGraph(OrchestratorAgentState)

    graph.add_node("intent_classifier", make_intent_classifier_node(llm))
    graph.add_node(
        "dispatcher",
        make_dispatcher_node(testcase_graph, scenario_graph, incident_graph, llm),
    )
    graph.add_node("aggregator", aggregator_node)

    graph.add_edge(START, "intent_classifier")
    graph.add_edge("intent_classifier", "dispatcher")
    graph.add_edge("dispatcher", "aggregator")
    graph.add_edge("aggregator", END)

    return graph
