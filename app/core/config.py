from __future__ import annotations

from functools import lru_cache
from typing import List, Optional, Literal
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, AnyUrl, field_validator


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="allow")

    # App
    APP_NAME: str = "Ureshii-Partner"
    LOG_LEVEL: str = "info"
    APP_CORS_ORIGINS: str = "*"

    # Auth
    AUTH_ENABLED: bool = True
    AUTH_SECRET_KEY: Optional[str] = Field(default=None, repr=False)
    AUTH_PROVIDER: Literal["google"] = "google"
    AUTH_GOOGLE_CLIENT_ID: Optional[str] = Field(default=None, repr=False)
    AUTH_GOOGLE_CLIENT_SECRET: Optional[str] = Field(default=None, repr=False)

    # DB
    MONGODB_URI: Optional[str] = None
    MONGO_URI: Optional[str] = None  # alias accepted
    MONGODB_DB: str = "ureshii_partner"

    # OpenRouter
    OPENROUTER_API_KEY: str = Field(default="", repr=False)
    OPENROUTER_SITE_URL: Optional[str] = None
    OPENROUTER_SITE_NAME: Optional[str] = None

    # Default models
    DEFAULT_CODER_MODEL: str = "qwen/qwen3-coder:free"
    DEFAULT_DEBUGGER_MODEL: str = "deepseek/deepseek-chat-v3.1:free"
    DEFAULT_FIXER_MODEL: str = "nvidia/nemotron-nano-9b-v2:free"
    DEFAULT_CHATBOT_MODEL: str = "qwen/qwen3-30b-a3b:free"

    # Queue
    QUEUE_BACKEND: Literal["redis", "qstash", "none"] = "redis"
    REDIS_URL: Optional[str] = None

    # QStash
    QSTASH_URL: str = "https://qstash.upstash.io"
    QSTASH_TOKEN: Optional[str] = Field(default=None, repr=False)
    QSTASH_CURRENT_SIGNING_KEY: Optional[str] = None
    QSTASH_NEXT_SIGNING_KEY: Optional[str] = None
    QSTASH_DESTINATION_URL: Optional[str] = None
    QSTASH_VERIFY_SIGNATURE: bool = True

    # New configuration
    PROMPT_MAX_CHARS: int = 20000

    @property
    def mongodb_uri_resolved(self) -> str:
        if self.MONGODB_URI:
            return self.MONGODB_URI
        if self.MONGO_URI:
            return self.MONGO_URI
        raise ValueError("MONGODB_URI (or MONGO_URI) must be set")

    @property
    def cors_origins(self) -> List[str]:
        raw = (self.APP_CORS_ORIGINS or "").strip()
        if raw == "*":
            return ["*"]
        return [x.strip() for x in raw.split(",") if x.strip()]

    @field_validator("OPENROUTER_API_KEY")
    @classmethod
    def _openrouter_key_not_empty(cls, v: str) -> str:
        if not v:
            # Allow empty in dev, but warn at runtime if used.
            return v
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()
