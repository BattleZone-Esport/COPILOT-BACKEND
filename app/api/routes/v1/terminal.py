"""
Terminal API routes for AI-powered command execution and system management.
"""

import logging
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status, BackgroundTasks
from pydantic import BaseModel, Field

from app.api.deps import get_database, validate_csrf, get_current_user
from app.services.terminal_manager import TerminalManager, CommandStatus
from app.services.agents.terminal_agent import TerminalAgent
from app.repositories.terminal_repository import TerminalRepository
from app.exceptions.custom_exceptions import (
    raise_bad_request_error,
    raise_not_found_error,
    raise_authorization_error,
    raise_internal_error
)
from app.core.config import get_settings

router = APIRouter(tags=["terminal"])
_logger = logging.getLogger(__name__)


# Request/Response Models
class CommandRequest(BaseModel):
    """Request model for command execution."""
    command: str = Field(..., description="Command to execute or natural language query")
    is_natural_language: bool = Field(default=False, description="Whether the command is in natural language")
    timeout: Optional[int] = Field(default=30, ge=1, le=300, description="Command timeout in seconds")
    working_dir: Optional[str] = Field(default=None, description="Working directory for command")
    env_vars: Optional[Dict[str, str]] = Field(default=None, description="Additional environment variables")
    require_confirmation: bool = Field(default=True, description="Require confirmation for risky commands")
    context: Optional[Dict[str, Any]] = Field(default=None, description="Additional context for AI interpretation")


class CommandResponse(BaseModel):
    """Response model for command execution."""
    command_id: str
    command: str
    status: str
    stdout: Optional[str] = None
    stderr: Optional[str] = None
    exit_code: Optional[int] = None
    duration_ms: Optional[int] = None
    error_message: Optional[str] = None
    interpretation: Optional[str] = None
    executed_at: datetime


class LogRequest(BaseModel):
    """Request model for log operations."""
    log_file: str = Field(..., description="Log file path")
    content: Optional[str] = Field(default=None, description="Content to write (for write operations)")
    append: bool = Field(default=True, description="Append to file instead of overwriting")
    max_lines: Optional[int] = Field(default=100, ge=1, le=10000, description="Maximum lines to read")


class LogResponse(BaseModel):
    """Response model for log operations."""
    log_file: str
    content: Optional[str] = None
    size_bytes: Optional[int] = None
    last_modified: Optional[datetime] = None
    lines_count: Optional[int] = None


class ExplainRequest(BaseModel):
    """Request model for command explanation."""
    command: str = Field(..., description="Command to explain")


class SuggestRequest(BaseModel):
    """Request model for command suggestions."""
    context: str = Field(..., description="Context or goal for suggestions")
    num_suggestions: int = Field(default=5, ge=1, le=10, description="Number of suggestions")


class HistoryQuery(BaseModel):
    """Query parameters for command history."""
    limit: int = Field(default=20, ge=1, le=100, description="Number of items to return")
    status_filter: Optional[str] = Field(default=None, description="Filter by status")
    start_time: Optional[datetime] = Field(default=None, description="Filter by start time")
    end_time: Optional[datetime] = Field(default=None, description="Filter by end time")


# Initialize services
terminal_manager = TerminalManager(
    working_dir="/home/user/workspace",
    default_timeout=30,
    max_timeout=300,
    strict_mode=False  # Can be set to True for production
)

terminal_agent = TerminalAgent(
    terminal_manager=terminal_manager,
    model=get_settings().DEFAULT_CHATBOT_MODEL,
    use_openrouter=True
)


