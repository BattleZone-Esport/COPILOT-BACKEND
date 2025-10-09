"""
Test suite for terminal functionality.
"""

import pytest
import asyncio
from unittest.mock import Mock, patch, MagicMock

from app.services.terminal_manager import (
    TerminalManager, 
    CommandResult, 
    CommandStatus,
    SecurityPolicy
)
from app.services.agents.terminal_agent import TerminalAgent, CommandIntent


class TestSecurityPolicy:
    """Test security policy for command validation."""
    
    def test_blocked_commands(self):
        """Test that dangerous commands are blocked."""
        dangerous_commands = [
            "rm -rf /",
            "dd if=/dev/zero of=/dev/sda",
            "mkfs.ext4 /dev/sda",
            ":(){:|:&};:",
            "chmod 777 /",
            "shutdown -h now",
        ]
        
        for cmd in dangerous_commands:
            is_allowed, reason = SecurityPolicy.is_command_allowed(cmd)
            assert not is_allowed, f"Dangerous command should be blocked: {cmd}"
            assert reason is not None
    
    def test_allowed_commands(self):
        """Test that safe commands are allowed."""
        safe_commands = [
            "ls -la",
            "pwd",
            "echo 'Hello World'",
            "cat file.txt",
            "grep pattern file.txt",
            "ps aux",
            "df -h",
        ]
        
        for cmd in safe_commands:
            is_allowed, reason = SecurityPolicy.is_command_allowed(cmd)
            assert is_allowed, f"Safe command should be allowed: {cmd}"
            assert reason is None
    
    def test_shell_injection_detection(self):
        """Test detection of shell injection attempts."""
        injection_attempts = [
            "echo test; rm -rf /",
            "cat file.txt && rm important.file",
            "ls || rm -rf /",
            "echo `rm -rf /`",
            "echo $(rm -rf /)",
        ]
        
        for cmd in injection_attempts:
            is_allowed, reason = SecurityPolicy.is_command_allowed(cmd)
            assert not is_allowed, f"Injection attempt should be blocked: {cmd}"
    
    def test_strict_mode(self):
        """Test strict mode whitelist enforcement."""
        # Commands not in whitelist
        non_whitelisted = [
            "netcat -l 8080",
            "nmap scanme.nmap.org",
            "tcpdump -i any",
        ]
        
        for cmd in non_whitelisted:
            is_allowed, reason = SecurityPolicy.is_command_allowed(cmd, strict_mode=True)
            assert not is_allowed, f"Non-whitelisted command should be blocked in strict mode: {cmd}"


