
from __future__ import annotations
from typing import Optional, Literal, List, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime


JobStatus = Literal["queued", "running", "succeeded", "failed", "debugging", "fixing"]
AgentName = Literal["coder", "debugger", "fixer", "chatbot"]


class JobOptions(BaseModel):
    mode: Literal["sync", "queue"] = "sync"
    pipeline_name: Optional[Literal["ureshii-p1", "chat"]] = "ureshii-p1"
    coder_model: Optional[str] = None
    debugger_model: Optional[str] = None
    fixer_model: Optional[str] = None


class PromptRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=16000)
    options: JobOptions = Field(default_factory=JobOptions)


class JobCreate(BaseModel):
    job_id: str
    user_id: Optional[str] = None
    prompt: str
    options: JobOptions
    status: JobStatus = "queued"
    created_at: datetime
    updated_at: datetime


class JobPublic(BaseModel):
    job_id: str
    status: JobStatus
    created_at: datetime
    updated_at: datetime
    error: Optional[Dict[str, Any]] = None
    intermediate_message: Optional[str] = None
    intermediate_output: Optional[str] = None


class JobResult(BaseModel):
    job_id: str
    final_output: Optional[str] = None
    artifacts: List[Dict[str, Any]] = Field(default_factory=list)


class RunRecord(BaseModel):
    job_id: str
    agent: AgentName
    input: str
    output: Optional[str] = None
    status: Literal["running", "succeeded", "failed"] = "running"
    started_at: datetime
    completed_at: Optional[datetime] = None
    error: Optional[Dict[str, Any]] = None


class ArtifactRecord(BaseModel):
    job_id: str
    agent: AgentName
    type: Literal["code", "diff", "report", "metadata"]
    content: Any
    created_at: datetime
