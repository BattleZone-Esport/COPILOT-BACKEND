from __future__ import annotations

import logging
from typing import Any, Dict
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo.errors import ConnectionFailure

from app.core.config import get_settings

_logger = logging.getLogger(__name__)

_client: AsyncIOMotorClient | None = None
_db: AsyncIOMotorDatabase | None = None


async def get_db() -> AsyncIOMotorDatabase:
    global _client, _db
    if _db is not None:
        # Optional: Ping the server to ensure the connection is still alive
        try:
            await _client.admin.command('ping')
            return _db
        except ConnectionFailure:
            _logger.warning("Database connection lost. Reconnecting...")
            _db = None
            _client = None

    settings = get_settings()
    _logger.info("Connecting to MongoDB...")
    try:
        _client = AsyncIOMotorClient(
            settings.mongodb_uri_resolved,
            maxPoolSize=50,
            minPoolSize=10,
            serverSelectionTimeoutMS=5000,
            connectTimeoutMS=5000,
        )
        # The ismaster command is cheap and does not require auth.
        await _client.admin.command('ping')
        _db = _client[settings.MONGODB_DB]
        _logger.info("Successfully connected to MongoDB.")
        return _db
    except ConnectionFailure as e:
        _logger.critical("Failed to connect to MongoDB: %s", e)
        # Depending on the application's needs, you might want to exit
        # or raise a more specific exception to be handled by the caller.
        raise HTTPException(status_code=500, detail="Database connection failed")

async def ensure_indexes() -> None:
    try:
        db = await get_db()
        await db.jobs.create_index("job_id", unique=True)
        await db.jobs.create_index("created_at")
        await db.jobs.create_index("status")

        await db.users.create_index("user_id", unique=True)
        await db.users.create_index("email", unique=True)

        await db.runs.create_index([("job_id", 1), ("agent", 1)])
        await db.artifacts.create_index("job_id")
        _logger.info("Mongo indexes ensured")
    except Exception as e:
        _logger.error("Could not ensure indexes: %s", e)
        # This could be a critical failure at startup
        # depending on application requirements


# You might want a function to close the connection gracefully during shutdown
async def close_db_connection():
    global _client
    if _client:
        _client.close()
        _logger.info("MongoDB connection closed.")
