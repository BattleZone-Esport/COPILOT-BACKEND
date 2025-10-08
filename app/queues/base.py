from __future__ import annotations
from typing import Protocol, Dict, Any


class QueueBackend(Protocol):
    async def enqueue(self, job: Dict[str, Any]) -> None: ...
