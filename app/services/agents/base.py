from __future__ import annotations
from typing import Optional, Protocol
from app.models.domain import AgentResult


class Agent(Protocol):
    async def run(self, job_id: str, input_text: str, model: str) -> AgentResult: ...
