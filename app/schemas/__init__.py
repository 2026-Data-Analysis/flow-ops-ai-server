"""FlowOps 스키마 패키지.

외부 모듈은 `from app.schemas import Scenario, ...` 형태로 임포트한다.
"""

from .api_spec import APIEndpoint, APIInventory, AuthScheme, ParameterSpec
from .common import AgentResponse, HttpMethod, RiskLevel, TokenUsage
from .scenario import (
    ChainedVariable,
    Scenario,
    ScenarioGenerationMode,
    ScenarioGenerationRequest,
    ScenarioGenerationResult,
    ScenarioMeta,
    ScenarioStep,
    VariableSource,
)
from .testcase import TestCase, TestCaseType

__all__ = [
    # common
    "AgentResponse",
    "HttpMethod",
    "RiskLevel",
    "TokenUsage",
    # api_spec
    "APIEndpoint",
    "APIInventory",
    "AuthScheme",
    "ParameterSpec",
    # testcase
    "TestCase",
    "TestCaseType",
    # scenario
    "ChainedVariable",
    "Scenario",
    "ScenarioGenerationMode",
    "ScenarioGenerationRequest",
    "ScenarioGenerationResult",
    "ScenarioMeta",
    "ScenarioStep",
    "VariableSource",
]
