"""시나리오 Agent의 LangGraph 그래프 정의.

그래프 흐름:

    START
      → intent_parser
        ├─(자연어 모드)─→ planner ─→ chainer ─→ dedup ─→ validator ─→ risk ─→ END
        └─(추천 모드)──→ recommender ─→ planner ─→ chainer ─→ dedup ─→ validator ─→ risk ─→ END

설계 결정:
1. build_graph(llm)이 LLM 클라이언트를 받아 노드들에 주입.
2. LLM이 필요 없는 노드(intent_parser, recommender, validator, risk, dedup)는 plain 함수.
3. 컴파일된 그래프는 모듈 레벨에서 만들지 않음 (LLM 클라이언트가 필요하므로).

구현 상태:
- intent_parser: stub
- recommender:   실제 구현 (LLM 없음, 규칙 기반). api_inventory + existing_test_cases를
                 보고 커버리지 갭(coverage_gaps)을 도출해 planner 입력으로 넘김.
- planner:       실제 구현 (Claude 호출)
- chainer:       실제 구현 (Claude 호출)
- dedup:         실제 구현 + 연결 완료 (LLM 없음). existing_test_cases와 비교해
                 중복 step에 duplicate=True 플래그. final_scenarios를 비파괴적으로 갱신.
- validator:     실제 구현 (LLM 없음, 비파괴적). 스키마/체이닝 경로 정합성 검증
- risk:          실제 구현 (LLM 없음, 규칙 기반)

NOTE: dedup은 chained_variables가 채워진 뒤(body 주입 필드까지 봐야 매칭) 돌아야 하므로
      chainer 다음에 둔다. validator/risk는 duplicate 플래그와 무관하게 final_scenarios만
      읽으므로 dedup 뒤 순서는 영향 없음.
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from app.agents.scenario.nodes._stubs import (
    intent_parser_node,
    route_after_intent,
)
from app.agents.scenario.nodes.chainer import make_chainer_node
from app.agents.scenario.nodes.dedup import dedup_node
from app.agents.scenario.nodes.planner import make_planner_node
from app.agents.scenario.nodes.recommender import recommender_node
from app.agents.scenario.nodes.risk import risk_node
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
    graph.add_node("risk", risk_node)

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
    graph.add_edge("validator", "risk")
    graph.add_edge("risk", END)

    return graph