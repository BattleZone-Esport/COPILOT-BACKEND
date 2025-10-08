from __future__ import annotations

import asyncio
import logging

from app.core.config import get_settings
from app.db.mongo import ensure_indexes, get_db
from app.queues.redis_queue import RedisQueue
from app.services.orchestrator import Orchestrator

logging.basicConfig(level=logging.INFO)
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
        job = await q.pop(timeout=15)
        if not job:
            continue
        job_id = job.get("job_id")
        prompt = job.get("prompt")
        options = job.get("options")
        if not job_id:
            _logger.warning("Job missing job_id: %s", job)
            continue

        if not prompt or not options:
            try:
                db = await get_db()
                doc = await db.jobs.find_one({"job_id": job_id})
                if doc:
                    prompt = prompt or doc.get("prompt")
                    options = options or doc.get("options")
            except Exception:
                _logger.exception("Failed fetching job %s from DB", job_id)

        if not prompt or not options:
            _logger.warning("Job %s missing prompt/options after DB fetch, skipping", job_id)
            continue

        try:
            lock = q.client.lock(f"job:lock:{job_id}", timeout=300)
            acquired = await lock.acquire(blocking=False)
            if not acquired:
                _logger.info("Job %s is already being processed; skipping", job_id)
                continue

            try:
                await orch.run_pipeline(job_id, prompt, options)
            finally:
                try:
                    await lock.release()
                except Exception:
                    _logger.warning("Failed to release lock for job %s", job_id)
        except Exception:
            _logger.exception("Failed processing job %s", job_id)


if __name__ == "__main__":
    asyncio.run(main())
