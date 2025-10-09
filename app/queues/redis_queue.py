from __future__ import annotations

import json
import logging
from typing import Dict, Any, Optional

from redis.asyncio import from_url, Redis

from app.core.config import get_settings
from app.models.schemas import JobOptions

_logger = logging.getLogger(__name__)
QUEUE_KEY = "ureshii.jobs"
DLQ_KEY = "ureshii.jobs.dead"

_redis_client: Optional[Redis] = None


def get_redis_client() -> Redis:
    """Initializes and returns a singleton Redis client instance."""
    global _redis_client
    if _redis_client is None:
        settings = get_settings()
        if not settings.REDIS_URL:
            raise ValueError("REDIS_URL must be set to use Redis queue")
        _logger.info("Connecting to Redis...")
        _redis_client = from_url(str(settings.REDIS_URL), decode_responses=True)
    return _redis_client


async def close_redis_client():
    """Closes the singleton Redis client connection."""
    global _redis_client
    if _redis_client:
        await _redis_client.close()
        _redis_client = None
        _logger.info("Redis connection closed.")


class RedisQueue:
    def __init__(self) -> None:
        self.client: Redis = get_redis_client()

    async def enqueue_job(self, job_id: str, prompt: str, options: JobOptions) -> None:
        job = {
            "job_id": job_id,
            "prompt": prompt,
            "options": options.model_dump(),
        }
        await self.client.lpush(QUEUE_KEY, json.dumps(job))

    async def pop(self, timeout: int = 5) -> Optional[Dict[str, Any]]:
        item = await self.client.brpop(QUEUE_KEY, timeout=timeout)
        if not item:
            return None
        _, payload = item
        try:
            return json.loads(payload)
        except (json.JSONDecodeError, TypeError):
            _logger.error("Failed to parse job payload: %s", payload)
            await self.move_to_dlq(payload, "parse_error")
            return None

    async def move_to_dlq(self, payload: str, reason: str):
        try:
            dlq_payload = json.dumps({"payload": payload, "reason": reason})
            await self.client.lpush(DLQ_KEY, dlq_payload)
            _logger.warning("Moved malformed/failed job to DLQ. Reason: %s", reason)
        except Exception:
            _logger.exception("CRITICAL: Failed to move job to DLQ. Payload: %s", payload)

    async def ping(self) -> bool:
        try:
            return bool(await self.client.ping())
        except Exception:
            return False
