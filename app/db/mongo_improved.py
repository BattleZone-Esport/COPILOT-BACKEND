"""
Improved MongoDB connection module with retry logic, connection pooling,
and comprehensive health checks.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional
from datetime import datetime, timezone
from contextlib import asynccontextmanager

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo.errors import (
    ConnectionFailure, 
    ServerSelectionTimeoutError,
    OperationFailure,
    ConfigurationError
)
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_log,
    after_log
)

from app.core.config import get_settings

_logger = logging.getLogger(__name__)

class MongoDBManager:
    """
    Singleton MongoDB connection manager with improved error handling,
    retry logic, and health monitoring.
    """
    
    _instance: Optional["MongoDBManager"] = None
    _lock = asyncio.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if not hasattr(self, "_initialized"):
            self._client: Optional[AsyncIOMotorClient] = None
            self._db: Optional[AsyncIOMotorDatabase] = None
            self._connected: bool = False
            self._last_ping: Optional[datetime] = None
            self._connection_attempts: int = 0
            self._settings = get_settings()
            self._initialized = True
    
    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type((ConnectionFailure, ServerSelectionTimeoutError)),
        before=before_log(_logger, logging.INFO),
        after=after_log(_logger, logging.INFO)
    )
    async def _connect_with_retry(self) -> AsyncIOMotorClient:
        """
        Attempt to connect to MongoDB with exponential backoff retry logic.
        """
        self._connection_attempts += 1
        
        try:
            client = AsyncIOMotorClient(
                self._settings.mongodb_uri_resolved,
                maxPoolSize=100,
                minPoolSize=10,
                maxIdleTimeMS=45000,
                serverSelectionTimeoutMS=10000,
                connectTimeoutMS=10000,
                socketTimeoutMS=20000,
                retryWrites=True,
                retryReads=True,
                w='majority',
                journal=True
            )
            
            # Verify connection
            await client.admin.command('ping')
            
            _logger.info(
                "Successfully connected to MongoDB after %d attempts",
                self._connection_attempts
            )
            
            self._connection_attempts = 0  # Reset counter on success
            return client
            
        except (ConnectionFailure, ServerSelectionTimeoutError) as e:
            _logger.error(
                "MongoDB connection attempt %d failed: %s",
                self._connection_attempts,
                str(e)
            )
            raise
        except Exception as e:
            _logger.critical(
                "Unexpected error during MongoDB connection: %s",
                str(e)
            )
            raise ConnectionFailure(f"Unexpected connection error: {e}")
    
    async def connect(self) -> AsyncIOMotorDatabase:
        """
        Establish or retrieve MongoDB connection with health checking.
        """
        async with self._lock:
            # Check if we have a healthy connection
            if await self.is_healthy():
                return self._db
            
            _logger.info("Establishing new MongoDB connection...")
            
            try:
                # Close existing unhealthy connection
                if self._client:
                    self._client.close()
                
                # Establish new connection with retry
                self._client = await self._connect_with_retry()
                self._db = self._client[self._settings.MONGODB_DB]
                
                # Initialize indexes
                await self._ensure_indexes()
                
                self._connected = True
                self._last_ping = datetime.now(timezone.utc)
                
                return self._db
                
            except Exception as e:
                self._connected = False
                _logger.critical("Failed to establish MongoDB connection: %s", str(e))
                raise
    
    async def is_healthy(self) -> bool:
        """
        Check if the current MongoDB connection is healthy.
        """
        if not self._client or not self._connected:
            return False
        
        try:
            # Ping with timeout
            await asyncio.wait_for(
                self._client.admin.command('ping'),
                timeout=5.0
            )
            self._last_ping = datetime.now(timezone.utc)
            return True
        except Exception as e:
            _logger.warning("MongoDB health check failed: %s", str(e))
            self._connected = False
            return False
    
    async def _ensure_indexes(self) -> None:
        """
        Create necessary database indexes for optimal performance.
        """
        try:
            # Jobs collection indexes
            await self._db.jobs.create_index("job_id", unique=True)
            await self._db.jobs.create_index("created_at")
            await self._db.jobs.create_index("status")
            await self._db.jobs.create_index("user_id")
            await self._db.jobs.create_index([("status", 1), ("created_at", -1)])
            
            # Users collection indexes
            await self._db.users.create_index("user_id", unique=True)
            await self._db.users.create_index("email", unique=True)
            await self._db.users.create_index("last_login")
            
            # Runs collection indexes
            await self._db.runs.create_index([("job_id", 1), ("agent", 1)])
            await self._db.runs.create_index("created_at")
            
            # Artifacts collection indexes
            await self._db.artifacts.create_index("job_id")
            await self._db.artifacts.create_index("created_at")
            
            # Terminal commands collection indexes (for new feature)
            await self._db.terminal_commands.create_index("command_id", unique=True)
            await self._db.terminal_commands.create_index("user_id")
            await self._db.terminal_commands.create_index("started_at")
            await self._db.terminal_commands.create_index([("user_id", 1), ("started_at", -1)])
            
            # Terminal logs collection indexes
            await self._db.terminal_logs.create_index([("user_id", 1), ("log_file", 1)])
            await self._db.terminal_logs.create_index("last_modified")
            
            _logger.info("Database indexes ensured successfully")
            
        except OperationFailure as e:
            _logger.error("Failed to create indexes: %s", str(e))
            # Don't fail the connection if index creation fails
        except Exception as e:
            _logger.critical("Unexpected error during index creation: %s", str(e))
            raise
    
    async def get_db(self) -> AsyncIOMotorDatabase:
        """
        Get database instance, establishing connection if needed.
        """
        if not await self.is_healthy():
            return await self.connect()
        return self._db
    
    async def get_client(self) -> AsyncIOMotorClient:
        """
        Get MongoDB client instance.
        """
        await self.get_db()  # Ensure connection
        return self._client
    
    async def close(self) -> None:
        """
        Gracefully close MongoDB connection.
        """
        if self._client:
            self._client.close()
            self._connected = False
            self._client = None
            self._db = None
            _logger.info("MongoDB connection closed")
    
    async def get_health_status(self) -> Dict[str, Any]:
        """
        Get detailed health status for monitoring.
        """
        is_healthy = await self.is_healthy()
        
        status = {
            "healthy": is_healthy,
            "connected": self._connected,
            "last_ping": self._last_ping.isoformat() if self._last_ping else None,
            "connection_attempts": self._connection_attempts
        }
        
        if is_healthy and self._db:
            try:
                # Get database statistics
                stats = await self._db.command("dbStats")
                status["database"] = {
                    "name": self._db.name,
                    "collections": stats.get("collections", 0),
                    "documents": stats.get("objects", 0),
                    "size_bytes": stats.get("dataSize", 0)
                }
                
                # Get connection pool stats
                if self._client:
                    pool_stats = self._client._topology._servers
                    status["connection_pool"] = {
                        "active": len(pool_stats) if pool_stats else 0
                    }
            except Exception as e:
                _logger.warning("Failed to get database statistics: %s", str(e))
        
        return status
    
    @asynccontextmanager
    async def transaction(self):
        """
        Context manager for MongoDB transactions with automatic retry.
        """
        client = await self.get_client()
        
        async with await client.start_session() as session:
            async with session.start_transaction():
                try:
                    yield session
                except Exception as e:
                    _logger.error("Transaction failed: %s", str(e))
                    raise

# Singleton instance
_db_manager = MongoDBManager()

# Public API functions for backward compatibility
async def get_db() -> AsyncIOMotorDatabase:
    """Get database instance."""
    return await _db_manager.get_db()

async def get_client() -> AsyncIOMotorClient:
    """Get MongoDB client instance."""
    return await _db_manager.get_client()

async def connect_to_mongo() -> AsyncIOMotorDatabase:
    """Connect to MongoDB."""
    return await _db_manager.connect()

async def close_mongo_connection() -> None:
    """Close MongoDB connection."""
    await _db_manager.close()

async def get_mongo_health() -> Dict[str, Any]:
    """Get MongoDB health status."""
    return await _db_manager.get_health_status()

async def ensure_indexes() -> None:
    """Ensure database indexes."""
    db = await get_db()
    # Indexes are created automatically during connection

# For dependency injection
async def get_database() -> AsyncIOMotorDatabase:
    """FastAPI dependency for database access."""
    return await get_db()