"""Application settings, loaded from environment variables / .env."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[1]

RiskThreshold = Literal["none", "low", "medium", "high"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(BACKEND_DIR.parent / ".env", BACKEND_DIR / ".env"),
        extra="ignore",
    )

    # Database (any SQLAlchemy URL; PostgreSQL works by swapping this value)
    database_url: str = f"sqlite:///{(BACKEND_DIR / 'data' / 'centralign.db').as_posix()}"
    checkpoint_db_path: str = str(BACKEND_DIR / "data" / "checkpoints.db")
    data_dir: str = str(BACKEND_DIR / "data")
    seed_on_start: bool = True

    # LLM: "demo" uses deterministic rule-based understanding/planning.
    llm_provider: Literal["demo", "openai", "gemini", "groq"] = "demo"
    llm_api_key: str | None = None
    llm_base_url: str | None = None
    llm_model: str | None = None
    llm_timeout_seconds: float = 45.0

    # Agent behaviour
    approval_threshold: RiskThreshold = "medium"  # minimum risk that needs human approval
    max_retries: int = 3
    retry_backoff_base: float = 0.5  # seconds; delay = base * 2**(attempt-1)
    max_plan_steps: int = 12
    max_replans: int = 1

    # Tools
    browser_tools_enabled: bool = True
    browser_headless: bool = True
    frontend_url: str = "http://localhost:5173"

    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    @property
    def reports_dir(self) -> Path:
        return Path(self.data_dir) / "reports"


@lru_cache
def get_settings() -> Settings:
    return Settings()
