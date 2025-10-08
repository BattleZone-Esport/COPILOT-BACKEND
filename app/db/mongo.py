from __future__ import annotations

import logging
from typing import Any, Dict
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from app.core.config import get_settings

_logger = logging.getLogger(__name__)

_client: AsyncIOMotorClient | None = None
_db: AsyncIOMotorDatabase | None = None


async def get_db() -> AsyncIOMotorDatabase:
    global _client, _db
    if _db is not None:
        return _db
    settings = get_settings()
    _client = AsyncIOMotorClient(
        settings.mongodb_uri_resolved,
        maxPoolSize=50,
        minPoolSize=10,
        serverSelectionTimeoutMS=5000,
        connectTimeoutMS=5000,
        # retryWrites is recommended for Atlas; safe to leave default if not supported
    )
    _db = _client[settings.MONGODB_DB]
    return _db


async def ensure_indexes() -> None:
    db = await get_db()
    await db.jobs.create_index("job_id", unique=True)
    await db.jobs.create_index("created_at")
    await db.jobs.create_index("status")

    await db.runs.create_index([("job_id", 1), ("agent", 1)])
    await db.artifacts.create_index("job_id")
    _logger.info("Mongo indexes ensured")
