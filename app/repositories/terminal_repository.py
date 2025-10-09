"""
Repository for terminal-related database operations.
"""

import logging
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone, timedelta

from motor.motor_asyncio import AsyncIOMotorDatabase

_logger = logging.getLogger(__name__)


class TerminalRepository:
    """Repository for terminal command and log operations."""
    
    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
        self.commands_collection = db.terminal_commands
        self.logs_collection = db.terminal_logs
        self.access_logs_collection = db.terminal_access_logs
    
    async def create_command(
        self,
        command_id: str,
        user_id: str,
        command: str,
        status: str,
        working_dir: Optional[str] = None,
        env_vars: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """Create a new terminal command record."""
        document = {
            "command_id": command_id,
            "user_id": user_id,
            "command": command,
            "status": status,
            "working_dir": working_dir,
            "env_vars": env_vars,
            "started_at": datetime.now(timezone.utc),
            "created_at": datetime.now(timezone.utc)
        }
        
        await self.commands_collection.insert_one(document)
        return document
    
    async def update_command(
        self,
        command_id: str,
        status: Optional[str] = None,
        stdout: Optional[str] = None,
        stderr: Optional[str] = None,
        exit_code: Optional[int] = None,
        duration_ms: Optional[int] = None,
        error_message: Optional[str] = None,
        completed_at: Optional[datetime] = None
    ) -> bool:
        """Update a terminal command record."""
        update_data = {}
        
        if status is not None:
            update_data["status"] = status
        if stdout is not None:
            update_data["stdout"] = stdout
        if stderr is not None:
            update_data["stderr"] = stderr
        if exit_code is not None:
            update_data["exit_code"] = exit_code
        if duration_ms is not None:
            update_data["duration_ms"] = duration_ms
        if error_message is not None:
            update_data["error_message"] = error_message
        if completed_at is not None:
            update_data["completed_at"] = completed_at
        
        update_data["updated_at"] = datetime.now(timezone.utc)
        
        result = await self.commands_collection.update_one(
            {"command_id": command_id},
            {"$set": update_data}
        )
        
        return result.modified_count > 0
    
    async def get_command(self, command_id: str) -> Optional[Dict[str, Any]]:
        """Get a terminal command by ID."""
        return await self.commands_collection.find_one({"command_id": command_id})
    
    async def get_user_commands(
        self,
        user_id: str,
        limit: int = 20,
        status_filter: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None
    ) -> List[Dict[str, Any]]:
        """Get commands for a specific user."""
        query = {"user_id": user_id}
        
        if status_filter:
            query["status"] = status_filter
        
        if start_time or end_time:
            time_query = {}
            if start_time:
                time_query["$gte"] = start_time
            if end_time:
                time_query["$lte"] = end_time
            query["started_at"] = time_query
        
        cursor = self.commands_collection.find(query).sort("started_at", -1).limit(limit)
        return await cursor.to_list(length=limit)
    
    async def clear_user_commands(self, user_id: str) -> int:
        """Clear all commands for a user."""
        result = await self.commands_collection.delete_many({"user_id": user_id})
        return result.deleted_count
    
    async def store_log_access(
        self,
        user_id: str,
        log_file: str,
        action: str,
        size: int = 0
    ) -> None:
        """Store log access record."""
        document = {
            "user_id": user_id,
            "log_file": log_file,
            "action": action,
            "size": size,
            "timestamp": datetime.now(timezone.utc)
        }
        
        await self.access_logs_collection.insert_one(document)
        
        # Update or create log metadata
        await self.logs_collection.update_one(
            {"log_file": log_file, "user_id": user_id},
            {
                "$set": {
                    "last_modified": datetime.now(timezone.utc),
                    "size": size
                },
                "$inc": {"access_count": 1}
            },
            upsert=True
        )
    
    async def can_access_log(self, user_id: str, log_file: str) -> bool:
        """Check if user can access a log file."""
        # For now, allow access to all logs for authenticated users
        # In production, implement proper access control
        blocked_patterns = [
            "/etc/passwd",
            "/etc/shadow",
            "/root/",
            "/.ssh/",
            "/proc/",
            "/sys/"
        ]
        
        for pattern in blocked_patterns:
            if pattern in log_file:
                return False
        
        return True
    
    async def can_write_log(self, user_id: str, log_file: str) -> bool:
        """Check if user can write to a log file."""
        # More restrictive than read access
        # Only allow writing to specific user logs
        allowed_patterns = [
            f"user_{user_id}",
            "app.log",
            "debug.log"
        ]
        
        for pattern in allowed_patterns:
            if pattern in log_file:
                return True
        
        return False
    
    async def get_command_statistics(
        self,
        user_id: Optional[str] = None,
        time_range: Optional[int] = 24  # hours
    ) -> Dict[str, Any]:
        """Get command execution statistics."""
        query = {}
        if user_id:
            query["user_id"] = user_id
        
        if time_range:
            cutoff_time = datetime.now(timezone.utc) - timedelta(hours=time_range)
            query["started_at"] = {"$gte": cutoff_time}
        
        # Aggregate statistics
        pipeline = [
            {"$match": query},
            {
                "$group": {
                    "_id": "$status",
                    "count": {"$sum": 1},
                    "avg_duration": {"$avg": "$duration_ms"}
                }
            }
        ]
        
        results = await self.commands_collection.aggregate(pipeline).to_list(length=10)
        
        # Format statistics
        stats = {
            "total_commands": 0,
            "by_status": {},
            "avg_duration_ms": 0
        }
        
        total_duration = 0
        total_with_duration = 0
        
        for result in results:
            status = result["_id"]
            count = result["count"]
            avg_duration = result.get("avg_duration", 0)
            
            stats["total_commands"] += count
            stats["by_status"][status] = {
                "count": count,
                "avg_duration_ms": avg_duration
            }
            
            if avg_duration:
                total_duration += avg_duration * count
                total_with_duration += count
        
        if total_with_duration > 0:
            stats["avg_duration_ms"] = total_duration / total_with_duration
        
        return stats
    
    async def cleanup_old_records(self, days: int = 30) -> Dict[str, int]:
        """Clean up old records from the database."""
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)
        
        # Clean up old commands
        commands_result = await self.commands_collection.delete_many(
            {"created_at": {"$lt": cutoff_date}}
        )
        
        # Clean up old access logs
        access_logs_result = await self.access_logs_collection.delete_many(
            {"timestamp": {"$lt": cutoff_date}}
        )
        
        return {
            "commands_deleted": commands_result.deleted_count,
            "access_logs_deleted": access_logs_result.deleted_count
        }