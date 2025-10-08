from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo.errors import DuplicateKeyError

from app.models.schemas import (
    ArtifactRecord,
    JobCreate,
    JobPublic,
    JobResult,
    RunRecord,
)

_logger = logging.getLogger(__name__)


class JobRepository:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db

    async def create_job(self, data: JobCreate) -> None:
        try:
            await self.db.jobs.insert_one(data.model_dump())
        except DuplicateKeyError:
            _logger.warning("Duplicate job_id: %s", data.job_id)
            raise ValueError(f"Job with id {data.job_id} already exists.")

    async def update_job_status(
        self,
        job_id: str,
        status: str,
        error: Optional[Dict[str, Any]] = None,
        final_output: Optional[str] = None,
        intermediate_message: Optional[str] = None,
        intermediate_output: Optional[str] = None,
    ) -> None:
        now = datetime.now(timezone.utc)
        update = {"$set": {"status": status, "updated_at": now}}
        if error:
            update["$set"]["error"] = error
        if final_output is not None:
            update["$set"]["final_output"] = final_output
        if intermediate_message is not None:
            update["$set"]["intermediate_message"] = intermediate_message
        if intermediate_output is not None:
            update["$set"]["intermediate_output"] = intermediate_output
        await self.db.jobs.update_one({"job_id": job_id}, update)

    async def get_job_public(self, job_id: str) -> Optional[JobPublic]:
        doc = await self.db.jobs.find_one({"job_id": job_id}, {"_id": 0})
        return JobPublic(**doc) if doc else None

    async def get_jobs_for_user(
        self, user_id: str, skip: int = 0, limit: int = 100
    ) -> List[JobPublic]:
        """Fetches a paginated list of jobs for a specific user."""
        cursor = (
            self.db.jobs.find({"user_id": user_id}, {"_id": 0})
            .sort("created_at", -1)
            .skip(skip)
            .limit(limit)
        )
        docs = await cursor.to_list(length=limit)
        return [JobPublic(**doc) for doc in docs]

    async def get_job_result(self, job_id: str) -> Optional[JobResult]:
        job = await self.db.jobs.find_one(
            {"job_id": job_id}, {"_id": 0, "final_output": 1, "job_id": 1}
        )
        if not job:
            return None
        # Here, we might still want to limit the number of artifacts returned
        # for a single job result, but for now we fetch all.
        artifacts = await self.db.artifacts.find({"job_id": job_id}, {"_id": 0}).to_list(
            1000
        )
        return JobResult(
            job_id=job["job_id"], final_output=job.get("final_output"), artifacts=artifacts
        )

    async def add_run(self, run: RunRecord) -> None:
        await self.db.runs.insert_one(run.model_dump())

    async def update_run(self, job_id: str, agent: str, update: Dict[str, Any]) -> None:
        now = datetime.now(timezone.utc)
        if "completed_at" not in update:
            update["updated_at"] = now
        await self.db.runs.update_one({"job_id": job_id, "agent": agent}, {"$set": update})

    async def add_artifact(self, art: ArtifactRecord) -> None:
        await self.db.artifacts.insert_one(art.model_dump())
