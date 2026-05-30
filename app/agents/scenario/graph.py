"""시나리오 Agent의 LangGraph 그래프 정의.

그래프 흐름:

    START
      → intent_parser
        ├─(자연어 모드)─→ planner ─→ chainer ─→ dedup ─→ validator ─→ END
        └─(추천 모드)──→ recommender ─→ planner ─→ chainer ─→ dedup ─→ validator ─→ END

설계 결정:
1. build_graph(llm)이 LLM 클라이언트를 받아 노드들에 주입.
2. dedup: 기존 테스트와 비교해 step.duplicate 플래그 세팅 (LLM 없음).
3. validator: 스키마 정합성/체이닝 경로 검증 (LLM 없음, 비파괴적 — errors에 기록만).
4. 컴파일된 그래프는 모듈 레벨에서 만들지 않음 (LLM 클라이언트가 필요하므로).
   대신 호출 측(엔드포인트 의존성)에서 build_graph(llm).compile() 호출.

구현 상태:
- intent_parser: stub (단순 분기라 유지)
- recommender:   stub (다음 단계)
- planner:       실제 구현 (Claude 호출)
- chainer:       실제 구현 (Claude 호출)
- dedup:         실제 구현 (기존 테스트 대비 중복 플래그)
- validator:     실제 구현 (스키마 정합성 검증)
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from app.agents.scenario.nodes._stubs import (
    intent_parser_node,
    recommender_node,
    route_after_intent,
)
from app.agents.scenario.nodes.chainer import make_chainer_node
from app.agents.scenario.nodes.dedup import dedup_node
from app.agents.scenario.nodes.planner import make_planner_node
from app.agents.scenario.nodes.validator import validator_node
from app.agents.scenario.state import ScenarioAgentState
from app.llm import LLMClient


def build_graph(llm: LLMClient) -> StateGraph:
    """시나리오 Agent 그래프를 빌드해 컴파일 전 상태로 반환.

    Args:
        llm: LLMClient 구현체. planner, chainer 등 LLM이 필요한 노드에 주입됨.

    Returns:
        컴파일되지 않은 StateGraph. 호출 측에서 .compile() 필요.
    """
    graph = StateGraph(ScenarioAgentState)

    # 노드 등록
    graph.add_node("intent_parser", intent_parser_node)
    graph.add_node("recommender", recommender_node)
    graph.add_node("planner", make_planner_node(llm))
    graph.add_node("chainer", make_chainer_node(llm))
    graph.add_node("dedup", dedup_node)
    graph.add_node("validator", validator_node)

    # 엣지 연결
    graph.add_edge(START, "intent_parser")
    graph.add_conditional_edges(
        "intent_parser",
        route_after_intent,
        {
            "recommender": "recommender",
            "planner": "planner",
        },
    )
    graph.add_edge("recommender", "planner")
    graph.add_edge("planner", "chainer")
    graph.add_edge("chainer", "dedup")
    graph.add_edge("dedup", "validator")
    graph.add_edge("validator", END)

    return graph