from __future__ import annotations
from datetime import datetime

from app.models.domain import AgentResult
from app.services.ai.openrouter_client import OpenRouterClient


CODER_SYSTEM = (
    "You are Coder AI. Produce clean, runnable code that fulfills the user's prompt. "
    "Include only code, no explanations, unless the prompt explicitly asks for them."
)


class CoderAgent:
    def __init__(self) -> None:
        self.client = OpenRouterClient()

    async def run(self, job_id: str, input_text: str, model: str) -> AgentResult:
        output = await self.client.generate_chat(
            model=model,
            user_content=input_text,
            system_prompt=CODER_SYSTEM,
            temperature=0.2,
        )
        return AgentResult(
            agent="coder",
            input=input_text,
            output=output,
            artifact_type="code",
            artifact_content=output,
        )
