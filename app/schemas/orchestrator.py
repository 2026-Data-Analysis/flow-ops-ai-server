"""Orchestrator Agent 스키마."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class OrchestratorRequest(BaseModel):
    """Orchestrator 챗봇 입력."""

    project_id: str
    user_prompt: str = Field(description="사용자 자연어 요청. 예: '로그 분석하고 테스트 케이스 만들어줘'")

    # Agent별 입력에 필요한 추가 컨텍스트 (선택)
    context: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Agent 실행에 필요한 부가 정보.\n"
            "- api_inventory: APIInventory dict (testcase/scenario Agent용)\n"
            "- raw_log: str (incident Agent용)\n"
            "- log_entries: list (incident Agent용)\n"
            "- service_name: str (incident Agent용)\n"
            "- occurred_at: str ISO 8601 (incident Agent용)\n"
            "- base_url: str (testcase Agent용)\n"
            "- env_name: str (testcase Agent용)"
        ),
    )


class AgentResultItem(BaseModel):
    """단일 Agent 실행 결과 (응답에 포함)."""

    agent_type: str = Field(description="실행된 Agent 타입: testcase | scenario | incident")
    success: bool
    data: Any | None = None
    error_message: str | None = None


class OrchestratorResult(BaseModel):
    """Orchestrator 출력."""

    dispatched_agents: list[str] = Field(
        description="실행된 Agent 이름 목록 (실행 순서 보존). 서버가 어떤 Agent가 쓰였는지 파악 가능."
    )
    agent_results: list[AgentResultItem] = Field(
        description="각 Agent의 실행 결과"
    )
    summary: str = Field(description="전체 실행 결과 자연어 요약")
