from __future__ import annotations

import asyncio
import json
import logging
from typing import Dict, Any, Optional

from redis.asyncio import from_url, Redis
from urllib.parse import urlparse

from app.core.config import get_settings

_logger = logging.getLogger(__name__)
QUEUE_KEY = "ureshii.jobs"


class RedisQueue:
    def __init__(self, url: Optional[str] = None) -> None:
        s = get_settings()
        url = url or s.REDIS_URL or "redis://localhost:6379"
        self.client: Redis = from_url(url, decode_responses=True)

    async def enqueue(self, job: Dict[str, Any]) -> None:
        await self.client.lpush(QUEUE_KEY, json.dumps(job))

    async def pop(self, timeout: int = 5) -> Optional[Dict[str, Any]]:
        item = await self.client.brpop(QUEUE_KEY, timeout=timeout)
        if not item:
            return None
        _, payload = item
        try:
            return json.loads(payload)
        except Exception:
            _logger.error("Failed to parse job payload")
            return None

    async def ping(self) -> bool:
        try:
            return bool(await self.client.ping())
        except Exception:
            return False
