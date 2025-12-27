"""Test runner service - Execute tests by type with token-optimized output.

This module provides async test execution for various test types:
- pytest: Python unit/integration tests
- mypy: Python type checking
- ruff: Python linting
- vitest: JavaScript/TypeScript unit tests
- api: HTTP API tests (curl-based)
- ui: Browser automation tests (using browser-automation skill)

Results are stored in the test_runs table and test metadata is updated.

Note: Playwright support has been replaced by browser-automation skill.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

from ..storage import test_runs as test_runs_storage
from ..storage import tests as tests_storage
from ..storage.connection import get_connection

# Import from submodules
from .test_runner_lib.base import (
    MAX_OUTPUT_LENGTH,
    TEST_TOOL_SPECS,
    TIER_TEST_TYPES,
    ProjectConfig,
    TestResult,
)
from .test_runner_lib.ui_tests import (
    build_browser_script_command,
    check_ui_assertions,
    extract_evidence_path,
    get_available_browser_scripts,
    parse_browser_script_output,
    resolve_browser_script,
)

logger = logging.getLogger(__name__)


def _combine_outputs(stdout: str, stderr: str) -> str:
    """Combine stdout and stderr into a single output string."""
    return stdout + ("\n" + stderr if stderr else "")


def _get_tool_path(tool_name: str, config: ProjectConfig) -> str:
    """Get the executable path for a test tool."""
    if tool_name == "pytest":
        return config.pytest_path
    elif tool_name == "mypy":
        return config.pytest_path.replace("pytest", "mypy")
    elif tool_name == "vitest":
        return config.node_path
    else:
        return tool_name


def _truncate_output(output: str) -> str:
    """Truncate output to MAX_OUTPUT_LENGTH for token efficiency."""
    if len(output) <= MAX_OUTPUT_LENGTH:
        return output

    half = (MAX_OUTPUT_LENGTH - 50) // 2
    return f"{output[:half]}\n\n... [truncated {len(output) - MAX_OUTPUT_LENGTH} chars] ...\n\n{output[-half:]}"


async def _run_command(
    command: str,
    working_dir: str,
    timeout: int = 60,
    env: dict[str, str] | None = None,
) -> tuple[int, str, str]:
    """Run a shell command asynchronously.

    Args:
        command: Shell command to execute
        working_dir: Working directory
        timeout: Timeout in seconds
        env: Additional environment variables

    Returns:
        Tuple of (exit_code, stdout, stderr)
    """
    full_env = os.environ.copy()
    if env:
        full_env.update(env)

    proc = None
    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=working_dir,
            env=full_env,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(),
            timeout=timeout,
        )
        return (
            proc.returncode or 0,
            stdout.decode("utf-8", errors="replace"),
            stderr.decode("utf-8", errors="replace"),
        )
    except TimeoutError:
        if proc:
            proc.kill()
            await proc.wait()
        return -1, "", f"Command timed out after {timeout}s"
    except Exception as e:
        return -1, "", str(e)


async def _execute_test_command(
    command: str,
    working_dir: str,
    timeout: int,
) -> tuple[int, str, str]:
    """Execute a test command with timeout handling."""
    return await _run_command(
        command=command,
        working_dir=working_dir,
        timeout=timeout,
    )


def _build_test_result(
    passed: bool,
    stdout: str,
    stderr: str,
    evidence_path: str | None = None,
) -> TestResult:
    """Build a TestResult from command execution output."""
    output = _combine_outputs(stdout, stderr)
    return TestResult(
        passed=passed,
        duration_ms=0,
        output=_truncate_output(output),
        error=stderr if not passed and stderr else None,
        evidence_path=evidence_path,
    )


async def _run_generic_test(
    tool_name: str,
    test: dict[str, Any],
    config: ProjectConfig,
) -> TestResult:
    """Run a generic test using TestToolSpec configuration."""
    spec = TEST_TOOL_SPECS.get(tool_name)
    if not spec:
        return TestResult(
            passed=False,
            duration_ms=0,
            output="",
            error=f"Unknown test tool: {tool_name}",
        )

    root_dir = getattr(config, spec.root_attr)
    working_dir = os.path.join(config.root_path, root_dir)

    test_path = test.get("command") or test.get("name") or spec.default_path

    tool_path = _get_tool_path(tool_name, config)
    command = spec.command_template.format(tool_path=tool_path, test_path=test_path)

    timeout = test.get("timeout_seconds", spec.default_timeout)

    exit_code, stdout, stderr = await _run_command(
        command=command,
        working_dir=working_dir,
        timeout=timeout,
    )

    output = _combine_outputs(stdout, stderr)
    passed = exit_code == 0

    error = (stderr if spec.use_stderr_as_error and stderr else output) if not passed else None

    return TestResult(
        passed=passed,
        duration_ms=0,
        output=_truncate_output(output),
        error=error,
    )


def get_project_config(project_id: str) -> ProjectConfig | None:
    """Get project configuration for test execution."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT root_path, test_config
            FROM projects
            WHERE id = %s
            """,
            (project_id,),
        )
        row = cur.fetchone()

    if not row:
        return None

    return ProjectConfig.from_db_row(project_id, row)


async def run_test(
    project_id: str,
    test_id: str,
    triggered_by: str = "manual",
    session_id: str | None = None,
) -> TestResult:
    """Run a single test by ID.

    Args:
        project_id: Project ID
        test_id: Test ID (not database ID)
        triggered_by: Who/what triggered the run
        session_id: Agent session ID if part of a build

    Returns:
        TestResult with execution details.

    Raises:
        ValueError: If test or project not found.
    """
    test = tests_storage.get_test(project_id, test_id)
    if not test:
        raise ValueError(f"Test not found: {test_id}")

    config = get_project_config(project_id)
    if not config:
        raise ValueError(f"Project not found: {project_id}")

    test_type = test["test_type"]
    start_time = time.time()

    runner_map = {
        "pytest": run_pytest,
        "mypy": run_mypy,
        "ruff": run_ruff,
        "vitest": run_vitest,
        "api": run_api_test,
        "ui": run_ui_test,
    }

    runner = runner_map.get(test_type)
    if not runner:
        return TestResult(
            passed=False,
            duration_ms=0,
            output="",
            error=f"Unknown test type: {test_type}",
        )

    result = await runner(test, config)
    duration_ms = int((time.time() - start_time) * 1000)
    result.duration_ms = duration_ms

    result_status = "passed" if result.passed else "failed"
    if result.error and "timed out" in result.error.lower():
        result_status = "timeout"

    test_run = test_runs_storage.create_test_run(
        project_id=project_id,
        test_db_id=test["id"],
        run_type=triggered_by,
        result=result_status,
        duration_ms=duration_ms,
        output=_truncate_output(result.output),
        error=result.error,
        evidence_path=result.evidence_path,
        triggered_by=triggered_by,
        session_id=session_id,
    )

    if test_type == "ui" and result.evidence_path and test_run:
        from . import evidence_manager

        evidence_manager.register_test_evidence(
            project_id=project_id,
            test_id=test_id,
            test_run_id=test_run["id"],
            evidence_path=result.evidence_path,
        )

    tests_storage.update_test_result(
        project_id=project_id,
        test_id=test_id,
        result=result_status,
        duration_ms=duration_ms,
        output=_truncate_output(result.output),
        error=result.error,
    )

    return result


async def run_tests(
    project_id: str,
    test_ids: list[str] | None = None,
    tier: str | None = None,
    triggered_by: str = "manual",
    session_id: str | None = None,
) -> list[dict[str, Any]]:
    """Run multiple tests.

    Args:
        project_id: Project ID
        test_ids: List of test IDs to run (if None, uses tier filter)
        tier: Test tier to run ('smoke', 'unit', 'integration', 'all')
        triggered_by: Who/what triggered the run
        session_id: Agent session ID if part of a build

    Returns:
        List of {test_id, result, duration_ms, output, error} dicts.
    """
    if test_ids:
        tests = [tests_storage.get_test(project_id, tid) for tid in test_ids]
        tests = [t for t in tests if t is not None]
    else:
        all_tests = tests_storage.list_tests(project_id)
        if tier and tier in TIER_TEST_TYPES:
            allowed_types = TIER_TEST_TYPES[tier]
            tests = [t for t in all_tests if t["test_type"] in allowed_types]
        else:
            tests = all_tests

    results = []
    for test in tests:
        try:
            result = await run_test(
                project_id=project_id,
                test_id=test["test_id"],
                triggered_by=triggered_by,
                session_id=session_id,
            )
            results.append(
                {
                    "test_id": test["test_id"],
                    "result": "passed" if result.passed else "failed",
                    "duration_ms": result.duration_ms,
                    "output": result.output,
                    "error": result.error,
                }
            )
        except Exception as e:
            results.append(
                {
                    "test_id": test["test_id"],
                    "result": "error",
                    "duration_ms": 0,
                    "output": "",
                    "error": str(e),
                }
            )

    return results


# ============================================================
# Type-Specific Runners
# ============================================================


async def run_pytest(test: dict[str, Any], config: ProjectConfig) -> TestResult:
    """Run a pytest test."""
    return await _run_generic_test("pytest", test, config)


async def run_mypy(test: dict[str, Any], config: ProjectConfig) -> TestResult:
    """Run mypy type checking."""
    return await _run_generic_test("mypy", test, config)


async def run_ruff(test: dict[str, Any], config: ProjectConfig) -> TestResult:
    """Run ruff linting."""
    return await _run_generic_test("ruff", test, config)


async def run_vitest(test: dict[str, Any], config: ProjectConfig) -> TestResult:
    """Run vitest JavaScript/TypeScript tests."""
    return await _run_generic_test("vitest", test, config)


async def run_api_test(test: dict[str, Any], config: ProjectConfig) -> TestResult:
    """Run HTTP API test."""
    command = test.get("command")
    test_config = test.get("config", {})

    if not command and test_config:
        url = test_config.get("url", "")
        method = test_config.get("method", "GET")
        headers = test_config.get("headers", {})
        body = test_config.get("body")

        cmd_parts = [
            "curl",
            "-s",
            "-o",
            "/tmp/api_response.json",
            "-w",
            "'%{http_code}'",
            "-X",
            method,
        ]
        for k, v in headers.items():
            cmd_parts.extend(["-H", f"'{k}: {v}'"])
        if body:
            cmd_parts.extend(["-d", f"'{json.dumps(body)}'"])
        cmd_parts.append(f"'{url}'")
        command = " ".join(cmd_parts)

    if not command:
        return TestResult(
            passed=False,
            duration_ms=0,
            output="",
            error="No command or config provided for API test",
        )

    timeout = test.get("timeout_seconds", 30)
    exit_code, stdout, stderr = await _execute_test_command(command, config.root_path, timeout)

    passed = exit_code == 0

    assertions = test_config.get("assertions", [])
    if passed and assertions:
        for assertion in assertions:
            jq_filter = assertion.get("jq")
            expected = assertion.get("expected")
            if jq_filter:
                jq_cmd = f"jq '{jq_filter}' /tmp/api_response.json"
                _jq_exit, jq_out, _ = await _run_command(jq_cmd, config.root_path, timeout=10)
                actual = jq_out.strip()
                if str(actual) != str(expected):
                    passed = False
                    stdout += f"\nAssertion failed: {jq_filter} = {actual}, expected {expected}"
                    break

    return _build_test_result(passed, stdout, stderr)


async def run_ui_test(test: dict[str, Any], config: ProjectConfig) -> TestResult:
    """Run browser automation UI test."""
    test_config = test.get("config", {})
    script_name = test_config.get("script_name")

    # Priority 1: Use browser-automation script by name
    if script_name:
        script_path = resolve_browser_script(script_name, config)
        if not script_path:
            return TestResult(
                passed=False,
                duration_ms=0,
                output="",
                error=f"Browser script not found: {script_name}. Available: {', '.join(get_available_browser_scripts(config))}",
            )

        url = test_config.get("url", "")
        args = test_config.get("args", {})
        output_path = test_config.get("output_path")

        command = build_browser_script_command(
            script_path=script_path,
            script_name=script_name,
            url=url,
            args=args,
            output_path=output_path,
        )

        timeout = test.get("timeout_seconds", 120)
        exit_code, stdout, stderr = await _execute_test_command(command, config.root_path, timeout)

        result = parse_browser_script_output(stdout, stderr, exit_code)

        assertions = test_config.get("assertions", [])
        if result.passed and assertions:
            assertion_result = await check_ui_assertions(assertions, stdout, config)
            if not assertion_result[0]:
                result = TestResult(
                    passed=False,
                    duration_ms=result.duration_ms,
                    output=result.output + f"\n\nAssertion failed: {assertion_result[1]}",
                    error=assertion_result[1],
                    evidence_path=result.evidence_path,
                )

        return result

    # Priority 2: Inline script content
    script = test.get("script")
    if script:
        import tempfile

        with tempfile.NamedTemporaryFile(mode="w", suffix=".js", delete=False) as f:
            f.write(script)
            temp_script_path = f.name

        try:
            command = f"node {temp_script_path}"
            timeout = test.get("timeout_seconds", 120)
            exit_code, stdout, stderr = await _execute_test_command(
                command, config.root_path, timeout
            )
            passed = exit_code == 0
            evidence_path = extract_evidence_path(stdout)
            return _build_test_result(passed, stdout, stderr, evidence_path)
        finally:
            Path(temp_script_path).unlink(missing_ok=True)

    # Priority 3: Raw command
    command = test.get("command")
    if command:
        timeout = test.get("timeout_seconds", 120)
        exit_code, stdout, stderr = await _execute_test_command(command, config.root_path, timeout)
        passed = exit_code == 0
        return _build_test_result(passed, stdout, stderr)

    return TestResult(
        passed=False,
        duration_ms=0,
        output="",
        error="UI test requires script_name (in config), script (inline), or command",
    )
