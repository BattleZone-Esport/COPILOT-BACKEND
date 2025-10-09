from __future__ import annotations

import logging
from typing import Optional, List, Dict, Any

import httpx
from openai import AsyncOpenAI
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from openai import APIStatusError, APIConnectionError, RateLimitError

from app.core.config import get_settings
from app.core.http_client import get_http_client

_logger = logging.getLogger(__name__)


class OpenRouterClient:
    def __init__(self, http_client: httpx.AsyncClient):
        s = get_settings()
        self.client = AsyncOpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=s.OPENROUTER_API_KEY or None,
            http_client=http_client,
        )
        self.extra_headers = {}
        if s.OPENROUTER_SITE_URL:
            self.extra_headers["HTTP-Referer"] = s.OPENROUTER_SITE_URL
        if s.OPENROUTER_SITE_NAME:
            self.extra_headers["X-Title"] = s.OPENROUTER_SITE_NAME

    @retry(
        reraise=True,
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=0.8, min=1, max=10),
        retry=retry_if_exception_type((APIStatusError, APIConnectionError, RateLimitError)),
    )
    async def generate_chat(
        self,
        *,
        model: str,
        user_content: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: Optional[int] = None,
    ) -> str:
        messages: List[Dict[str, Any]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_content})

        resp = await self.client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            extra_headers=self.extra_headers or None,
        )
        out = resp.choices[0].message.content or ""
        return out.strip()


async def get_openrouter_client() -> OpenRouterClient:
    http_client = get_http_client()  # This returns a client directly, not async
    return OpenRouterClient(http_client)