@pytest.mark.asyncio
class TestTerminalManager:
    """Test terminal manager functionality."""
    
    async def test_execute_safe_command(self):
        """Test execution of a safe command."""
        manager = TerminalManager()
        result = await manager.execute_command("echo 'Test output'", timeout=5)
        
        assert result.status == CommandStatus.SUCCESS
        assert result.stdout.strip() == "Test output"
        assert result.exit_code == 0
        assert result.duration_ms > 0
    
    async def test_execute_command_with_timeout(self):
        """Test command timeout."""
        manager = TerminalManager()
        result = await manager.execute_command("sleep 10", timeout=1)
        
        assert result.status == CommandStatus.TIMEOUT
        assert "timed out" in result.error_message.lower()
    
    async def test_execute_denied_command(self):
        """Test that dangerous commands are denied."""
        manager = TerminalManager()
        result = await manager.execute_command("rm -rf /", timeout=5)
        
        assert result.status == CommandStatus.DENIED
        assert result.error_message is not None
    
    async def test_command_with_error(self):
        """Test command that returns error."""
        manager = TerminalManager()
        result = await manager.execute_command("ls /nonexistent", timeout=5)
        
        assert result.status == CommandStatus.ERROR
        assert result.exit_code != 0
        assert result.stderr != ""
    
    async def test_output_truncation(self):
        """Test that large outputs are truncated."""
        manager = TerminalManager(max_output_size=100)
        # Generate large output
        result = await manager.execute_command("for i in {1..1000}; do echo Line $i; done", timeout=5)
        
        assert result.status == CommandStatus.SUCCESS
        assert len(result.stdout) <= manager.max_output_size + 50  # Allow for truncation message
        assert "[Output truncated]" in result.stdout or len(result.stdout) <= 100
    
    async def test_working_directory(self):
        """Test command execution in specific working directory."""
        manager = TerminalManager()
        result = await manager.execute_command("pwd", working_dir="/tmp", timeout=5)
        
        assert result.status == CommandStatus.SUCCESS
        assert result.stdout.strip() == "/tmp"
    
    async def test_environment_variables(self):
        """Test command with custom environment variables."""
        manager = TerminalManager()
        env_vars = {"TEST_VAR": "test_value"}
        result = await manager.execute_command("echo $TEST_VAR", env_vars=env_vars, timeout=5)
        
        assert result.status == CommandStatus.SUCCESS
        assert result.stdout.strip() == "test_value"
    
    async def test_command_history(self):
        """Test command history tracking."""
        manager = TerminalManager()
        
        # Execute multiple commands
        await manager.execute_command("echo 'First'", timeout=5)
        await manager.execute_command("echo 'Second'", timeout=5)
        await manager.execute_command("echo 'Third'", timeout=5)
        
        history = manager.get_command_history()
        assert len(history) >= 3
        
        # Test history limit
        limited_history = manager.get_command_history(limit=2)
        assert len(limited_history) == 2
        
        # Clear history
        manager.clear_command_history()
        history = manager.get_command_history()
        assert len(history) == 0
    
    async def test_file_operations(self):
        """Test file read and write operations."""
        manager = TerminalManager()
        test_file = "/tmp/test_file.txt"
        test_content = "Test content\nLine 2"
        
        # Write file
        success, error = await manager.write_file(test_file, test_content)
        assert success
        assert error is None
        
        # Read file
        success, content, error = await manager.read_file(test_file)
        assert success
        assert content == test_content
        assert error is None
        
        # Append to file
        append_content = "\nLine 3"
        success, error = await manager.write_file(test_file, append_content, append=True)
        assert success
        
        success, content, error = await manager.read_file(test_file)
        assert success
        assert "Line 3" in content
        
        # Clean up
        await manager.execute_command(f"rm {test_file}", timeout=5)
    
    async def test_command_syntax_check(self):
        """Test command syntax validation."""
        manager = TerminalManager()
        
        # Valid syntax
        is_valid, error = await manager.check_command_syntax("echo 'test'")
        assert is_valid
        assert error is None
        
        # Invalid syntax (unclosed quote)
        is_valid, error = await manager.check_command_syntax("echo 'test")
        assert not is_valid
        assert "syntax" in error.lower()
        
        # Dangerous command
        is_valid, error = await manager.check_command_syntax("rm -rf /")
        assert not is_valid
        assert error is not None


