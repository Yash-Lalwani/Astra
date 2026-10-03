import logging
import os
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]

# CT.gov condition queries for each condition group (BACKEND.md 7.1).
CONDITION_GROUPS: dict[str, str] = {
    "oncology": "cancer",
    "cardiovascular": "cardiovascular diseases",
    "cns_mental_health": (
        "depression OR schizophrenia OR bipolar disorder OR anxiety disorders OR alzheimer disease"
    ),
    "metabolic_t2d": "type 2 diabetes",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    # App
    app_env: Literal["development", "production"] = "development"
    log_level: str = "INFO"
    cors_origins: str = "http://localhost:3000"
    admin_api_key: str = ""
    public_daily_run_limit: int = 5
    replay_delay_ms: int = 250

    # Database
    database_url: str = ""
    test_database_url: str = "postgresql://astra:astra@localhost:5434/astra_test"

    # LLMs (OpenRouter)
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_api_key: str = ""
    # Comma-separated, in order of preference.
    openrouter_providers: str = ""
    strong_model: str = "deepseek/deepseek-v4-flash"
    fast_model: str = "deepseek/deepseek-v4-flash"
    structured_output_method: Literal["function_calling", "json_schema"] = "json_schema"
    llm_requests_per_second: float = 2
    llm_max_tokens: int = 8000
    llm_timeout_seconds: int = 60

    # OpenAI: embeddings only
    openai_api_key: str = ""
    embedding_model: str = "text-embedding-3-small"
    embedding_dims: int = 1536

    # Agents
    agent_max_steps: int = 6
    agent_timeout_seconds: int = 240

    # LangSmith
    langsmith_tracing: bool = True
    langsmith_api_key: str = ""
    langsmith_project: str = "astra"

    # GCS
    gcs_bucket: str = ""
    gcs_credentials_json: str = ""

    # PubMed
    ncbi_api_key: str = ""
    ncbi_email: str = ""

    # Layer-Engine (empty URL = disabled)
    layer_mcp_url: str = ""
    layer_api_key: str = ""
    layer_collection: str = "astra-trials"

    @property
    def openrouter_provider_list(self) -> list[str]:
        return [name.strip() for name in self.openrouter_providers.split(",") if name.strip()]


def export_langsmith_env(config: Settings) -> None:
    """pydantic-settings never writes to os.environ, but the LangSmith SDK only reads os.environ."""
    if not config.langsmith_api_key:
        return
    os.environ["LANGSMITH_TRACING"] = "true" if config.langsmith_tracing else "false"
    os.environ["LANGSMITH_API_KEY"] = config.langsmith_api_key
    os.environ["LANGSMITH_PROJECT"] = config.langsmith_project


def configure_logging() -> None:
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    # httpx logs every request at INFO; that would drown out Astra's own log lines.
    logging.getLogger("httpx").setLevel(logging.WARNING)


settings = Settings()
export_langsmith_env(settings)
