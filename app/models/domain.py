from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Dict, Any, Literal

AgentName = Literal["coder", "debugger", "fixer"]


@dataclass
class AgentResult:
    agent: AgentName
    input: str
    output: Optional[str]
    artifact_type: str  # "code" | "diff" | "report" | "metadata"
    artifact_content: Any
