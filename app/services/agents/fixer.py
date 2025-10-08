from __future__ import annotations

from app.models.domain import AgentResult
from app.services.ai.openrouter_client import OpenRouterClient

FIXER_SYSTEM = (
    "You are Fixer AI. Apply the debugger's recommendations to the original code and return corrected code. "
    "Include only corrected code. Ensure it compiles and addresses listed issues."
)


class FixerAgent:
    def __init__(self) -> None:
        self.client = OpenRouterClient()

    async def run(self, job_id: str, input_text: str, model: str) -> AgentResult:
        output = await self.client.generate_chat(
            model=model,
            user_content=input_text,
            system_prompt=FIXER_SYSTEM,
            temperature=0.1,
        )
        return AgentResult(
            agent="fixer",
            input=input_text,
            output=output,
            artifact_type="code",
            artifact_content=output,
        )
