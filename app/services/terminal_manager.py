"""
AI Terminal Manager Service for secure command execution and system management.
"""

import asyncio
import os
import subprocess
import shlex
import logging
import hashlib
import json
import re
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime, timezone
from pathlib import Path
from enum import Enum
import resource
import signal

from app.core.config import get_settings
from app.exceptions.custom_exceptions import (
    TerminalException,
    CommandNotAllowedException,
    CommandTimeoutException,
    ResourceLimitException
)

_logger = logging.getLogger(__name__)


class CommandStatus(Enum):
    """Command execution status."""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    ERROR = "error"
    TIMEOUT = "timeout"
    KILLED = "killed"
    DENIED = "denied"


class CommandResult:
    """Result of command execution."""
    
    def __init__(
        self,
        command: str,
        status: CommandStatus,
        stdout: str = "",
        stderr: str = "",
        exit_code: Optional[int] = None,
        duration_ms: Optional[int] = None,
        error_message: Optional[str] = None
    ):
        self.command = command
        self.status = status
        self.stdout = stdout
        self.stderr = stderr
        self.exit_code = exit_code
        self.duration_ms = duration_ms
        self.error_message = error_message
        self.executed_at = datetime.now(timezone.utc)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "command": self.command,
            "status": self.status.value,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "exit_code": self.exit_code,
            "duration_ms": self.duration_ms,
            "error_message": self.error_message,
            "executed_at": self.executed_at.isoformat()
        }


class SecurityPolicy:
    """Security policy for command execution."""
    
    # Dangerous commands that should never be allowed
    BLOCKED_COMMANDS = {
        "rm -rf /",
        "dd",
        "mkfs",
        "format",
        ":(){:|:&};:",  # Fork bomb
        "chmod 777 /",
        "chown",
        "shutdown",
        "reboot",
        "init",
        "systemctl",
        "service"
    }
    
    # Dangerous patterns
    DANGEROUS_PATTERNS = [
        r"rm\s+-rf\s+/",  # Recursive delete from root
        r">\s*/dev/sd[a-z]",  # Direct write to disk
        r"curl.*\|\s*sh",  # Pipe curl to shell
        r"wget.*\|\s*sh",  # Pipe wget to shell
        r"/etc/passwd",  # Password file access
        r"/etc/shadow",  # Shadow password file
        r"sudo\s+",  # Sudo commands
        r"su\s+",  # Switch user
    ]
    
    # Allowed command whitelist (if enabled)
    ALLOWED_COMMANDS = {
        "ls", "pwd", "echo", "cat", "grep", "find", "head", "tail",
        "wc", "sort", "uniq", "cut", "awk", "sed", "date", "whoami",
        "ps", "top", "df", "du", "free", "uptime", "hostname",
        "ping", "curl", "wget", "git", "docker", "npm", "pip",
        "python", "node", "java", "go", "cargo"
    }
    
    @classmethod
    def is_command_allowed(
        cls,
        command: str,
        strict_mode: bool = False
    ) -> Tuple[bool, Optional[str]]:
        """
        Check if command is allowed based on security policy.
        
        Returns:
            Tuple of (is_allowed, denial_reason)
        """
        command_lower = command.lower().strip()
        
        # Check against blocked commands
        for blocked in cls.BLOCKED_COMMANDS:
            if blocked in command_lower:
                return False, f"Command contains blocked pattern: {blocked}"
        
        # Check against dangerous patterns
        for pattern in cls.DANGEROUS_PATTERNS:
            if re.search(pattern, command, re.IGNORECASE):
                return False, f"Command matches dangerous pattern: {pattern}"
        
        # In strict mode, only allow whitelisted commands
        if strict_mode:
            # Extract the base command
            parts = shlex.split(command)
            if not parts:
                return False, "Empty command"
            
            base_command = Path(parts[0]).name
            if base_command not in cls.ALLOWED_COMMANDS:
                return False, f"Command '{base_command}' not in whitelist"
        
        # Check for shell injection attempts
        if cls._has_shell_injection(command):
            return False, "Potential shell injection detected"
        
        return True, None
    
    @staticmethod
    def _has_shell_injection(command: str) -> bool:
        """Check for potential shell injection patterns."""
        injection_patterns = [
            r";\s*rm",  # Command chaining with rm
            r"&&\s*rm",  # Conditional execution with rm
            r"\|\|\s*rm",  # Or execution with rm
            r"`.*`",  # Command substitution
            r"\$\(.*\)",  # Command substitution
            r"\${.*}",  # Variable expansion with braces
            r"<\(.*\)",  # Process substitution
            r">\(.*\)",  # Process substitution
        ]
        
        for pattern in injection_patterns:
            if re.search(pattern, command):
                return True
        
        return False