@pytest.mark.asyncio
class TestTerminalAgent:
    """Test terminal agent AI functionality."""
    
    @patch('app.services.agents.terminal_agent.AsyncOpenAI')
    async def test_parse_natural_language(self, mock_openai):
        """Test natural language parsing."""
        # Mock OpenAI response
        mock_client = MagicMock()
        mock_openai.return_value = mock_client
        
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = '''
        {
            "command": "ls -la",
            "description": "List all files with details",
            "confidence": 0.95,
            "parameters": {},
            "safety_notes": []
        }
        '''
        mock_client.chat.completions.create = asyncio.coroutine(lambda **kwargs: mock_response)
        
        agent = TerminalAgent()
        intent = await agent.parse_natural_language("show me all files")
        
        assert isinstance(intent, CommandIntent)
        assert intent.command == "ls -la"
        assert intent.confidence == 0.95
    
    def test_quick_pattern_match(self):
        """Test quick pattern matching for common commands."""
        agent = TerminalAgent()
        
        test_cases = [
            ("show files", "ls -la"),
            ("list directory", "ls -la"),
            ("show recent logs", "tail -n 50"),
            ("cpu usage", "echo 'CPU:' && top -bn1"),
            ("list processes", "ps aux"),
            ("git status", "git status"),
        ]
        
        for user_input, expected_command in test_cases:
            result = agent._quick_pattern_match(user_input)
            assert result is not None, f"Should match pattern for: {user_input}"
            assert expected_command in result.command
    
    @patch('app.services.agents.terminal_agent.TerminalManager')
    async def test_execute_intent(self, mock_terminal_manager):
        """Test intent execution."""
        mock_manager = MagicMock()
        mock_result = CommandResult(
            command="ls -la",
            status=CommandStatus.SUCCESS,
            stdout="file1.txt\nfile2.txt",
            exit_code=0,
            duration_ms=10
        )
        mock_manager.execute_command = asyncio.coroutine(lambda **kwargs: mock_result)
        
        agent = TerminalAgent(terminal_manager=mock_manager)
        intent = CommandIntent(
            command="ls -la",
            description="List files",
            confidence=0.9
        )
        
        result = await agent.execute_intent(intent, timeout=30)
        
        assert result.status == CommandStatus.SUCCESS
        assert result.command == "ls -la"
    
    async def test_low_confidence_rejection(self):
        """Test that low confidence commands are rejected."""
        agent = TerminalAgent()
        intent = CommandIntent(
            command="rm -rf /",
            description="Delete everything",
            confidence=0.3  # Low confidence
        )
        
        result = await agent.execute_intent(intent)
        
        assert result.status == CommandStatus.ERROR
        assert "Low confidence" in result.error_message
    
    def test_risky_command_detection(self):
        """Test detection of risky commands."""
        agent = TerminalAgent()
        
        risky_commands = [
            "rm file.txt",
            "chmod 777 file",
            "kill -9 1234",
            "shutdown now",
            "echo test > file.txt",
        ]
        
        for cmd in risky_commands:
            is_risky = agent._is_risky_command(cmd)
            assert is_risky, f"Should detect as risky: {cmd}"
        
        safe_commands = [
            "ls -la",
            "cat file.txt",
            "grep pattern file",
            "ps aux",
        ]
        
        for cmd in safe_commands:
            is_risky = agent._is_risky_command(cmd)
            assert not is_risky, f"Should not detect as risky: {cmd}"
    
    @patch('app.services.agents.terminal_agent.AsyncOpenAI')
    async def test_interpret_output(self, mock_openai):
        """Test output interpretation."""
        # Mock OpenAI client
        mock_client = MagicMock()
        mock_openai.return_value = mock_client
        
        agent = TerminalAgent()
        
        # Test successful command
        result = CommandResult(
            command="ls -la",
            status=CommandStatus.SUCCESS,
            stdout="file1.txt\nfile2.txt",
            exit_code=0,
            duration_ms=10
        )
        
        interpretation = await agent.interpret_output(result)
        assert "✅" in interpretation
        assert "successfully" in interpretation.lower()
        
        # Test error command
        result = CommandResult(
            command="ls /nonexistent",
            status=CommandStatus.ERROR,
            stderr="No such file or directory",
            exit_code=1,
            duration_ms=10
        )
        
        interpretation = await agent.interpret_output(result)
        assert "❌" in interpretation
        assert "failed" in interpretation.lower()
        
        # Test timeout
        result = CommandResult(
            command="sleep 100",
            status=CommandStatus.TIMEOUT,
            error_message="Command timed out after 5 seconds",
            duration_ms=5000
        )
        
        interpretation = await agent.interpret_output(result)
        assert "⏱️" in interpretation
        assert "timed out" in interpretation.lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])