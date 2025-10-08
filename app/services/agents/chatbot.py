
from __future__ import annotations
import logging
from app.services.ai.openrouter_client import OpenRouterClient
from app.core.config import get_settings

_logger = logging.getLogger(__name__)

class ChatbotAgent:
    def __init__(self):
        self.client = OpenRouterClient()
        settings = get_settings()
        self.model = settings.DEFAULT_CHATBOT_MODEL

    async def run(self, prompt: str) -> str:
        _logger.info(f"Running chatbot with prompt: {prompt}")
        try:
            response = await self.client.generate_chat(
                model=self.model,
                user_content=prompt,
                temperature=0.7, # More creative for chat
            )
            return response
        except Exception as e:
            _logger.exception("Error running chatbot agent")
            return f"Sorry, I encountered an error: {str(e)}"
