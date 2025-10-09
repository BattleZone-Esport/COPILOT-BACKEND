from __future__ import annotations

from typing import Protocol

from app.models.schemas import JobOptions


class AsyncQueue(Protocol):
    """A protocol for asynchronous job queues."""

    async def enqueue_job(self, job_id: str, prompt: str, options: JobOptions) -> None:
        """Enqueues a job for background processing."""
        ...

    async def ping(self) -> bool:
        """Checks if the queue backend is available."""
        ...
