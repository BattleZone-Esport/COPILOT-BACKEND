from __future__ import annotations

import logging
from typing import Optional

from app.core.config import get_settings
from app.queues.base import AsyncQueue
from app.queues.redis_queue import RedisQueue, close_redis_client
from app.queues.qstash import QStashQueue

_logger = logging.getLogger(__name__)
_queue_instance: Optional[AsyncQueue] = None


def get_queue() -> Optional[AsyncQueue]:
    """Initializes and returns a singleton queue instance based on settings."""
    global _queue_instance
    if _queue_instance is None:
        settings = get_settings()
        if settings.QUEUE_BACKEND == "redis":
            _logger.info("Using Redis as the queue backend.")
            _queue_instance = RedisQueue()
        elif settings.QUEUE_BACKEND == "qstash":
            _logger.info("Using QStash as the queue backend.")
            _queue_instance = QStashQueue()
        else:
            _logger.warning("No queue backend configured. Background jobs will not be processed.")
    return _queue_instance


async def shutdown_queue() -> None:
    """Cleans up queue resources, like closing Redis connections."""
    settings = get_settings()
    if settings.QUEUE_BACKEND == "redis":
        await close_redis_client()
