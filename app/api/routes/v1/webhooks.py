from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Request
from app.core.config import get_settings
from app.db.mongo import get_db
from app.models.schemas import JobOptions, WebhookPayload
from app.repositories.job_repository import JobRepository
from app.services.orchestrator import Orchestrator, get_orchestrator
from app.queues.qstash import QStashPublisher

router = APIRouter(prefix="/v1/webhooks", tags=["webhooks"])
_logger = logging.getLogger(__name__)


@router.post("/qstash")
async def qstash_webhook(
    request: Request, orchestrator: Orchestrator = Depends(get_orchestrator)
) -> Dict[str, Any]:
    settings = get_settings()
    body = (await request.body()).decode()

    if settings.QSTASH_VERIFY_SIGNATURE:
        sig = request.headers.get("Upstash-Signature")
        if not sig:
            raise HTTPException(status_code=400, detail="Missing signature")
        if not QStashPublisher.verify_signature(dict(request.headers), body):
            raise HTTPException(status_code=401, detail="Invalid signature")

    try:
        payload = WebhookPayload.model_validate_json(body)
    except Exception as e:
        _logger.error("Webhook payload validation failed: %s", e)
        raise HTTPException(status_code=422, detail="Invalid payload")

    job_id = payload.job_id
    prompt = payload.prompt
    options = payload.options

    db = await get_db()
    repo = JobRepository(db)
    job = await repo.get_job_public(job_id)

    if not job:
        _logger.warning("Webhook received for non-existent job_id: %s", job_id)
        # The job does not exist, but we have a valid payload so we can proceed
    
    if not prompt:
         raise HTTPException(status_code=400, detail=f"No prompt found for job {job_id}")

    result = await orchestrator.run(job_id=job_id, prompt=prompt, options=options)
    return {"status": "ok", **result}
