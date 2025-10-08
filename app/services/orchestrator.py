
from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Dict, Any, Optional

from app.core.config import get_settings
from app.db.mongo import get_db
from app.repositories.job_repository import JobRepository
from app.models.schemas import JobCreate, JobOptions, RunRecord, ArtifactRecord
from app.services.agents.coder import CoderAgent
from app.services.agents.debugger import DebuggerAgent
from app.services.agents.fixer import FixerAgent
from app.services.agents.chatbot import ChatbotAgent

_logger = logging.getLogger(__name__)


class Orchestrator:
    def __init__(self):
        s = get_settings()
        self.defaults = {
            "coder": s.DEFAULT_CODER_MODEL,
            "debugger": s.DEFAULT_DEBUGGER_MODEL,
            "fixer": s.DEFAULT_FIXER_MODEL,
        }
        self.coder = CoderAgent()
        self.debugger = DebuggerAgent()
        self.fixer = FixerAgent()
        self.chatbot = ChatbotAgent()

    async def create_job(self, prompt: str, options: JobOptions) -> str:
        job_id = str(uuid.uuid4())
        db = await get_db()
        repo = JobRepository(db)
        now = datetime.utcnow()
        job = JobCreate(
            job_id=job_id,
            prompt=prompt,
            options=options,
            status="queued" if options.mode == "queue" else "running",
            created_at=now,
            updated_at=now,
        )
        await repo.create_job(job)
        return job_id

    async def run(self, job_id: str, prompt: str, options: JobOptions) -> Dict[str, Any]:
        # Default to the coding pipeline if mode is not specified
        mode = options.pipeline_name or "ureshii-p1"

        if mode == "chat":
            return await self.run_chat(job_id, prompt, options)
        elif mode == "ureshii-p1":
            return await self.run_ureshii_p1_pipeline(job_id, prompt, options)
        else:
            _logger.error(f"Unknown pipeline: {mode}")
            return {"job_id": job_id, "status": "failed", "error": f"Unknown pipeline: {mode}"}

    async def run_chat(self, job_id: str, prompt: str, options: JobOptions) -> Dict[str, Any]:
        db = await get_db()
        repo = JobRepository(db)
        try:
            chat_response = await self.chatbot.run(prompt)
            await repo.update_job_status(job_id, "succeeded", final_output=chat_response)
            return {"job_id": job_id, "status": "succeeded", "final_output": chat_response}
        except Exception as e:
            _logger.exception("Chat failed for job %s", job_id)
            await repo.update_job_status(job_id, "failed", error={"message": str(e)})
            return {"job_id": job_id, "status": "failed", "error": str(e)}

    async def run_ureshii_p1_pipeline(self, job_id: str, prompt: str, options: JobOptions) -> Dict[str, Any]:
        db = await get_db()
        repo = JobRepository(db)

        coder_model = options.coder_model or self.defaults["coder"]
        debugger_model = options.debugger_model or self.defaults["debugger"]
        fixer_model = options.fixer_model or self.defaults["fixer"]

        coder_res = None
        try:
            # Coder Agent
            await repo.update_job_status(job_id, "running", intermediate_message="Generating code with Ureshii-P1...")
            run = RunRecord(job_id=job_id, agent="coder", input=prompt, status="running", started_at=datetime.utcnow())
            await repo.add_run(run)
            coder_res = await self.coder.run(job_id, prompt, coder_model)
            await repo.update_run(job_id, "coder", {
                "output": coder_res.output,
                "status": "succeeded",
                "completed_at": datetime.utcnow(),
            })
            await repo.add_artifact(ArtifactRecord(
                job_id=job_id, agent="coder", type="code",
                content=coder_res.artifact_content, created_at=datetime.utcnow()
            ))

            await repo.update_job_status(job_id, "debugging", intermediate_message="Code generated, debugging in progress...", intermediate_output=coder_res.output)

            # Debugger Agent
            debug_input = coder_res.output or ""
            run = RunRecord(job_id=job_id, agent="debugger", input=debug_input, status="running", started_at=datetime.utcnow())
            await repo.add_run(run)
            dbg_res = await self.debugger.run(job_id, debug_input, debugger_model)

            if not dbg_res or not dbg_res.output:
                _logger.warning("Debugger failed or returned no output for job %s. Falling back to coder's output.", job_id)
                final = coder_res.output or ""
                await repo.update_job_status(job_id, "succeeded", final_output=final)
                return {"job_id": job_id, "status": "succeeded", "final_output": final, "message": "Debugging failed, returning initial generated code."}

            await repo.update_run(job_id, "debugger", {
                "output": dbg_res.output,
                "status": "succeeded",
                "completed_at": datetime.utcnow(),
            })
            await repo.add_artifact(ArtifactRecord(
                job_id=job_id, agent="debugger", type="report",
                content=dbg_res.artifact_content, created_at=datetime.utcnow()
            ))
            await repo.update_job_status(job_id, "fixing", intermediate_message=f"Debugging complete. Report: {dbg_res.output}. Fixing code...", intermediate_output=coder_res.output)

            # Fixer Agent
            fixer_input = f"Original code:\n{coder_res.output or ''}\n\nDebugger report:\n{dbg_res.output or ''}\n\nReturn only corrected code."
            run = RunRecord(job_id=job_id, agent="fixer", input=fixer_input, status="running", started_at=datetime.utcnow())
            await repo.add_run(run)
            fixer_res = await self.fixer.run(job_id, fixer_input, fixer_model)

            if not fixer_res or not fixer_res.output:
                _logger.warning("Fixer failed or returned no output for job %s. Falling back to coder's output.", job_id)
                final = coder_res.output or ""
                await repo.update_job_status(job_id, "succeeded", final_output=final)
                return {"job_id": job_id, "status": "succeeded", "final_output": final, "message": "Code fixing failed, returning initial generated code."}

            await repo.update_run(job_id, "fixer", {
                "output": fixer_res.output,
                "status": "succeeded",
                "completed_at": datetime.utcnow(),
            })
            await repo.add_artifact(ArtifactRecord(
                job_id=job_id, agent="fixer", type="code",
                content=fixer_res.artifact_content, created_at=datetime.utcnow()
            ))

            final = fixer_res.output or ""
            await repo.update_job_status(job_id, "succeeded", final_output=final)
            return {"job_id": job_id, "status": "succeeded", "final_output": final}

        except Exception as e:
            _logger.exception("Pipeline failed for job %s", job_id)
            if coder_res and coder_res.output:
                await repo.update_job_status(job_id, "failed", error={"message": str(e)}, final_output=coder_res.output)
                return {"job_id": job_id, "status": "failed", "error": str(e), "final_output": coder_res.output, "message": "An error occurred, returning initial generated code."}
            else:
                await repo.update_job_status(job_id, "failed", error={"message": str(e)})
                return {"job_id": job_id, "status": "failed", "error": str(e)}

