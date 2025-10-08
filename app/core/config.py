from __future__ import annotations

import secrets
import warnings
from functools import lru_cache
from typing import List, Literal, Optional

from pydantic import AnyUrl, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="allow")

    # App
    APP_NAME: str = "Ureshii-Partner"
    LOG_LEVEL: str = "info"
    ENVIRONMENT: Literal["development", "production"] = "development"

    # CORS
    APP_CORS_ORIGINS: List[str] = Field(default_factory=list)

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
    JOB_LOCK_TIMEOUT: int = 300

    @field_validator("APP_CORS_ORIGINS", mode="before")
    @classmethod
    def _parse_cors_origins(cls, v):
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",") if origin.strip()]
        return v

    @model_validator(mode="after")
    def _check_settings(self) -> "Settings":
        # Check Auth Secret Key
        if self.AUTH_ENABLED and not self.AUTH_SECRET_KEY:
            if self.ENVIRONMENT == "production":
                raise ValueError(
                    "AUTH_SECRET_KEY must be set in production when AUTH_ENABLED is True"
                )
            else:
                self.AUTH_SECRET_KEY = secrets.token_hex(32)
                warnings.warn(
                    "AUTH_SECRET_KEY was not set. A temporary key has been generated for development. "
                    "Please set a permanent key in your .env file for production.",
                    UserWarning,
                )

        # Check CORS Origins
        if self.ENVIRONMENT == "production" and "*" in self.APP_CORS_ORIGINS:
            warnings.warn(
                "Using '*' for APP_CORS_ORIGINS in production is a security risk. "
                "It is recommended to specify the exact origins.",
                UserWarning,
            )
        return self


@lru_cache()
def get_settings():
    return Settings()
