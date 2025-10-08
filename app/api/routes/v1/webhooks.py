from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter, Request, HTTPException, Depends
from app.core.config import get_settings
from app.api.deps import get_orchestrator
from app.models.schemas import JobOptions
from app.repositories.job_repository import JobRepository
from app.queues.qstash import QStashPublisher
from app.db.mongo import get_db

router = APIRouter(prefix="/v1/webhooks", tags=["webhooks"])
_logger = logging.getLogger(__name__)


@router.post("/qstash")
async def qstash_webhook(request: Request, orchestrator=Depends(get_orchestrator)):
    settings = get_settings()
    body = await request.body()

    if settings.QSTASH_VERIFY_SIGNATURE:
        sig = request.headers.get("Upstash-Signature")
        if not sig:
            raise HTTPException(status_code=400, detail="Missing signature")
        if not QStashPublisher.verify_signature(dict(request.headers), body):
            raise HTTPException(status_code=401, detail="Invalid signature")

    data = await request.json()
    job_id = data.get("job_id")
    if not job_id:
        raise HTTPException(status_code=400, detail="Missing job_id")

    db = await get_db()
    repo = JobRepository(db)
    job = await repo.get_job_public(job_id)

    if not job:
        _logger.warning("Webhook received for non-existent job_id: %s", job_id)
        # Instead of erroring, we could try to use the payload if it exists
        prompt = data.get("prompt")
        options_data = data.get("options") or {}
        options = JobOptions(**options_data)
        if not prompt:
             raise HTTPException(status_code=404, detail=f"Job {job_id} not found and no prompt in payload")
    else:
        # This is not ideal, we need to reconstruct the full job from the repo
        # but for now we just need the prompt and options
        full_job_doc = await db.jobs.find_one({"job_id": job_id})
        if not full_job_doc:
             raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
        prompt = full_job_doc.get("prompt")
        options = JobOptions(**full_job_doc.get("options", {}))


    if not prompt:
        return {"status": "ignored", "reason": "No prompt found for job"}

    result = await orchestrator.run(job_id=job_id, prompt=prompt, options=options)
    return {"status": "ok", **result}