@router.post("/execute", response_model=CommandResponse, dependencies=[Depends(validate_csrf)])
async def execute_command(
    request: CommandRequest,
    background_tasks: BackgroundTasks,
    db=Depends(get_database),
    current_user=Depends(get_current_user)
) -> CommandResponse:
    """
    Execute a command or natural language query in the terminal.
    
    This endpoint supports both direct bash commands and natural language queries.
    Natural language queries are interpreted by the AI agent before execution.
    """
    command_id = str(uuid.uuid4())
    repo = TerminalRepository(db)
    
    _logger.info(
        "Received command execution request from user %s: %s",
        current_user.get("id"),
        request.command[:100]
    )
    
    try:
        # Store command in database
        await repo.create_command(
            command_id=command_id,
            user_id=current_user.get("id"),
            command=request.command,
            status=CommandStatus.PENDING.value
        )
        
        # Process natural language if needed
        if request.is_natural_language:
            # Parse natural language to command
            intent = await terminal_agent.parse_natural_language(
                request.command,
                request.context
            )
            
            _logger.info(
                "Parsed natural language to command: %s (confidence: %.2f)",
                intent.command,
                intent.confidence
            )
            
            # Check confidence threshold
            if intent.confidence < 0.5:
                await repo.update_command(
                    command_id=command_id,
                    status=CommandStatus.ERROR.value,
                    error_message=f"Low confidence in interpretation: {intent.confidence:.2f}"
                )
                
                raise_bad_request_error(
                    "Unable to interpret command with sufficient confidence",
                    {"confidence": intent.confidence, "interpretation": intent.to_dict()}
                )
            
            # Execute the interpreted command
            result = await terminal_agent.execute_intent(
                intent,
                timeout=request.timeout,
                require_confirmation=request.require_confirmation
            )
            
            # Get interpretation of output
            interpretation = await terminal_agent.interpret_output(
                result,
                request.command
            )
            
        else:
            # Execute direct command
            result = await terminal_manager.execute_command(
                command=request.command,
                timeout=request.timeout,
                working_dir=request.working_dir,
                env_vars=request.env_vars
            )
            interpretation = None
        
        # Update command in database
        await repo.update_command(
            command_id=command_id,
            status=result.status.value,
            stdout=result.stdout,
            stderr=result.stderr,
            exit_code=result.exit_code,
            duration_ms=result.duration_ms,
            error_message=result.error_message,
            completed_at=datetime.now(timezone.utc)
        )
        
        return CommandResponse(
            command_id=command_id,
            command=result.command,
            status=result.status.value,
            stdout=result.stdout,
            stderr=result.stderr,
            exit_code=result.exit_code,
            duration_ms=result.duration_ms,
            error_message=result.error_message,
            interpretation=interpretation,
            executed_at=result.executed_at
        )
        
    except Exception as e:
        _logger.exception("Error executing command")
        
        # Update command status
        await repo.update_command(
            command_id=command_id,
            status=CommandStatus.ERROR.value,
            error_message=str(e),
            completed_at=datetime.now(timezone.utc)
        )
        
        if isinstance(e, HTTPException):
            raise
        
        raise_internal_error(
            "Failed to execute command",
            details={"error": str(e)}
        )


@router.get("/logs/{log_file:path}", response_model=LogResponse)
async def read_log_file(
    log_file: str,
    max_lines: int = Query(100, ge=1, le=10000),
    db=Depends(get_database),
    current_user=Depends(get_current_user)
) -> LogResponse:
    """
    Read contents of a log file.
    
    This endpoint safely reads log files with size limits and access controls.
    """
    repo = TerminalRepository(db)
    
    # Check if user has access to this log file
    if not await repo.can_access_log(current_user.get("id"), log_file):
        raise_authorization_error(
            "Access to this log file is not allowed"
        )
    
    # Read the log file
    success, content, error = await terminal_manager.read_file(
        file_path=f"/var/log/{log_file}",
        max_size=10 * 1024 * 1024  # 10 MB limit
    )
    
    if not success:
        raise_not_found_error(
            "Log file",
            log_file,
            {"error": error}
        )
    
    # Limit lines if needed
    if max_lines and content:
        lines = content.split('\n')
        if len(lines) > max_lines:
            content = '\n'.join(lines[-max_lines:])
    
    # Store log access in database
    await repo.store_log_access(
        user_id=current_user.get("id"),
        log_file=log_file,
        action="read",
        size=len(content) if content else 0
    )
    
    return LogResponse(
        log_file=log_file,
        content=content,
        size_bytes=len(content) if content else 0,
        lines_count=len(content.split('\n')) if content else 0,
        last_modified=datetime.now(timezone.utc)
    )


@router.post("/logs", response_model=LogResponse, dependencies=[Depends(validate_csrf)])
async def write_log_file(
    request: LogRequest,
    db=Depends(get_database),
    current_user=Depends(get_current_user)
) -> LogResponse:
    """
    Write or append to a log file.
    
    This endpoint safely writes to log files with proper access controls.
    """
    repo = TerminalRepository(db)
    
    # Check if user has write access
    if not await repo.can_write_log(current_user.get("id"), request.log_file):
        raise_authorization_error(
            "Write access to this log file is not allowed"
        )
    
    # Write to the log file
    success, error = await terminal_manager.write_file(
        file_path=f"/var/log/{request.log_file}",
        content=request.content,
        append=request.append
    )
    
    if not success:
        raise_bad_request_error(
            "Failed to write to log file",
            {"error": error}
        )
    
    # Store log access in database
    await repo.store_log_access(
        user_id=current_user.get("id"),
        log_file=request.log_file,
        action="write",
        size=len(request.content) if request.content else 0
    )
    
    return LogResponse(
        log_file=request.log_file,
        size_bytes=len(request.content) if request.content else 0,
        last_modified=datetime.now(timezone.utc)
    )


