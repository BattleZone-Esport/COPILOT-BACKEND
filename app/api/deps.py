from __future__ import annotations

from typing import Dict, Optional, Any
from fastapi import Depends, Request, HTTPException
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.config import get_settings
from app.services.orchestrator import get_orchestrator as get_orchestrator_instance, Orchestrator
from app.core.security import validate_csrf_token
from app.db.mongo_improved import get_db
from app.exceptions.custom_exceptions import raise_authentication_error

async def get_orchestrator() -> Orchestrator:
    return await get_orchestrator_instance()

def get_settings_dep():
    return get_settings()

async def validate_csrf(request: Request):
    session_csrf_token = request.session.get('csrf_token')
    request_csrf_token = request.headers.get('X-CSRF-Token')
    if not validate_csrf_token(session_csrf_token, request_csrf_token):
        raise HTTPException(status_code=403, detail='CSRF token mismatch')

async def get_database() -> AsyncIOMotorDatabase:
    """Get database dependency."""
    return await get_db()

async def get_current_user(request: Request) -> Dict[str, Any]:
    """Get current authenticated user from session."""
    user = request.session.get("user")
    if not user:
        raise_authentication_error("User not authenticated")
    
    # Add user ID if not present (for backward compatibility)
    if "id" not in user and "email" in user:
        # Try to get user ID from database
        db = await get_database()
        user_record = await db.users.find_one({"email": user["email"]})
        if user_record:
            user["id"] = user_record.get("user_id", user_record.get("_id"))
    
    return user

async def get_optional_user(request: Request) -> Optional[Dict[str, Any]]:
    """Get current user if authenticated, otherwise return None."""
    try:
        return await get_current_user(request)
    except HTTPException:
        return None
