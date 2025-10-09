
from __future__ import annotations

import logging
import uuid
import base64
from datetime import datetime, timezone
from typing import Dict, Any, Optional

from app.core.config import get_settings
from app.db.mongo import get_db, get_client
from app.repositories.job_repository import JobRepository
from app.models.schemas import JobCreate, JobOptions, RunRecord, ArtifactRecord
from app.services.agents.coder import CoderAgent
from app.services.agents.debugger import DebuggerAgent
from app.services.agents.fixer import FixerAgent
from app.services.agents.chatbot import ChatbotAgent
from app.queues import get_queue
from app.services.github_client import GitHubClient, get_github_client

_logger = logging.getLogger(__name__)


class Orchestrator:
    def __init__(self, github_client: GitHubClient):
        s = get_settings()
        self.github_client = github_client
        self.defaults = {
            "coder": s.DEFAULT_CODER_MODEL,
            "debugger": s.DEFAULT_DEBUGGER_MODEL,
            "fixer": s.DEFAULT_FIXER_MODEL,
        }
        self.allowed_models = s.ALLOWED_MODELS
        self.coder = CoderAgent()
        self.debugger = DebuggerAgent()
        self.fixer = FixerAgent()
        self.chatbot = ChatbotAgent()

    async def create_job(self, prompt: str, options: JobOptions, user_id: Optional[str] = None, request_id: Optional[str] = None) -> str:
        job_id = str(uuid.uuid4())
        db = await get_db()
        repo = JobRepository(db)
        now = datetime.now(timezone.utc)
        job = JobCreate(
            job_id=job_id,
            request_id=request_id,
            user_id=user_id,
            prompt=prompt,
            options=options,
            status="queued" if options.mode == "queue" else "running",
            created_at=now,
            updated_at=now,
        )
        await repo.create_job(job)
        if options.mode == "queue":
            queue = get_queue()
            if queue:
                await queue.enqueue_job(job_id, prompt, options)
        return job_id

    async def run(self, job_id: str, prompt: str, options: JobOptions) -> Dict[str, Any]:
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
        client = await get_client()
        repo = JobRepository(db)

        coder_model = options.coder_model or self.defaults["coder"]
        if coder_model not in self.allowed_models:
            raise ValueError(f"Model {coder_model} is not allowed")

        debugger_model = options.debugger_model or self.defaults["debugger"]
        if debugger_model not in self.allowed_models:
            raise ValueError(f"Model {debugger_model} is not allowed")

        fixer_model = options.fixer_model or self.defaults["fixer"]
        if fixer_model not in self.allowed_models:
            raise ValueError(f"Model {fixer_model} is not allowed")

        coder_res = None
        async with await client.start_session() as session:
            async with session.start_transaction():
                try:
                    await repo.update_job_status(job_id, "running", intermediate_message="Generating code with Ureshii-P1...")
                    run = RunRecord(job_id=job_id, agent="coder", input=prompt, status="running", started_at=datetime.now(timezone.utc))
                    await repo.add_run(run)
                    coder_res = await self.coder.run(job_id, prompt, coder_model)
                    await repo.update_run(job_id, "coder", {
                        "output": coder_res.output,
                        "status": "succeeded",
                        "completed_at": datetime.now(timezone.utc),
                    })
                    await repo.add_artifact(ArtifactRecord(
                        job_id=job_id, agent="coder", type="code",
                        content=coder_res.artifact_content, created_at=datetime.now(timezone.utc)
                    ))

                    await repo.update_job_status(job_id, "debugging", intermediate_message="Code generated, debugging in progress...", intermediate_output=coder_res.output)

                    dbg_res = None
                    try:
                        debug_input = coder_res.output or ""
                        run = RunRecord(job_id=job_id, agent="debugger", input=debug_input, status="running", started_at=datetime.now(timezone.utc))
                        await repo.add_run(run)
                        dbg_res = await self.debugger.run(job_id, debug_input, debugger_model)
                    except Exception as e:
                        _logger.exception("Debugger agent failed for job %s", job_id)

                    if not dbg_res or not dbg_res.output:
                        _logger.warning("Debugger failed or returned no output for job %s. Falling back to coder's output.", job_id)
                        final = coder_res.output or ""
                        await self.handle_github_pr(job_id, options, final, prompt, "Debugging failed, returning initial code.")
                        await repo.update_job_status(job_id, "succeeded", final_output=final)
                        return {"job_id": job_id, "status": "succeeded", "final_output": final, "message": "Debugging failed, returning initial generated code."}

                    await repo.update_run(job_id, "debugger", {
                        "output": dbg_res.output,
                        "status": "succeeded",
                        "completed_at": datetime.now(timezone.utc),
                    })
                    await repo.add_artifact(ArtifactRecord(
                        job_id=job_id, agent="debugger", type="report",
                        content=dbg_res.artifact_content, created_at=datetime.now(timezone.utc)
                    ))
                    await repo.update_job_status(job_id, "fixing", intermediate_message=f"Debugging complete. Report: {dbg_res.output}. Fixing code...", intermediate_output=coder_res.output)

                    fixer_res = None
                    try:
                        fixer_input = f"Original code:\n{coder_res.output or ''}\n\nDebugger report:\n{dbg_res.output or ''}\n\nReturn only corrected code."
                        run = RunRecord(job_id=job_id, agent="fixer", input=fixer_input, status="running", started_at=datetime.now(timezone.utc))
                        await repo.add_run(run)
                        fixer_res = await self.fixer.run(job_id, fixer_input, fixer_model)
                    except Exception as e:
                        _logger.exception("Fixer agent failed for job %s", job_id)


                    if not fixer_res or not fixer_res.output:
                        _logger.warning("Fixer failed or returned no output for job %s. Falling back to coder's output.", job_id)
                        final = coder_res.output or ""
                        await self.handle_github_pr(job_id, options, final, prompt, "Fixer failed, returning initial code.")
                        await repo.update_job_status(job_id, "succeeded", final_output=final)
                        return {"job_id": job_id, "status": "succeeded", "final_output": final, "message": "Code fixing failed, returning initial generated code."}

                    await repo.update_run(job_id, "fixer", {
                        "output": fixer_res.output,
                        "status": "succeeded",
                        "completed_at": datetime.now(timezone.utc),
                    })
                    await repo.add_artifact(ArtifactRecord(
                        job_id=job_id, agent="fixer", type="code",
                        content=fixer_res.artifact_content, created_at=datetime.now(timezone.utc)
                    ))

                    final = fixer_res.output or ""
                    await self.handle_github_pr(job_id, options, final, prompt, "Code generated and fixed.")
                    await repo.update_job_status(job_id, "succeeded", final_output=final)
                    return {"job_id": job_id, "status": "succeeded", "final_output": final}

                except Exception as e:
                    _logger.exception("Pipeline failed for job %s", job_id)
                    await session.abort_transaction()
                    if coder_res and coder_res.output:
                        await repo.update_job_status(job_id, "failed", error={"message": str(e)}, final_output=coder_res.output)
                        return {"job_id": job_id, "status": "failed", "error": str(e), "final_output": coder_res.output, "message": "An error occurred, returning initial generated code."}
                    else:
                        await repo.update_job_status(job_id, "failed", error={"message": str(e)})
                        return {"job_id": job_id, "status": "failed", "error": str(e)}
    
    async def handle_github_pr(self, job_id: str, options: JobOptions, code: str, prompt: str, pr_body: str):
        if not options.github_repo or not options.github_branch or not options.github_file_path:
            _logger.warning(f"GitHub options not set for job {job_id}. Skipping PR creation.")
            return

        try:
            repo_name = options.github_repo
            base_branch = options.github_branch
            file_path = options.github_file_path
            new_branch = f"ureshii-bot/{job_id[:8]}"
            commit_message = f"feat: ✨ Ureshii-Bot generated code for job {job_id}"
            pr_title = f"Ureshii-Bot: {prompt[:50]}..."

            await self.github_client.create_branch(repo_name, new_branch, base_branch)
            
            content_b64 = base64.b64encode(code.encode("utf-8")).decode("utf-8")
            await self.github_client.create_or_update_file(
                repo_name, file_path, content_b64, new_branch, commit_message
            )
            
            pr = await self.github_client.create_pull_request(
                repo_name, pr_title, new_branch, base_branch, pr_body
            )
            _logger.info(f"Created PR for job {job_id}: {pr['html_url']}")

        except Exception as e:
            _logger.exception(f"Failed to create GitHub PR for job {job_id}")


async def get_orchestrator() -> Orchestrator:
    github_client = await get_github_client()
    return Orchestrator(github_client)