@router.get("/history", response_model=List[CommandResponse])
async def get_command_history(
    limit: int = Query(20, ge=1, le=100),
    status_filter: Optional[str] = Query(None),
    db=Depends(get_database),
    current_user=Depends(get_current_user)
) -> List[CommandResponse]:
    """
    Get command execution history for the current user.
    """
    repo = TerminalRepository(db)
    
    # Get commands from database
    commands = await repo.get_user_commands(
        user_id=current_user.get("id"),
        limit=limit,
        status_filter=status_filter
    )
    
    return [
        CommandResponse(
            command_id=cmd["command_id"],
            command=cmd["command"],
            status=cmd["status"],
            stdout=cmd.get("stdout"),
            stderr=cmd.get("stderr"),
            exit_code=cmd.get("exit_code"),
            duration_ms=cmd.get("duration_ms"),
            error_message=cmd.get("error_message"),
            executed_at=cmd["started_at"]
        )
        for cmd in commands
    ]


@router.post("/history/clear", dependencies=[Depends(validate_csrf)])
async def clear_command_history(
    db=Depends(get_database),
    current_user=Depends(get_current_user)
) -> Dict[str, str]:
    """
    Clear command history for the current user.
    """
    repo = TerminalRepository(db)
    
    # Clear user's command history
    deleted_count = await repo.clear_user_commands(current_user.get("id"))
    
    # Also clear in-memory history
    terminal_manager.clear_command_history()
    
    return {
        "message": f"Successfully cleared {deleted_count} commands from history"
    }


@router.get("/status")
async def get_terminal_status(
    current_user=Depends(get_current_user)
) -> Dict[str, Any]:
    """
    Get terminal system status and information.
    """
    system_info = terminal_manager.get_system_info()
    
    return {
        "status": "operational",
        "system_info": system_info,
        "user": current_user.get("email"),
        "limits": {
            "max_timeout": terminal_manager.max_timeout,
            "max_output_size": terminal_manager.max_output_size,
            "strict_mode": terminal_manager.strict_mode
        },
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


@router.post("/explain", response_model=Dict[str, Any])
async def explain_command(
    request: ExplainRequest,
    current_user=Depends(get_current_user)
) -> Dict[str, Any]:
    """
    Get AI explanation of what a command does before execution.
    """
    explanation = await terminal_agent.explain_command(request.command)
    
    # Check if command is allowed
    is_allowed, denial_reason = await terminal_manager.check_command_syntax(request.command)
    
    explanation["is_allowed"] = is_allowed
    if not is_allowed:
        explanation["denial_reason"] = denial_reason
    
    return explanation


@router.post("/suggest", response_model=List[Dict[str, str]])
async def suggest_commands(
    request: SuggestRequest,
    current_user=Depends(get_current_user)
) -> List[Dict[str, str]]:
    """
    Get AI suggestions for commands based on context.
    """
    suggestions = await terminal_agent.suggest_commands(
        context=request.context,
        num_suggestions=request.num_suggestions
    )
    
    return suggestions


@router.get("/system-info")
async def get_system_info(
    current_user=Depends(get_current_user)
) -> Dict[str, Any]:
    """
    Get detailed system information.
    """
    # Execute system info commands
    commands = [
        ("uname -a", "System kernel information"),
        ("df -h", "Disk usage"),
        ("free -h", "Memory usage"),
        ("ps aux --sort=-%mem | head -10", "Top memory processes"),
        ("ps aux --sort=-%cpu | head -10", "Top CPU processes"),
        ("netstat -tulpn 2>/dev/null | head -20", "Network connections"),
        ("docker ps 2>/dev/null", "Docker containers"),
        ("systemctl list-units --failed 2>/dev/null", "Failed services")
    ]
    
    results = {}
    
    for command, description in commands:
        result = await terminal_manager.execute_command(
            command=command,
            timeout=5
        )
        
        results[description] = {
            "command": command,
            "output": result.stdout if result.status == CommandStatus.SUCCESS else result.error_message,
            "status": result.status.value
        }
    
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "system_info": results
    }