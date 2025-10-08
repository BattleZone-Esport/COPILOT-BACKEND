from __future__ import annotations

from functools import lru_cache
from typing import List, Optional, Literal
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, AnyUrl, field_validator, model_validator


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

    # OpenAI
    OPENAI_API_KEY: Optional[str] = Field(default=None, repr=False)
    OPENAI_ORG_ID: Optional[str] = Field(default=None, repr=False)
    OPENAI_MODEL: str = "gpt-3.5-turbo"

    # LLM
    PROMPT_MAX_CHARS: int = 2000
    ALLOWED_MODELS: List[str] = [
        "openai/gpt-3.5-turbo",
        "openai/gpt-4",
        "anthropic/claude-2",
        "google/gemini-pro",
    ]


    # Queues
    QUEUE_BACKEND: Literal["redis", "gcp-pubsub", "qstash", "none"] = "none"
    REDIS_URL: Optional[AnyUrl] = None
    QSTASH_TOKEN: Optional[str] = Field(default=None, repr=False)
    QSTASH_CALLBACK_URL: Optional[AnyUrl] = None
    GCP_PROJECT_ID: Optional[str] = None
    GCP_PUBSUB_TOPIC: Optional[str] = None

    @field_validator("APP_CORS_ORIGINS")
    def build_cors_origins(cls, v: str) -> List[str]:
        return [origin.strip() for origin in v.split(",")]

    @model_validator(mode='after')
    def check_auth_secret_key(self) -> 'Settings':
        if self.AUTH_ENABLED and not self.AUTH_SECRET_KEY:
            raise ValueError("AUTH_SECRET_KEY must be set when AUTH_ENABLED is True")
        return self

@lru_cache()
def get_settings():
    return Settings()
