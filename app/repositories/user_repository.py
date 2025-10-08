from typing import Optional, Any
from datetime import datetime, timezone
from motor.motor_asyncio import AsyncIOMotorDatabase

async def create_user(db: AsyncIOMotorDatabase, data: dict[str, Any]) -> dict:
    data["created_at"] = data.get("created_at") or datetime.now(timezone.utc)
    data["last_login"] = datetime.now(timezone.utc)
    await db.users.insert_one(data)
    return data

async def get_user_by_id(db: AsyncIOMotorDatabase, user_id: str) -> Optional[dict]:
    return await db.users.find_one({"user_id": user_id})

async def get_user_by_email(db: AsyncIOMotorDatabase, email: str) -> Optional[dict]:
    return await db.users.find_one({"email": email})

async def update_user(db: AsyncIOMotorDatabase, user_id: str, updates: dict[str, Any]) -> Optional[dict]:
    await db.users.update_one({"user_id": user_id}, {"$set": updates})
    return await get_user_by_id(db, user_id)

async def link_oauth_provider(db: AsyncIOMotorDatabase, user_id: str, provider: str, oauth_tokens: dict[str, Any]) -> None:
    await db.users.update_one({"user_id": user_id}, {"$set": {f"providers.{provider}": oauth_tokens}})

async def touch_last_login(db: AsyncIOMotorDatabase, user_id: str) -> None:
    await db.users.update_one({"user_id": user_id}, {"$set": {"last_login": datetime.now(timezone.utc)}})
