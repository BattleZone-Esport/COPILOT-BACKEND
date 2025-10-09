
from __future__ import annotations

import secrets
import warnings
from functools import lru_cache
from typing import List, Literal, Optional

from pydantic import AnyUrl, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="allow")

    # App
    APP_NAME: str = "Ureshii-Partner"
    LOG_LEVEL: str = "info"
    ENVIRONMENT: Literal["development", "production"] = "development"

    # CORS
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

    @property
    def mongodb_uri_resolved(self) -> str:
        return self.MONGODB_URI or self.MONGO_URI or ""

    # OpenAI
    OPENAI_API_KEY: Optional[str] = Field(default=None, repr=False)
    OPENAI_ORG_ID: Optional[str] = Field(default=None, repr=False)
    OPENAI_MODEL: str = "gpt-3.5-turbo"
    
    # OpenRouter
    OPENROUTER_API_KEY: Optional[str] = Field(default=None, repr=False)
    OPENROUTER_SITE_URL: Optional[str] = None
    OPENROUTER_SITE_NAME: Optional[str] = None

    # LLM
    PROMPT_MAX_CHARS: int = 2000
    ALLOWED_MODELS: List[str] = [
        "openai/gpt-3.5-turbo",
        "openai/gpt-4",
        "anthropic/claude-2",
        "google/gemini-pro",
        "qwen/qwen3-30b-a3b:free",
        "qwen/qwen3-coder:free",
        "deepseek/deepseek-chat-v3.1:free",
        "nvidia/nemotron-nano-9b-v2:free",
    ]
    DEFAULT_CODER_MODEL: str = "qwen/qwen3-coder:free"
    DEFAULT_DEBUGGER_MODEL: str = "deepseek/deepseek-chat-v3.1:free"
    DEFAULT_FIXER_MODEL: str = "nvidia/nemotron-nano-9b-v2:free"
    DEFAULT_CHATBOT_MODEL: str = "qwen/qwen3-30b-a3b:free"

    # Queues
    QUEUE_BACKEND: Literal["redis", "gcp-pubsub", "qstash", "none"] = "none"
    REDIS_URL: Optional[AnyUrl] = None
    QSTASH_URL: Optional[str] = None
    QSTASH_TOKEN: Optional[str] = Field(default=None, repr=False)
    QSTASH_CURRENT_SIGNING_KEY: Optional[str] = Field(default=None, repr=False)
    QSTASH_NEXT_SIGNING_KEY: Optional[str] = Field(default=None, repr=False)
    QSTASH_DESTINATION_URL: Optional[AnyUrl] = None
    QSTASH_VERIFY_SIGNATURE: bool = False
    GCP_PROJECT_ID: Optional[str] = None
    GCP_PUBSUB_TOPIC: Optional[str] = None
    JOB_LOCK_TIMEOUT: int = 300

    # GitHub
    GITHUB_TOKEN: Optional[str] = Field(default=None, repr=False)

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
