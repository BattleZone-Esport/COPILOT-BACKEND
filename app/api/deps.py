from __future__ import annotations

from fastapi import Depends, Request, HTTPException
from app.core.config import get_settings
from app.services.orchestrator import Orchestrator
from app.core.security import validate_csrf_token

def get_orchestrator():
    return Orchestrator()


def get_settings_dep():
    return get_settings()

async def validate_csrf(request: Request):
    session_csrf_token = request.session.get('csrf_token')
    request_csrf_token = request.headers.get('X-CSRF-Token')
    if not validate_csrf_token(session_csrf_token, request_csrf_token):
        raise HTTPException(status_code=403, detail='CSRF token mismatch')
