# FlowOps AI Server — 폴더 구조 설계

LangGraph + Claude(Anthropic) 기반 멀티 에이전트 AI 서버.
시나리오 테스트 Agent 구현을 위해 전체 구조 안에서 명확한 경계를 가진 모듈로 설계.

## 디렉터리 트리

```
app/
├── __init__.py
├── main.py                          # FastAPI 진입점, 라우터 등록
│
├── api/                             # FastAPI 라우터 (백엔드 ↔ AI 서버 인터페이스)
│   ├── __init__.py
│   ├── deps.py                      # 공통 의존성 (LLM 클라이언트, 메모리 등)
│   └── v1/
│       ├── __init__.py
│       ├── scenario.py              # POST /v1/agents/scenario/generate 등
│       ├── testcase.py              # 다른 팀원: 테스트 케이스 생성 엔드포인트
│       ├── incident.py              # 다른 팀원: 장애 대응 엔드포인트
│       └── orchestrator.py          # 다른 팀원: 통합 진입점
│
├── core/                            # 프레임워크 무관한 공통 코드
│   ├── __init__.py
│   ├── config.py                    # 환경변수, 모델 설정 (pydantic-settings)
│   ├── logging.py                   # 구조화 로깅
│   └── exceptions.py                # 도메인 예외 정의
│
├── schemas/                         # Pydantic 스키마 (요청·응답·내부 모델)
│   ├── __init__.py
│   ├── api_spec.py                  # APIEndpoint, RequestSchema, ResponseSchema
│   ├── scenario.py                  # ScenarioStep, Scenario, ChainedVariable 등
│   ├── testcase.py                  # TestCase (다른 Agent에서도 참조)
│   └── common.py                    # 공통 enum, 응답 래퍼
│
├── llm/                             # LLM 추상화 계층 (벤더 종속 코드 격리)
│   ├── __init__.py
│   ├── base.py                      # LLMClient 프로토콜 (다른 모델 추가 대비)
│   ├── anthropic_client.py          # Claude 호출 구현
│   └── prompts/
│       ├── __init__.py
│       ├── scenario_planner.py      # 시나리오 플래너 프롬프트
│       ├── scenario_recommender.py  # 시나리오 추천기 프롬프트
│       └── response_chainer.py      # Response Chaining 프롬프트
│
├── memory/                          # Shared Memory 추상화
│   ├── __init__.py
│   ├── base.py                      # SharedMemory 인터페이스
│   ├── in_memory.py                 # 개발용 인메모리 구현
│   └── postgres.py                  # (추후) PostgreSQL 구현
│
├── agents/                          # LangGraph 에이전트 정의
│   ├── __init__.py
│   ├── state.py                     # 공통 AgentState (TypedDict)
│   ├── orchestrator/                # 다른 팀원 영역
│   │   └── __init__.py
│   ├── testcase/                    # 다른 팀원 영역
│   │   └── __init__.py
│   ├── incident/                    # 다른 팀원 영역
│   │   └── __init__.py
│   └── scenario/                    # ★ 내가 구현할 영역
│       ├── __init__.py
│       ├── graph.py                 # LangGraph 그래프 정의 (StateGraph)
│       ├── state.py                 # ScenarioAgentState (TypedDict)
│       ├── nodes/                   # 그래프의 각 노드 (단일 책임 함수)
│       │   ├── __init__.py
│       │   ├── intent_parser.py     # 사용자 입력 의도 분류 (생성/추천)
│       │   ├── planner.py           # 시나리오 플래너: 흐름 설계
│       │   ├── chainer.py           # Response Chainer: 변수 매핑 생성
│       │   ├── recommender.py       # 시나리오 추천기: 누락 탐지
│       │   └── validator.py         # 생성 결과 검증 (스키마 일치 확인)
│       └── tools/                   # 노드 내부에서 쓰는 헬퍼
│           ├── __init__.py
│           ├── api_indexer.py       # Shared Memory에서 API 목록 조회
│           └── jsonpath_helper.py   # 응답값 경로 추출 유틸
│
└── tests/                           # pytest
    ├── __init__.py
    ├── conftest.py
    └── agents/
        └── scenario/
            ├── test_planner.py
            ├── test_chainer.py
            ├── test_recommender.py
            └── test_graph.py        # 그래프 통합 테스트
```

## 설계 원칙

1. **계층 분리**: `api → agents → llm/memory` 의 단방향 의존.
2. **벤더 독립**: LLM 호출은 `llm/` 안에 격리하여 추후 OpenAI 비교 시 교체 용이.
3. **노드 단일 책임**: `agents/scenario/nodes/` 안의 각 파일은 LangGraph 노드 1개 = 함수 1개.
4. **팀 협업**: `agents/` 하위 폴더로 에이전트별 영역을 분리해 머지 충돌 최소화.
5. **공통 스키마**: `schemas/` 는 모든 에이전트가 공유 (특히 `APIEndpoint`, `TestCase`).

## 시나리오 Agent의 LangGraph 흐름

```
START
  → intent_parser     (자연어/추천요청 분류)
  → planner           (API 시퀀스 설계)
  → chainer           (변수 매핑 생성)
  → validator         (스키마 검증)
  → END
```

추천 모드일 경우:
```
START
  → intent_parser
  → recommender       (이력 기반 부족 시나리오 도출)
  → planner           (각 추천 시나리오를 실제 시퀀스로 확장)
  → chainer
  → validator
  → END
```
