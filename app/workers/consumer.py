from __future__ import annotations

import asyncio
import logging

from app.core.config import get_settings
from app.db.mongo import ensure_indexes
from app.queues.redis_queue import RedisQueue
from app.services.orchestrator import Orchestrator
from app.models.schemas import JobOptions

_logger = logging.getLogger("worker")


async def main():
    await ensure_indexes()
    settings = get_settings()
    if settings.QUEUE_BACKEND != "redis":
        _logger.error("Worker is only for Redis backend. Current: %s", settings.QUEUE_BACKEND)
        return

    q = RedisQueue()
    orch = Orchestrator()

    _logger.info("Starting Redis worker...")
    while True:
        job_payload = await q.pop(timeout=15)
        if not job_payload:
            continue

        job_id = job_payload.get("job_id")
        prompt = job_payload.get("prompt")
        options_data = job_payload.get("options")

        if not all([job_id, prompt, options_data]):
            _logger.warning("Job missing data in payload: %s", job_payload)
            await q.move_to_dlq(str(job_payload), "missing_data_in_payload")
            continue

        try:
            options = JobOptions(**options_data)
        except Exception as e:
            _logger.error("Failed to parse JobOptions: %s", e)
            await q.move_to_dlq(str(job_payload), f"invalid_options: {e}")
            continue

        try:
            lock = q.client.lock(f"job:lock:{job_id}", timeout=settings.JOB_LOCK_TIMEOUT)
            acquired = await lock.acquire(blocking=False)
            if not acquired:
                _logger.info("Job %s is already being processed; skipping", job_id)
                # Re-queue the job with a delay if needed, or just let another worker pick it up.
                # For now, we'll just skip. A small delay might be good.
                await asyncio.sleep(1)
                await q.push(job_payload) # Re-queue
                continue

            try:
                await orch.run(job_id=job_id, prompt=prompt, options=options)
            finally:
                try:
                    await lock.release()
                except Exception:
                    _logger.warning("Failed to release lock for job %s", job_id)
        except Exception as e:
            _logger.exception("CRITICAL: Unhandled exception processing job %s.", job_id)
            await q.move_to_dlq(str(job_payload), f"unhandled_exception: {e}")

if __name__ == "__main__":
    asyncio.run(main())
