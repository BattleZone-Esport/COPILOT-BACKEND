from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.api.deps import get_orchestrator, validate_csrf
from app.core.logging import request_id_var
from app.db.mongo import AsyncIOMotorDatabase, get_db
from app.models.schemas import JobListPublic, JobPublic, PromptRequest
from app.repositories.job_repository import JobRepository

router = APIRouter(tags=["jobs"])  # prefix will be added in main.py
_logger = logging.getLogger(__name__)


async def get_user_id_from_session(
    request: Request, db: AsyncIOMotorDatabase = Depends(get_db)
) -> Optional[str]:
    """Retrieves the user ID from the session, or raises a 403 error."""
    user = request.session.get("user")
    if user and "email" in user:
        user_record = await db.users.find_one({"email": user["email"]})
        if user_record:
            return user_record.get("user_id")
    # Deny access if user is not found in session or DB
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
    """Creates a new job and returns its public model."""
    request_id = request_id_var.get()
    _logger.info(
        "Received job creation request for user %s.",
        user_id,
        extra={"request_id": request_id, "user_id": user_id},
    )

    try:
        job_id = await orchestrator.create_job(
            prompt=payload.prompt,
            options=payload.options,
            user_id=user_id,
            request_id=request_id,
        )
        # If the job is synchronous, run it immediately.
        if payload.options.mode == "sync":
            await orchestrator.run(job_id, payload.prompt, payload.options)

    except ValueError as e:
        # Handle validation errors from the orchestrator (e.g., invalid options)
        _logger.warning("Job creation failed due to validation error: %s", e)
        raise HTTPException(status_code=422, detail=str(e))
    except Exception:
        # Catch all other exceptions and log them.
        _logger.exception("An unexpected error occurred during job creation.")
        raise HTTPException(status_code=500, detail="An internal error occurred.")

    repo = JobRepository(db)
    job = await repo.get_job_public(job_id)
    if not job:
        _logger.error("Could not retrieve job %s after creation.", job_id)
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
    return JobListPublic(jobs=jobs)


@router.get("/{job_id}", response_model=JobPublic)
async def get_job(job_id: str, db: AsyncIOMotorDatabase = Depends(get_db)) -> JobPublic:
    """Retrieves the public details of a single job."""
    repo = JobRepository(db)
    job = await repo.get_job_public(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.get("/{job_id}/result")
async def get_job_result(
    job_id: str, db: AsyncIOMotorDatabase = Depends(get_db)
) -> Dict[str, Any]:
    """Retrieves the final result and artifacts for a completed job."""
    repo = JobRepository(db)
    result = await repo.get_job_result(job_id)
    if not result:
        raise HTTPException(status_code=404, detail="Job result not found or not ready")
    return result.model_dump()
