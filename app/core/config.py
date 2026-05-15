"""애플리케이션 설정.

환경변수는 모두 여기를 통해 읽는다.
.env 파일도 지원 (개발 환경 편의).

설계 결정:
1. pydantic-settings 사용. FastAPI/LangChain 진영 표준.
2. lru_cache로 싱글톤 보장 (앱 전체에서 같은 인스턴스).
3. 시크릿(API 키 등)은 SecretStr로 받아 로그·repr에 노출되지 않게.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """앱 설정. 환경변수 prefix는 FLOWOPS_."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="FLOWOPS_",
        extra="ignore",
    )

    # --- LLM ---
    anthropic_api_key: SecretStr = Field(
        description="Anthropic API 키. 환경변수: FLOWOPS_ANTHROPIC_API_KEY",
    )
    anthropic_model: str = Field(
        default="claude-sonnet-4-5",
        description="기본 시나리오 생성용 모델",
    )

    # --- 앱 메타 ---
    app_name: str = "FlowOps AI"
    log_level: str = Field(default="INFO", description="DEBUG, INFO, WARNING, ERROR")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """앱 전체에서 공유되는 Settings 인스턴스 반환.

    @lru_cache로 첫 호출 결과를 캐싱 → 사실상 싱글톤.
    테스트에서 settings를 바꿀 때는 get_settings.cache_clear() 호출.
    """
    return Settings()  # type: ignore[call-arg]
