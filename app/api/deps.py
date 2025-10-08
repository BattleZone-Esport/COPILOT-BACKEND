from __future__ import annotations

from fastapi import Depends
from app.core.config import get_settings
from app.services.orchestrator import Orchestrator


def get_orchestrator():
    return Orchestrator()


def get_settings_dep():
    return get_settings()
