"""Shell capture strategy for CLI projects."""

from __future__ import annotations

import asyncio
import logging
import shlex
import time
from typing import Any

from .base import CaptureConfig, CaptureStrategy, EvidenceResult, EvidenceType, ExplorerEntry

logger = logging.getLogger(__name__)

# Default timeout for shell commands (60 seconds)
DEFAULT_TIMEOUT_SECONDS = 60

# Maximum output size to store (1MB)
MAX_OUTPUT_SIZE = 1024 * 1024


class ShellCapture(CaptureStrategy):
    """Capture strategy for shell command execution.

    Used for CLI projects to verify command output and exit codes.
    Captures stdout, stderr, and execution metrics.
    """

    @property
    def name(self) -> str:
        return "Shell Capture"

    def supports_entry_type(self, entry_type: str) -> bool:
        return entry_type == "file"

    def get_evidence_types(self) -> list[EvidenceType]:
        return ["task_execution"]

    async def capture(
        self,
        entry: ExplorerEntry,
        config: CaptureConfig,
    ) -> list[EvidenceResult]:
        """Capture shell command execution for an entry.

        The command to execute is determined from the entry metadata:
        - metadata.command: Explicit command to run
        - metadata.test_command: If this is a test file
        - path: If the path is an executable script
        """
        command = self._determine_command(entry)

        if not command:
            return [
                EvidenceResult.failure(
                    "task_execution",
                    "No command specified in entry metadata. "
                    "Set 'command' or 'test_command' in entry metadata.",
                )
            ]

        result = await self._execute_command(command, entry, config)
        return [result]

    def _determine_command(self, entry: ExplorerEntry) -> str | None:
        """Determine the command to execute from entry metadata."""
        metadata = entry.get("metadata", {})

        # Explicit command has highest priority
        if command := metadata.get("command"):
            return str(command)

        # Test command for test files
        if command := metadata.get("test_command"):
            return str(command)

        # If the path looks like a script, try to execute it
        path = entry.get("path", "")
        if path.endswith((".sh", ".bash", ".py", ".js", ".ts")):
            # Return None - we don't want to auto-execute arbitrary files
            # This requires explicit command configuration
            return None

        return None

    async def _execute_command(
        self,
        command: str,
        entry: ExplorerEntry,
        config: CaptureConfig,
    ) -> EvidenceResult:
        """Execute command and capture output."""
        timeout_sec = config.get("timeout_ms", DEFAULT_TIMEOUT_SECONDS * 1000) / 1000
        metadata = entry.get("metadata", {})
        working_dir = metadata.get("working_dir")
        env_vars: dict[str, str] = metadata.get("env", {})

        start_time = time.perf_counter()

        try:
            # Parse command for safe execution
            # Use shell=True for complex commands with pipes, redirects, etc.
            use_shell = any(c in command for c in ["|", ">", "<", "&&", "||", ";"])

            if use_shell:
                process = await asyncio.create_subprocess_shell(
                    command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=working_dir,
                    env=env_vars if env_vars else None,
                )
            else:
                args = shlex.split(command)
                process = await asyncio.create_subprocess_exec(
                    *args,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=working_dir,
                    env=env_vars if env_vars else None,
                )

            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    process.communicate(),
                    timeout=timeout_sec,
                )
            except TimeoutError:
                process.kill()
                await process.wait()
                return EvidenceResult.failure(
                    "task_execution",
                    f"Command timed out after {timeout_sec}s",
                )

            duration_ms = int((time.perf_counter() - start_time) * 1000)

            # Decode output
            stdout = self._decode_and_truncate(stdout_bytes)
            stderr = self._decode_and_truncate(stderr_bytes)
            exit_code = process.returncode or 0

            # Determine success based on exit code
            success = exit_code == 0

            return EvidenceResult(
                success=success,
                evidence_type="task_execution",
                metadata=self._build_metadata(
                    command=command,
                    exit_code=exit_code,
                    stdout=stdout,
                    stderr=stderr,
                    duration_ms=duration_ms,
                    working_dir=working_dir,
                    truncated={
                        "stdout": len(stdout_bytes) > MAX_OUTPUT_SIZE,
                        "stderr": len(stderr_bytes) > MAX_OUTPUT_SIZE,
                    },
                ),
                duration_ms=duration_ms,
                errors=[stderr] if stderr and not success else [],
            )

        except FileNotFoundError as e:
            return EvidenceResult.failure(
                "task_execution",
                f"Command not found: {e}",
            )
        except PermissionError as e:
            return EvidenceResult.failure(
                "task_execution",
                f"Permission denied: {e}",
            )
        except Exception as e:
            logger.exception(f"Error executing command: {command}")
            return EvidenceResult.failure("task_execution", str(e))

    def _decode_and_truncate(self, data: bytes) -> str:
        """Decode bytes to string and truncate if too large."""
        if len(data) > MAX_OUTPUT_SIZE:
            data = data[:MAX_OUTPUT_SIZE]
            text = data.decode("utf-8", errors="replace")
            return text + "\n... [truncated]"
        return data.decode("utf-8", errors="replace")

    def _build_metadata(
        self,
        command: str,
        exit_code: int,
        stdout: str,
        stderr: str,
        duration_ms: int,
        working_dir: str | None,
        truncated: dict[str, bool],
    ) -> dict[str, Any]:
        """Build metadata dict for the evidence result."""
        return {
            "command": command,
            "exit_code": exit_code,
            "stdout": stdout,
            "stderr": stderr,
            "duration_ms": duration_ms,
            "working_dir": working_dir,
            "truncated": truncated,
            "success": exit_code == 0,
        }


async def capture_shell_command(
    command: str,
    *,
    working_dir: str | None = None,
    env: dict[str, str] | None = None,
    timeout_sec: float = DEFAULT_TIMEOUT_SECONDS,
) -> EvidenceResult:
    """Convenience function to capture a single shell command.

    Args:
        command: Command to execute
        working_dir: Working directory for command
        env: Environment variables
        timeout_sec: Timeout in seconds

    Returns:
        EvidenceResult with command output
    """
    entry: ExplorerEntry = {
        "id": 0,
        "project_id": "",
        "entry_type": "file",
        "path": "",
        "name": "shell_command",
        "metadata": {
            "command": command,
            "working_dir": working_dir,
            "env": env or {},
        },
    }
    config: CaptureConfig = {"timeout_ms": int(timeout_sec * 1000)}

    strategy = ShellCapture()
    results = await strategy.capture(entry, config)
    return (
        results[0]
        if results
        else EvidenceResult.failure(
            "task_execution",
            "No results from capture",
        )
    )
