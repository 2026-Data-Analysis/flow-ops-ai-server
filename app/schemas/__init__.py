"""FlowOps 스키마 패키지.

외부 모듈은 `from app.schemas import Scenario, ...` 형태로 임포트한다.
"""
from .testcase import DraftType, TestCaseType, TestCase
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
from .testcase import (
    ApiSpec,
    DraftType,
    EnvironmentInfo,
    ExistingTestCase,
    FailureContext,
    GenerationContext,
    ProjectInfo,
    RequestMetadata,
    TestCase,
    TestCaseDraft,
    TestCaseGenerationRequest,
    TestCaseGenerationResponse,
    TestCaseType,
)

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
    # testcase — shared
    "TestCase",
    "TestCaseType",
    # testcase — generation agent
    "ApiSpec",
    "DraftType",
    "EnvironmentInfo",
    "ExistingTestCase",
    "FailureContext",
    "GenerationContext",
    "ProjectInfo",
    "RequestMetadata",
    "TestCaseDraft",
    "TestCaseGenerationRequest",
    "TestCaseGenerationResponse",
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
