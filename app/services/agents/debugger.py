from __future__ import annotations

from app.models.domain import AgentResult
from app.services.ai.openrouter_client import get_openrouter_client

DEBUGGER_SYSTEM = (
    "You are Debugger AI. Analyze the provided code, identify issues, and propose concrete fixes. "
    "Return a concise report listing bugs with line references (if feasible) and recommended changes."
)


class DebuggerAgent:
    def __init__(self) -> None:
        self.client = None  # Will be initialized on first use

    async def run(self, job_id: str, input_text: str, model: str) -> AgentResult:
        if self.client is None:
            self.client = await get_openrouter_client()
        output = await self.client.generate_chat(
            model=model,
            user_content=input_text,
            system_prompt=DEBUGGER_SYSTEM,
            temperature=0.2,
        )
        return AgentResult(
            agent="debugger",
            input=input_text,
            output=output,
            artifact_type="report",
            artifact_content=output,
        )
