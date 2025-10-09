"""
AI Terminal Agent for natural language command processing and execution.
"""

import logging
import re
import json
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime, timezone

from openai import AsyncOpenAI

from app.services.terminal_manager import TerminalManager, CommandResult, CommandStatus
from app.core.config import get_settings
from app.exceptions.custom_exceptions import (
    AIServiceException,
    TerminalException
)

_logger = logging.getLogger(__name__)


class CommandIntent:
    """Represents the intent extracted from natural language."""
    
    def __init__(
        self,
        command: str,
        description: str,
        confidence: float,
        parameters: Optional[Dict[str, Any]] = None,
        safety_notes: Optional[List[str]] = None
    ):
        self.command = command
        self.description = description
        self.confidence = confidence
        self.parameters = parameters or {}
        self.safety_notes = safety_notes or []
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "command": self.command,
            "description": self.description,
            "confidence": self.confidence,
            "parameters": self.parameters,
            "safety_notes": self.safety_notes
        }


class TerminalAgent:
    """
    AI agent for interpreting natural language commands and executing them
    through the terminal manager.
    """
    
    def __init__(
        self,
        terminal_manager: Optional[TerminalManager] = None,
        model: str = "gpt-3.5-turbo",
        use_openrouter: bool = True
    ):
        self.terminal_manager = terminal_manager or TerminalManager()
        self.model = model
        self.use_openrouter = use_openrouter
        self.settings = get_settings()
        
        # Initialize OpenAI client
        if use_openrouter:
            self.client = AsyncOpenAI(
                api_key=self.settings.OPENROUTER_API_KEY,
                base_url="https://openrouter.ai/api/v1",
                default_headers={
                    "HTTP-Referer": self.settings.OPENROUTER_SITE_URL or "http://localhost",
                    "X-Title": self.settings.OPENROUTER_SITE_NAME or "Ureshii Terminal"
                }
            )
        else:
            self.client = AsyncOpenAI(api_key=self.settings.OPENAI_API_KEY)
        
        # Command patterns for common operations
        self.command_patterns = self._initialize_command_patterns()
    
    def _initialize_command_patterns(self) -> Dict[str, Dict[str, Any]]:
        """Initialize common command patterns for quick matching."""
        return {
            "list_files": {
                "patterns": [
                    r"(show|list|display)\s+(files|directory|folder)",
                    r"what\s+files\s+are",
                    r"ls\s*$"
                ],
                "command": "ls -la",
                "description": "List files in current directory"
            },
            "show_logs": {
                "patterns": [
                    r"show\s+(recent\s+)?logs?",
                    r"(display|view)\s+.*\s+logs?",
                    r"tail\s+.*log"
                ],
                "command": "tail -n 50 {log_file}",
                "description": "Show recent log entries"
            },
            "system_info": {
                "patterns": [
                    r"(system|server)\s+info",
                    r"(cpu|memory|disk)\s+usage",
                    r"resource\s+status"
                ],
                "command": "echo 'CPU:' && top -bn1 | head -5 && echo '\nMemory:' && free -h && echo '\nDisk:' && df -h",
                "description": "Show system resource usage"
            },
            "process_list": {
                "patterns": [
                    r"(show|list)\s+processes?",
                    r"what.*running",
                    r"ps\s+"
                ],
                "command": "ps aux | head -20",
                "description": "List running processes"
            },
            "network_info": {
                "patterns": [
                    r"network\s+(info|status)",
                    r"(show|list)\s+connections?",
                    r"netstat"
                ],
                "command": "netstat -tuln | head -20",
                "description": "Show network connections"
            },
            "search_files": {
                "patterns": [
                    r"(find|search)\s+.*\s+files?",
                    r"where\s+is\s+",
                    r"locate\s+"
                ],
                "command": "find . -name '{pattern}' -type f 2>/dev/null | head -20",
                "description": "Search for files"
            },
            "check_service": {
                "patterns": [
                    r"(check|status)\s+.*\s+service",
                    r"is\s+.*\s+running"
                ],
                "command": "systemctl status {service} 2>/dev/null || service {service} status 2>/dev/null",
                "description": "Check service status"
            },
            "docker_status": {
                "patterns": [
                    r"docker\s+(ps|status|containers?)",
                    r"(show|list)\s+containers?"
                ],
                "command": "docker ps",
                "description": "Show Docker containers"
            },
            "git_status": {
                "patterns": [
                    r"git\s+status",
                    r"(show|check)\s+git"
                ],
                "command": "git status",
                "description": "Show Git repository status"
            }
        }
    
    async def parse_natural_language(
        self,
        user_input: str,
        context: Optional[Dict[str, Any]] = None
    ) -> CommandIntent:
        """
        Parse natural language input and extract command intent.
        
        Args:
            user_input: Natural language command from user
            context: Additional context for command interpretation
        
        Returns:
            CommandIntent with parsed command and metadata
        """
        # First, check if it matches any common patterns
        quick_match = self._quick_pattern_match(user_input)
        if quick_match:
            return quick_match
        
        # Use AI for more complex interpretation
        try:
            system_prompt = """You are a terminal command interpreter. Convert natural language requests into safe bash commands.
            
            Rules:
            1. Only generate safe, read-only commands unless explicitly asked for modifications
            2. Use standard Unix/Linux commands
            3. Include appropriate flags for better output
            4. Avoid destructive operations (rm -rf, dd, format, etc.)
            5. Limit output with head/tail when appropriate
            6. Include error handling (2>/dev/null) when needed
            
            Response format (JSON):
            {
                "command": "the bash command to execute",
                "description": "brief description of what the command does",
                "confidence": 0.0 to 1.0 (how confident you are),
                "parameters": {"key": "value"},
                "safety_notes": ["any safety concerns or warnings"]
            }
            """
            
            user_prompt = f"Convert this request to a bash command: {user_input}"
            
            if context:
                user_prompt += f"\n\nContext: {json.dumps(context)}"
            
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.3,
                max_tokens=500,
                response_format={"type": "json_object"}
            )
            
            # Parse AI response
            ai_response = json.loads(response.choices[0].message.content)
            
            return CommandIntent(
                command=ai_response.get("command", ""),
                description=ai_response.get("description", ""),
                confidence=ai_response.get("confidence", 0.5),
                parameters=ai_response.get("parameters", {}),
                safety_notes=ai_response.get("safety_notes", [])
            )
            
        except Exception as e:
            _logger.exception("Error parsing natural language with AI")
            raise AIServiceException(
                message="Failed to parse command",
                details={"error": str(e)}
            )
    
    def _quick_pattern_match(self, user_input: str) -> Optional[CommandIntent]:
        """Quick pattern matching for common commands."""
        user_input_lower = user_input.lower().strip()
        
        for cmd_type, pattern_info in self.command_patterns.items():
            for pattern in pattern_info["patterns"]:
                if re.search(pattern, user_input_lower):
                    # Extract parameters if needed
                    params = {}
                    command = pattern_info["command"]
                    
                    # Handle parameterized commands
                    if "{" in command:
                        # Extract parameter values from user input
                        if cmd_type == "show_logs":
                            # Extract log file name
                            match = re.search(r"(\S+\.log)", user_input_lower)
                            if match:
                                params["log_file"] = match.group(1)
                            else:
                                params["log_file"] = "/var/log/app.log"
                            command = command.format(**params)
                        
                        elif cmd_type == "search_files":
                            # Extract search pattern
                            match = re.search(r"(find|search|where)\s+.*\s+['\"]?(\S+)['\"]?", user_input_lower)
                            if match:
                                params["pattern"] = match.group(2)
                            else:
                                params["pattern"] = "*"
                            command = command.format(**params)
                        
                        elif cmd_type == "check_service":
                            # Extract service name
                            match = re.search(r"(check|status)\s+(\S+)\s+service", user_input_lower)
                            if match:
                                params["service"] = match.group(2)
                            else:
                                params["service"] = "nginx"
                            command = command.format(**params)
                    
                    return CommandIntent(
                        command=command,
                        description=pattern_info["description"],
                        confidence=0.9,
                        parameters=params
                    )
        
        return None
    
    async def execute_intent(
        self,
        intent: CommandIntent,
        timeout: Optional[int] = None,
        require_confirmation: bool = True
    ) -> CommandResult:
        """
        Execute a command intent through the terminal manager.
        
        Args:
            intent: CommandIntent to execute
            timeout: Command timeout in seconds
            require_confirmation: Whether to require confirmation for risky commands
        
        Returns:
            CommandResult from execution
        """
        # Check confidence threshold
        if intent.confidence < 0.5:
            return CommandResult(
                command=intent.command,
                status=CommandStatus.ERROR,
                error_message=f"Low confidence ({intent.confidence:.2f}) in command interpretation"
            )
        
        # Check for risky commands
        if require_confirmation and self._is_risky_command(intent.command):
            _logger.warning(
                "Risky command requires confirmation: %s",
                intent.command
            )
            return CommandResult(
                command=intent.command,
                status=CommandStatus.DENIED,
                error_message="This command requires manual confirmation due to potential risks"
            )
        
        # Execute command
        result = await self.terminal_manager.execute_command(
            command=intent.command,
            timeout=timeout
        )
        
        return result
    
    def _is_risky_command(self, command: str) -> bool:
        """Check if a command is potentially risky."""
        risky_keywords = [
            "rm ", "delete", "remove",
            "chmod", "chown",
            "kill", "pkill",
            "reboot", "shutdown",
            "format", "mkfs",
            ">", ">>",  # File redirects
        ]
        
        command_lower = command.lower()
        return any(keyword in command_lower for keyword in risky_keywords)
    
    async def interpret_output(
        self,
        result: CommandResult,
        user_query: Optional[str] = None
    ) -> str:
        """
        Interpret command output and provide user-friendly explanation.
        
        Args:
            result: CommandResult to interpret
            user_query: Original user query for context
        
        Returns:
            Human-readable interpretation of the output
        """
        if result.status == CommandStatus.DENIED:
            return f"❌ Command was denied: {result.error_message}"
        
        if result.status == CommandStatus.TIMEOUT:
            return f"⏱️ Command timed out: {result.error_message}"
        
        if result.status == CommandStatus.ERROR:
            if result.stderr:
                return f"❌ Command failed with error:\n{result.stderr[:500]}"
            else:
                return f"❌ Command failed: {result.error_message or 'Unknown error'}"
        
        # For successful commands, interpret the output
        if not result.stdout:
            return "✅ Command executed successfully (no output)"
        
        # Use AI to interpret complex output if needed
        if len(result.stdout) > 1000 or (user_query and "explain" in user_query.lower()):
            try:
                interpretation = await self._ai_interpret_output(
                    result.stdout,
                    result.command,
                    user_query
                )
                return f"✅ Command executed successfully:\n\n{interpretation}"
            except Exception as e:
                _logger.warning("Failed to AI-interpret output: %s", e)
        
        # Return raw output for simple cases
        return f"✅ Command executed successfully:\n\n{result.stdout[:2000]}"
    
    async def _ai_interpret_output(
        self,
        output: str,
        command: str,
        user_query: Optional[str]
    ) -> str:
        """Use AI to interpret command output."""
        try:
            system_prompt = """You are a helpful assistant that explains terminal command outputs.
            Provide clear, concise explanations that highlight the key information.
            Use bullet points for multiple items.
            Keep explanations under 500 words."""
            
            user_prompt = f"Command executed: {command}\n\n"
            if user_query:
                user_prompt += f"User's original question: {user_query}\n\n"
            user_prompt += f"Output:\n{output[:3000]}\n\n"
            user_prompt += "Please explain this output in simple terms."
            
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.5,
                max_tokens=500
            )
            
            return response.choices[0].message.content
            
        except Exception as e:
            _logger.exception("Error interpreting output with AI")
            # Fallback to raw output
            return output[:2000]
    
    async def suggest_commands(
        self,
        context: str,
        num_suggestions: int = 5
    ) -> List[Dict[str, str]]:
        """
        Suggest relevant commands based on context.
        
        Args:
            context: Current context or user's goal
            num_suggestions: Number of suggestions to provide
        
        Returns:
            List of command suggestions with descriptions
        """
        try:
            system_prompt = f"""Suggest {num_suggestions} relevant bash commands for the given context.
            
            Response format (JSON):
            {{
                "suggestions": [
                    {{
                        "command": "the bash command",
                        "description": "what it does",
                        "use_case": "when to use it"
                    }}
                ]
            }}
            """
            
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Context: {context}"}
                ],
                temperature=0.7,
                max_tokens=500,
                response_format={"type": "json_object"}
            )
            
            result = json.loads(response.choices[0].message.content)
            return result.get("suggestions", [])
            
        except Exception as e:
            _logger.exception("Error generating command suggestions")
            # Return default suggestions
            return [
                {
                    "command": "ls -la",
                    "description": "List all files with details",
                    "use_case": "View directory contents"
                },
                {
                    "command": "ps aux | grep",
                    "description": "Search running processes",
                    "use_case": "Find specific processes"
                },
                {
                    "command": "tail -f /var/log/app.log",
                    "description": "Follow log file in real-time",
                    "use_case": "Monitor application logs"
                }
            ]
    
    async def explain_command(self, command: str) -> Dict[str, Any]:
        """
        Explain what a command does before execution.
        
        Args:
            command: Command to explain
        
        Returns:
            Dictionary with explanation details
        """
        try:
            system_prompt = """Explain bash commands in detail.
            
            Response format (JSON):
            {
                "summary": "brief one-line summary",
                "components": [
                    {"part": "command part", "explanation": "what it does"}
                ],
                "risks": ["potential risks or side effects"],
                "alternatives": ["alternative commands that achieve similar results"],
                "output_preview": "what kind of output to expect"
            }
            """
            
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Explain this command: {command}"}
                ],
                temperature=0.3,
                max_tokens=500,
                response_format={"type": "json_object"}
            )
            
            return json.loads(response.choices[0].message.content)
            
        except Exception as e:
            _logger.exception("Error explaining command")
            return {
                "summary": "Unable to explain command",
                "error": str(e)
            }