class TerminalManager:
    """
    Secure terminal manager for command execution with sandboxing.
    """
    
    def __init__(
        self,
        working_dir: Optional[str] = None,
        env_vars: Optional[Dict[str, str]] = None,
        max_output_size: int = 10 * 1024 * 1024,  # 10 MB
        default_timeout: int = 30,
        max_timeout: int = 300,
        strict_mode: bool = False
    ):
        self.working_dir = working_dir or os.getcwd()
        self.env_vars = env_vars or {}
        self.max_output_size = max_output_size
        self.default_timeout = default_timeout
        self.max_timeout = max_timeout
        self.strict_mode = strict_mode
        self._command_history: List[CommandResult] = []
    
    async def execute_command(
        self,
        command: str,
        timeout: Optional[int] = None,
        working_dir: Optional[str] = None,
        env_vars: Optional[Dict[str, str]] = None,
        capture_output: bool = True,
        use_pty: bool = False
    ) -> CommandResult:
        """
        Execute a command in a sandboxed environment.
        
        Args:
            command: Command to execute
            timeout: Execution timeout in seconds
            working_dir: Working directory for command
            env_vars: Additional environment variables
            capture_output: Whether to capture stdout/stderr
            use_pty: Whether to use pseudo-terminal
        
        Returns:
            CommandResult with execution details
        """
        # Validate command
        is_allowed, denial_reason = SecurityPolicy.is_command_allowed(
            command,
            self.strict_mode
        )
        
        if not is_allowed:
            _logger.warning(
                "Command denied: %s. Reason: %s",
                command,
                denial_reason
            )
            return CommandResult(
                command=command,
                status=CommandStatus.DENIED,
                error_message=denial_reason
            )
        
        # Prepare execution environment
        timeout = min(timeout or self.default_timeout, self.max_timeout)
        working_dir = working_dir or self.working_dir
        
        # Merge environment variables
        env = os.environ.copy()
        env.update(self.env_vars)
        if env_vars:
            env.update(env_vars)
        
        # Remove sensitive environment variables
        sensitive_vars = [
            "AWS_SECRET_ACCESS_KEY",
            "DATABASE_PASSWORD",
            "API_KEY",
            "SECRET_KEY",
            "PRIVATE_KEY"
        ]
        for var in sensitive_vars:
            env.pop(var, None)
        
        _logger.info(
            "Executing command: %s (timeout: %ds)",
            command,
            timeout
        )
        
        start_time = asyncio.get_event_loop().time()
        
        try:
            # Create subprocess
            if use_pty:
                process = await self._create_pty_process(
                    command,
                    working_dir,
                    env
                )
            else:
                process = await asyncio.create_subprocess_shell(
                    command,
                    stdout=asyncio.subprocess.PIPE if capture_output else None,
                    stderr=asyncio.subprocess.PIPE if capture_output else None,
                    cwd=working_dir,
                    env=env,
                    preexec_fn=self._set_resource_limits
                )
            
            # Execute with timeout
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=timeout
                )
            except asyncio.TimeoutError:
                # Kill process on timeout
                process.kill()
                await process.wait()
                
                duration_ms = int((asyncio.get_event_loop().time() - start_time) * 1000)
                
                result = CommandResult(
                    command=command,
                    status=CommandStatus.TIMEOUT,
                    duration_ms=duration_ms,
                    error_message=f"Command timed out after {timeout} seconds"
                )
                
                self._command_history.append(result)
                return result
            
            # Process output
            duration_ms = int((asyncio.get_event_loop().time() - start_time) * 1000)
            
            stdout_str = ""
            stderr_str = ""
            
            if capture_output:
                # Decode and truncate output if needed
                if stdout:
                    stdout_str = stdout.decode('utf-8', errors='replace')
                    if len(stdout_str) > self.max_output_size:
                        stdout_str = stdout_str[:self.max_output_size] + "\n[Output truncated]"
                
                if stderr:
                    stderr_str = stderr.decode('utf-8', errors='replace')
                    if len(stderr_str) > self.max_output_size:
                        stderr_str = stderr_str[:self.max_output_size] + "\n[Output truncated]"
            
            # Determine status
            status = CommandStatus.SUCCESS if process.returncode == 0 else CommandStatus.ERROR
            
            result = CommandResult(
                command=command,
                status=status,
                stdout=stdout_str,
                stderr=stderr_str,
                exit_code=process.returncode,
                duration_ms=duration_ms
            )
            
            self._command_history.append(result)
            
            _logger.info(
                "Command completed: %s (status: %s, exit_code: %d, duration: %dms)",
                command,
                status.value,
                process.returncode,
                duration_ms
            )
            
            return result
            
        except Exception as e:
            duration_ms = int((asyncio.get_event_loop().time() - start_time) * 1000)
            
            _logger.exception(
                "Error executing command: %s",
                command
            )
            
            result = CommandResult(
                command=command,
                status=CommandStatus.ERROR,
                duration_ms=duration_ms,
                error_message=str(e)
            )
            
            self._command_history.append(result)
            return result
    
    async def _create_pty_process(
        self,
        command: str,
        working_dir: str,
        env: Dict[str, str]
    ):
        """Create process with pseudo-terminal."""
        import pty
        import fcntl
        import struct
        import termios
        
        # Create PTY
        master, slave = pty.openpty()
        
        # Set terminal size
        winsize = struct.pack('HHHH', 24, 80, 0, 0)
        fcntl.ioctl(slave, termios.TIOCSWINSZ, winsize)
        
        # Create subprocess
        process = await asyncio.create_subprocess_shell(
            command,
            stdin=slave,
            stdout=slave,
            stderr=slave,
            cwd=working_dir,
            env=env,
            preexec_fn=self._set_resource_limits
        )
        
        os.close(slave)
        
        # Make master non-blocking
        import fcntl
        flags = fcntl.fcntl(master, fcntl.F_GETFL)
        fcntl.fcntl(master, fcntl.F_SETFL, flags | os.O_NONBLOCK)
        
        return process
    
    @staticmethod
    def _set_resource_limits():
        """Set resource limits for subprocess."""
        # Limit CPU time (5 minutes)
        resource.setrlimit(resource.RLIMIT_CPU, (300, 300))
        
        # Limit memory (1 GB)
        resource.setrlimit(resource.RLIMIT_AS, (1024 * 1024 * 1024, 1024 * 1024 * 1024))
        
        # Limit number of processes
        resource.setrlimit(resource.RLIMIT_NPROC, (50, 50))
        
        # Limit file size (100 MB)
        resource.setrlimit(resource.RLIMIT_FSIZE, (100 * 1024 * 1024, 100 * 1024 * 1024))
        
        # Limit number of open files
        resource.setrlimit(resource.RLIMIT_NOFILE, (100, 100))
    
    async def read_file(
        self,
        file_path: str,
        max_size: Optional[int] = None
    ) -> Tuple[bool, str, Optional[str]]:
        """
        Safely read a file with size limits.
        
        Returns:
            Tuple of (success, content, error_message)
        """
        max_size = max_size or self.max_output_size
        
        try:
            file_path = Path(file_path)
            
            # Check if file exists
            if not file_path.exists():
                return False, "", f"File not found: {file_path}"
            
            # Check if it's a file
            if not file_path.is_file():
                return False, "", f"Not a file: {file_path}"
            
            # Check file size
            file_size = file_path.stat().st_size
            if file_size > max_size:
                return False, "", f"File too large: {file_size} bytes (max: {max_size})"
            
            # Read file
            content = file_path.read_text(encoding='utf-8', errors='replace')
            
            return True, content, None
            
        except Exception as e:
            _logger.exception("Error reading file: %s", file_path)
            return False, "", str(e)
    
    async def write_file(
        self,
        file_path: str,
        content: str,
        append: bool = False,
        create_dirs: bool = True
    ) -> Tuple[bool, Optional[str]]:
        """
        Safely write to a file.
        
        Returns:
            Tuple of (success, error_message)
        """
        try:
            file_path = Path(file_path)
            
            # Create directories if needed
            if create_dirs:
                file_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Write file
            mode = 'a' if append else 'w'
            file_path.write_text(content, encoding='utf-8')
            
            _logger.info(
                "File written: %s (append: %s, size: %d bytes)",
                file_path,
                append,
                len(content)
            )
            
            return True, None
            
        except Exception as e:
            _logger.exception("Error writing file: %s", file_path)
            return False, str(e)
    
    def get_command_history(
        self,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Get command execution history."""
        history = self._command_history
        
        if limit:
            history = history[-limit:]
        
        return [cmd.to_dict() for cmd in history]
    
    def clear_command_history(self):
        """Clear command execution history."""
        self._command_history.clear()
    
    async def check_command_syntax(self, command: str) -> Tuple[bool, Optional[str]]:
        """
        Check command syntax without executing.
        
        Returns:
            Tuple of (is_valid, error_message)
        """
        try:
            # Try to parse the command
            shlex.split(command)
            
            # Check security policy
            is_allowed, denial_reason = SecurityPolicy.is_command_allowed(
                command,
                self.strict_mode
            )
            
            if not is_allowed:
                return False, denial_reason
            
            return True, None
            
        except ValueError as e:
            return False, f"Invalid command syntax: {str(e)}"
    
    def get_system_info(self) -> Dict[str, Any]:
        """Get system information."""
        import platform
        import psutil
        
        return {
            "platform": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "architecture": platform.machine(),
            "processor": platform.processor(),
            "python_version": platform.python_version(),
            "cpu_count": psutil.cpu_count(),
            "memory_total": psutil.virtual_memory().total,
            "memory_available": psutil.virtual_memory().available,
            "disk_usage": psutil.disk_usage('/').percent,
            "working_directory": self.working_dir
        }