
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.api.deps import get_orchestrator, validate_csrf
from app.core.config import get_settings
from app.db.mongo import AsyncIOMotorDatabase, get_db
from app.models.schemas import JobPublic, JobListPublic, PromptRequest
from app.repositories.job_repository import JobRepository

router = APIRouter(prefix="/v1/jobs", tags=["jobs"])
_logger = logging.getLogger(__name__)


async def get_user_id_from_session(
    request: Request, db: AsyncIOMotorDatabase = Depends(get_db)
) -> Optional[str]:
    user = request.session.get("user")
    if user and "email" in user:
        user_record = await db.users.find_one({"email": user["email"]})
        if user_record:
            return user_record.get("user_id")
    raise HTTPException(status_code=403, detail="User not authenticated")

@router.post(
    "",
    response_model=JobPublic,
    status_code=201,
    dependencies=[Depends(validate_csrf)],
)
async def create_job(
    payload: PromptRequest,
    orchestrator=Depends(get_orchestrator),
    user_id: Optional[str] = Depends(get_user_id_from_session),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> JobPublic:
    settings = get_settings()
    if payload.prompt and len(payload.prompt) > settings.PROMPT_MAX_CHARS:
        raise HTTPException(
            status_code=413, detail=f"Prompt too large (max {settings.PROMPT_MAX_CHARS} chars)"
        )

    try:
        job_id = await orchestrator.create_job(
            payload.prompt, payload.options, user_id=user_id
        )
        if payload.options.mode == "sync":
            await orchestrator.run(job_id, payload.prompt, payload.options)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception:
        _logger.exception("Error creating job")
        raise HTTPException(status_code=500, detail="An internal error occurred.")

    repo = JobRepository(db)
    job = await repo.get_job_public(job_id)
    if not job:
        raise HTTPException(
            status_code=500, detail="Job could not be retrieved after creation."
        )
    return job


@router.get("", response_model=JobListPublic)
async def list_jobs(
    user_id: str = Depends(get_user_id_from_session),
    skip: int = Query(0, ge=0, description="Number of items to skip"),
    limit: int = Query(10, gt=0, le=100, description="Number of items to return"),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> JobListPublic:
    """Lists jobs for the authenticated user with pagination."""
    repo = JobRepository(db)
    jobs = await repo.get_jobs_for_user(user_id, skip=skip, limit=limit)
    # In a real app, we might also want to return the total count for pagination UIs.
    return JobListPublic(jobs=jobs)


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
        raise HTTPException(status_code=404, detail="Job not found or result not ready")
    return result.model_dump()
