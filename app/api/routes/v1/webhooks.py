from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter, Request, HTTPException, Depends
from app.core.config import get_settings
from app.api.deps import get_orchestrator
from app.models.schemas import JobOptions
from app.queues.qstash import QStashPublisher

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

    # In queued mode, pull job from DB to get prompt/options
    # For simplicity we ask the webhook publisher to include prompt/options if needed.
    prompt = data.get("prompt")
    options_data = data.get("options") or {}
    options = JobOptions(**options_data)
    if not prompt:
        return {"status": "ignored", "reason": "No prompt provided in webhook payload"}

    result = await orchestrator.run_pipeline(job_id, prompt, options)
    return {"status": "ok", **result}
