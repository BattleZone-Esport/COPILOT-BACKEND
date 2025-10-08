
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from app.api.deps import get_orchestrator, validate_csrf
from app.core.config import get_settings
from app.db.mongo import get_db, AsyncIOMotorDatabase
from app.models.schemas import PromptRequest, JobPublic
from app.repositories.job_repository import JobRepository
from app.queues.redis_queue import RedisQueue
from app.queues.qstash import QStashPublisher

router = APIRouter(prefix="/v1/jobs", tags=["jobs"])
_logger = logging.getLogger(__name__)

async def get_user_id_from_session(request: Request, db: AsyncIOMotorDatabase = Depends(get_db)) -> Optional[str]:
    user = request.session.get("user")
    if user and "email" in user: # Using email as a proxy for user_id for now
        # In a real app, you'd probably have a user_id in the session
        user_record = await db.users.find_one({"email": user["email"]})
        if user_record:
            return user_record.get("user_id")
    return None

@router.post("", response_model=JobPublic, dependencies=[Depends(validate_csrf)])
async def create_job(
    payload: PromptRequest, 
    orchestrator=Depends(get_orchestrator), 
    user_id: Optional[str] = Depends(get_user_id_from_session),
    db: AsyncIOMotorDatabase = Depends(get_db)
) -> JobPublic:
    settings = get_settings()
    if payload.prompt and len(payload.prompt) > settings.PROMPT_MAX_CHARS:
        raise HTTPException(status_code=413, detail=f"Prompt too large (max {settings.PROMPT_MAX_CHARS} chars)")

    job_id = await orchestrator.create_job(payload.prompt, payload.options, user_id=user_id)

    if payload.options.mode == "queue":
        if settings.QUEUE_BACKEND == "redis":
            q = RedisQueue()
            await q.enqueue({"job_id": job_id, "prompt": payload.prompt, "options": payload.options.model_dump()})
        elif settings.QUEUE_BACKEND == "qstash":
            q = QStashPublisher()
            await q.enqueue({"job_id": job_id, "prompt": payload.prompt, "options": payload.options.model_dump()})
        else:
            raise HTTPException(status_code=400, detail="Queue mode requested but QUEUE_BACKEND=none")

        repo = JobRepository(db)
        job = await repo.get_job_public(job_id)
        assert job
        return job

    # sync mode
    result = await orchestrator.run(job_id, payload.prompt, payload.options)
    repo = JobRepository(db)
    job = await repo.get_job_public(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found after processing")
    return job


@router.get("/{job_id}", response_model=JobPublic)
async def get_job(job_id: str, db: AsyncIOMotorDatabase = Depends(get_db)) -> JobPublic:
    repo = JobRepository(db)
    job = await repo.get_job_public(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.get("/{job_id}/result")
async def get_job_result(job_id: str, db: AsyncIOMotorDatabase = Depends(get_db)) -> Dict[str, Any]:
    repo = JobRepository(db)
    result = await repo.get_job_result(job_id)
    if not result:
        raise HTTPException(status_code=404, detail="Job not found")
    return result.model_dump()
