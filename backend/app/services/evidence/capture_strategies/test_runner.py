"""Test runner capture strategy for test file entries."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from pathlib import Path
from typing import Any

from .base import CaptureConfig, CaptureStrategy, EvidenceResult, EvidenceType, ExplorerEntry

logger = logging.getLogger(__name__)

# Default timeout for test runs (5 minutes)
DEFAULT_TIMEOUT_SECONDS = 300

# Maximum output size to store (2MB for test output)
MAX_OUTPUT_SIZE = 2 * 1024 * 1024


class TestRunnerCapture(CaptureStrategy):
    """Capture strategy for running tests and collecting results.

    Supports pytest (Python) and vitest/jest (JavaScript/TypeScript).
    Captures test results, duration, and optional coverage data.
    """

    @property
    def name(self) -> str:
        return "Test Runner Capture"

    def supports_entry_type(self, entry_type: str) -> bool:
        return entry_type == "file"

    def get_evidence_types(self) -> list[EvidenceType]:
        return ["test_result"]

    async def capture(
        self,
        entry: ExplorerEntry,
        config: CaptureConfig,
    ) -> list[EvidenceResult]:
        """Run tests for a test file entry.

        The test runner is determined from:
        - metadata.test_runner: Explicit runner (pytest, vitest, jest)
        - path extension: .py -> pytest, .ts/.tsx/.js/.jsx -> vitest/jest
        """
        runner = self._determine_runner(entry)

        if not runner:
            return [
                EvidenceResult.failure(
                    "test_result",
                    "Could not determine test runner. "
                    "Set 'test_runner' in entry metadata or use a recognized test file extension.",
                )
            ]

        if runner == "pytest":
            result = await self._run_pytest(entry, config)
        elif runner in ("vitest", "jest"):
            result = await self._run_js_tests(entry, config, runner)
        else:
            return [
                EvidenceResult.failure(
                    "test_result",
                    f"Unsupported test runner: {runner}",
                )
            ]

        return [result]

    def _determine_runner(self, entry: ExplorerEntry) -> str | None:
        """Determine the test runner to use."""
        metadata = entry.get("metadata", {})

        # Explicit runner has highest priority
        if runner := metadata.get("test_runner"):
            return str(runner)

        # Infer from file extension
        path = entry.get("path", "")
        if path.endswith(".py") or path.endswith("_test.py") or "test_" in path:
            return "pytest"
        if path.endswith((".ts", ".tsx", ".js", ".jsx")) and (
            "test" in path.lower() or "spec" in path.lower()
        ):
            return "vitest"  # Default to vitest for modern projects

        return None

    async def _run_pytest(
        self,
        entry: ExplorerEntry,
        config: CaptureConfig,
    ) -> EvidenceResult:
        """Run pytest on the test file."""
        path = entry.get("path", "")
        metadata = entry.get("metadata", {})
        working_dir = metadata.get("working_dir", ".")
        timeout_sec = config.get("timeout_ms", DEFAULT_TIMEOUT_SECONDS * 1000) / 1000

        # Build pytest command with JSON output
        cmd = [
            "python",
            "-m",
            "pytest",
            path,
            "-v",
            "--tb=short",
            "-q",
            "--json-report",
            "--json-report-file=/dev/stdout",
        ]

        # Add coverage if requested
        if metadata.get("collect_coverage"):
            cmd.extend(["--cov", "--cov-report=json"])

        start_time = time.perf_counter()

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=working_dir,
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
                    "test_result",
                    f"Test run timed out after {timeout_sec}s",
                )

            duration_ms = int((time.perf_counter() - start_time) * 1000)

            stdout = stdout_bytes.decode("utf-8", errors="replace")
            stderr = stderr_bytes.decode("utf-8", errors="replace")
            exit_code = process.returncode or 0

            # Parse pytest results
            test_results = self._parse_pytest_output(stdout, stderr, exit_code)

            return EvidenceResult(
                success=exit_code == 0,
                evidence_type="test_result",
                metadata={
                    "runner": "pytest",
                    "path": path,
                    "exit_code": exit_code,
                    "duration_ms": duration_ms,
                    **test_results,
                    "stdout": stdout[:MAX_OUTPUT_SIZE] if len(stdout) > MAX_OUTPUT_SIZE else stdout,
                    "stderr": stderr[:MAX_OUTPUT_SIZE] if len(stderr) > MAX_OUTPUT_SIZE else stderr,
                },
                duration_ms=duration_ms,
                errors=[stderr] if stderr and exit_code != 0 else [],
            )

        except FileNotFoundError:
            return EvidenceResult.failure(
                "test_result",
                "pytest not found. Install with: pip install pytest pytest-json-report",
            )
        except Exception as e:
            logger.exception(f"Error running pytest: {path}")
            return EvidenceResult.failure("test_result", str(e))

    def _parse_pytest_output(
        self,
        stdout: str,
        stderr: str,
        exit_code: int,
    ) -> dict[str, Any]:
        """Parse pytest output to extract test results."""
        results: dict[str, Any] = {
            "passed": 0,
            "failed": 0,
            "skipped": 0,
            "errors": 0,
            "total": 0,
            "tests": [],
        }

        # Try to parse JSON report if available
        try:
            # Look for JSON report in stdout
            json_match = re.search(r"\{.*\"report\".*\}", stdout, re.DOTALL)
            if json_match:
                report = json.loads(json_match.group())
                if "summary" in report:
                    summary = report["summary"]
                    results["passed"] = summary.get("passed", 0)
                    results["failed"] = summary.get("failed", 0)
                    results["skipped"] = summary.get("skipped", 0)
                    results["errors"] = summary.get("error", 0)
                    results["total"] = summary.get("total", 0)
                if "tests" in report:
                    results["tests"] = [
                        {
                            "name": t.get("nodeid", ""),
                            "outcome": t.get("outcome", ""),
                            "duration": t.get("duration", 0),
                        }
                        for t in report.get("tests", [])
                    ]
                return results
        except (json.JSONDecodeError, KeyError):
            pass

        # Fall back to parsing text output
        # Match patterns like "5 passed, 2 failed, 1 skipped"
        summary_pattern = r"(\d+)\s+(passed|failed|skipped|error)"
        for match in re.finditer(summary_pattern, stdout + stderr, re.IGNORECASE):
            count = int(match.group(1))
            status = match.group(2).lower()
            if status == "error":
                results["errors"] = count
            elif status in results:
                results[status] = count

        results["total"] = (
            results["passed"] + results["failed"] + results["skipped"] + results["errors"]
        )

        return results

    async def _run_js_tests(
        self,
        entry: ExplorerEntry,
        config: CaptureConfig,
        runner: str,
    ) -> EvidenceResult:
        """Run JavaScript/TypeScript tests with vitest or jest."""
        path = entry.get("path", "")
        metadata = entry.get("metadata", {})
        working_dir = metadata.get("working_dir", ".")
        timeout_sec = config.get("timeout_ms", DEFAULT_TIMEOUT_SECONDS * 1000) / 1000

        # Build test command
        if runner == "vitest":
            cmd = ["npx", "vitest", "run", path, "--reporter=json"]
        else:  # jest
            cmd = ["npx", "jest", path, "--json", "--outputFile=/dev/stdout"]

        start_time = time.perf_counter()

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=working_dir,
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
                    "test_result",
                    f"Test run timed out after {timeout_sec}s",
                )

            duration_ms = int((time.perf_counter() - start_time) * 1000)

            stdout = stdout_bytes.decode("utf-8", errors="replace")
            stderr = stderr_bytes.decode("utf-8", errors="replace")
            exit_code = process.returncode or 0

            # Parse test results
            test_results = self._parse_js_test_output(stdout, runner)

            return EvidenceResult(
                success=exit_code == 0,
                evidence_type="test_result",
                metadata={
                    "runner": runner,
                    "path": path,
                    "exit_code": exit_code,
                    "duration_ms": duration_ms,
                    **test_results,
                    "stdout": stdout[:MAX_OUTPUT_SIZE] if len(stdout) > MAX_OUTPUT_SIZE else stdout,
                    "stderr": stderr[:MAX_OUTPUT_SIZE] if len(stderr) > MAX_OUTPUT_SIZE else stderr,
                },
                duration_ms=duration_ms,
                errors=[stderr] if stderr and exit_code != 0 else [],
            )

        except FileNotFoundError:
            return EvidenceResult.failure(
                "test_result",
                f"{runner} not found. Install with: npm install {runner}",
            )
        except Exception as e:
            logger.exception(f"Error running {runner}: {path}")
            return EvidenceResult.failure("test_result", str(e))

    def _parse_js_test_output(self, stdout: str, runner: str) -> dict[str, Any]:
        """Parse JavaScript test runner output."""
        results: dict[str, Any] = {
            "passed": 0,
            "failed": 0,
            "skipped": 0,
            "total": 0,
            "tests": [],
        }

        try:
            # Try to parse JSON output
            json_match = re.search(r"\{.*\}", stdout, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())

                # Both vitest and jest use the same JSON format
                if runner in ("vitest", "jest") and "numPassedTests" in data:
                    results["passed"] = data.get("numPassedTests", 0)
                    results["failed"] = data.get("numFailedTests", 0)
                    results["skipped"] = data.get("numPendingTests", 0)
                    results["total"] = data.get("numTotalTests", 0)

                return results
        except (json.JSONDecodeError, KeyError):
            pass

        # Fall back to counting from output
        results["total"] = results["passed"] + results["failed"] + results["skipped"]
        return results


async def run_tests(
    path: str,
    *,
    runner: str = "pytest",
    working_dir: str = ".",
    timeout_sec: float = DEFAULT_TIMEOUT_SECONDS,
    collect_coverage: bool = False,
) -> EvidenceResult:
    """Convenience function to run tests on a file.

    Args:
        path: Path to test file or directory
        runner: Test runner to use (pytest, vitest, jest)
        working_dir: Working directory
        timeout_sec: Timeout in seconds
        collect_coverage: Whether to collect coverage data

    Returns:
        EvidenceResult with test results
    """
    entry: ExplorerEntry = {
        "id": 0,
        "project_id": "",
        "entry_type": "file",
        "path": path,
        "name": Path(path).name,
        "metadata": {
            "test_runner": runner,
            "working_dir": working_dir,
            "collect_coverage": collect_coverage,
        },
    }
    config: CaptureConfig = {"timeout_ms": int(timeout_sec * 1000)}

    strategy = TestRunnerCapture()
    results = await strategy.capture(entry, config)
    return (
        results[0]
        if results
        else EvidenceResult.failure(
            "test_result",
            "No results from capture",
        )
    )
