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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..storage import test_runs as test_runs_storage
from ..storage import tests as tests_storage
from ..storage.connection import get_connection

logger = logging.getLogger(__name__)

# Maximum output length to store (token efficiency)
MAX_OUTPUT_LENGTH = 1000

# Browser automation scripts path - uses ~/.claude/skills/browser-automation/scripts/ by default
BROWSER_AUTOMATION_SCRIPTS_PATH = os.environ.get(
    "BROWSER_AUTOMATION_SCRIPTS_PATH",
    os.path.expanduser("~/.claude/skills/browser-automation/scripts"),
)

# Available browser-automation scripts
BROWSER_SCRIPTS = {
    "screenshot": "screenshot.js",
    "click-screenshot": "click-screenshot.js",
    "tab-click-screenshot": "tab-click-screenshot.js",
    "interact": "interact.js",
    "regression-check": "regression-check.js",
    "console": "console.js",
    "network": "network.js",
    "capture-evidence": "capture-evidence.js",
    "expand": "expand.js",
}


@dataclass
class TestResult:
    """Result from a test execution."""

    passed: bool
    duration_ms: int
    output: str
    error: str | None = None
    evidence_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for API response."""
        return {
            "passed": self.passed,
            "duration_ms": self.duration_ms,
            "output": self.output,
            "error": self.error,
            "evidence_path": self.evidence_path,
        }


@dataclass
class ProjectConfig:
    """Test configuration for a project."""

    project_id: str
    root_path: str
    backend_root: str = "backend"
    frontend_root: str = "frontend"
    pytest_path: str = ".venv/bin/pytest"
    node_path: str = "npx"
    test_patterns: dict[str, str] = field(default_factory=dict)
    browser_scripts_path: str = field(default_factory=lambda: BROWSER_AUTOMATION_SCRIPTS_PATH)

    @classmethod
    def from_db_row(cls, project_id: str, row: tuple) -> ProjectConfig:
        """Create from database row (root_path, test_config)."""
        root_path = row[0] or "."
        test_config = row[1] or {}

        # Handle JSON string if needed
        if isinstance(test_config, str):
            test_config = json.loads(test_config)

        return cls(
            project_id=project_id,
            root_path=root_path,
            backend_root=test_config.get("backend_root", "backend"),
            frontend_root=test_config.get("frontend_root", "frontend"),
            pytest_path=test_config.get("pytest_path", ".venv/bin/pytest"),
            node_path=test_config.get("node_path", "npx"),
            test_patterns=test_config.get("test_patterns", {}),
            browser_scripts_path=test_config.get(
                "browser_scripts_path", BROWSER_AUTOMATION_SCRIPTS_PATH
            ),
        )


def get_project_config(project_id: str) -> ProjectConfig | None:
    """Get project configuration for test execution.

    Returns:
        ProjectConfig or None if project not found.
    """
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


def _truncate_output(output: str) -> str:
    """Truncate output to MAX_OUTPUT_LENGTH for token efficiency."""
    if len(output) <= MAX_OUTPUT_LENGTH:
        return output

    # Keep first and last parts with indicator
    half = (MAX_OUTPUT_LENGTH - 50) // 2
    return f"{output[:half]}\n\n... [truncated {len(output) - MAX_OUTPUT_LENGTH} chars] ...\n\n{output[-half:]}"


def resolve_browser_script(script_name: str, config: ProjectConfig | None = None) -> Path | None:
    """Resolve a browser-automation script name to its full path.

    Args:
        script_name: Script name (e.g., 'screenshot', 'interact') or filename
        config: Optional project config with custom browser_scripts_path

    Returns:
        Path to the script file if it exists, None otherwise.
    """
    scripts_path = Path(config.browser_scripts_path if config else BROWSER_AUTOMATION_SCRIPTS_PATH)

    # If script_name is already a filename (ends with .js), use it directly
    if script_name.endswith(".js"):
        script_file = scripts_path / script_name
    else:
        # Look up in BROWSER_SCRIPTS map
        filename = BROWSER_SCRIPTS.get(script_name, f"{script_name}.js")
        script_file = scripts_path / filename

    if script_file.exists():
        return script_file

    return None


def get_available_browser_scripts(config: ProjectConfig | None = None) -> list[str]:
    """Get list of available browser-automation scripts.

    Args:
        config: Optional project config with custom browser_scripts_path

    Returns:
        List of available script names.
    """
    scripts_path = Path(config.browser_scripts_path if config else BROWSER_AUTOMATION_SCRIPTS_PATH)

    if not scripts_path.exists():
        return []

    available = []
    for name, filename in BROWSER_SCRIPTS.items():
        if (scripts_path / filename).exists():
            available.append(name)

    return available


# ============================================================
# UI Test Schema for Browser-Automation
# ============================================================


@dataclass
class UITestConfig:
    """Configuration for a browser-automation UI test.

    A UI test can be defined in three ways:
    1. script_name: Use a pre-built browser-automation script
    2. script: Provide inline JavaScript to execute
    3. command: Provide a raw shell command

    Attributes:
        script_name: Name of browser-automation script (screenshot, interact, etc.)
        url: Target URL to test
        args: Arguments to pass to the script
        assertions: List of assertions to check after script execution
        output_path: Path to save screenshots/evidence
        wait_for: CSS selector to wait for before executing
        auth_required: Whether Cloudflare auth is needed
    """

    script_name: str | None = None
    url: str | None = None
    args: dict[str, Any] = field(default_factory=dict)
    assertions: list[dict[str, Any]] = field(default_factory=list)
    output_path: str | None = None
    wait_for: str | None = None
    auth_required: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> UITestConfig:
        """Create from a test config dict."""
        return cls(
            script_name=data.get("script_name"),
            url=data.get("url"),
            args=data.get("args", {}),
            assertions=data.get("assertions", []),
            output_path=data.get("output_path"),
            wait_for=data.get("wait_for"),
            auth_required=data.get("auth_required", False),
        )


def validate_ui_test_config(
    config: dict[str, Any], project_config: ProjectConfig | None = None
) -> tuple[bool, str | None]:
    """Validate UI test configuration.

    Args:
        config: The test config dict to validate
        project_config: Optional project config for script path resolution

    Returns:
        Tuple of (is_valid, error_message)
    """
    # At least one of script_name, script, or command must be provided
    has_script_name = config.get("script_name")
    has_script = config.get("script")
    has_command = config.get("command")

    if not any([has_script_name, has_script, has_command]):
        return False, "UI test requires script_name, script, or command"

    # If script_name provided, validate it exists
    if has_script_name:
        available = get_available_browser_scripts(project_config)
        if has_script_name not in available:
            return (
                False,
                f"Unknown script '{has_script_name}'. Available: {', '.join(available)}",
            )

    # If script_name is used with browser-automation, url is typically required
    if has_script_name and has_script_name != "capture-evidence" and not config.get("url"):
        return False, f"Script '{has_script_name}' requires a 'url' parameter"

    # Validate assertions format if provided
    assertions = config.get("assertions", [])
    for assertion in assertions:
        if not isinstance(assertion, dict):
            return False, "Each assertion must be a dict"
        if "type" not in assertion:
            return False, "Each assertion must have a 'type' field"

    return True, None


# Available browser-automation scripts documentation
UI_TEST_SCRIPTS_DOCS = {
    "screenshot": {
        "description": "Take a full-page screenshot",
        "args": {
            "url": "Target URL (required)",
            "output": "Output path for screenshot",
            "fullPage": "Capture full scrollable page (default: true)",
        },
        "example": {
            "script_name": "screenshot",
            "url": "https://example.com",
            "args": {"fullPage": True},
        },
    },
    "click-screenshot": {
        "description": "Click an element and take a screenshot",
        "args": {
            "url": "Target URL (required)",
            "selector": "CSS selector to click",
            "output": "Output path for screenshot",
        },
        "example": {
            "script_name": "click-screenshot",
            "url": "https://example.com",
            "args": {"selector": "button.submit"},
        },
    },
    "tab-click-screenshot": {
        "description": "Click a tab and take a screenshot",
        "args": {
            "url": "Target URL (required)",
            "selector": "CSS selector for tab",
            "output": "Output path for screenshot",
        },
        "example": {
            "script_name": "tab-click-screenshot",
            "url": "https://example.com/projects/1",
            "args": {"selector": "[data-tab='components']"},
        },
    },
    "interact": {
        "description": "Perform user interactions (click, fill, hover)",
        "args": {
            "url": "Target URL (required)",
            "actions": "List of actions to perform",
        },
        "example": {
            "script_name": "interact",
            "url": "https://example.com/login",
            "args": {
                "actions": [
                    {"type": "fill", "selector": "#email", "value": "test@test.com"},
                    {"type": "click", "selector": "button[type=submit]"},
                ]
            },
        },
    },
    "regression-check": {
        "description": "All-in-one regression testing with console/network monitoring",
        "args": {
            "url": "Target URL (required)",
            "checkConsole": "Check for console errors (default: true)",
            "checkNetwork": "Monitor network failures (default: true)",
        },
        "example": {
            "script_name": "regression-check",
            "url": "https://example.com",
            "args": {"checkConsole": True, "checkNetwork": True},
        },
    },
    "console": {
        "description": "Capture console messages",
        "args": {
            "url": "Target URL (required)",
            "filter": "Filter by log level (error, warn, info)",
        },
        "example": {
            "script_name": "console",
            "url": "https://example.com",
            "args": {"filter": "error"},
        },
    },
    "network": {
        "description": "Monitor network requests",
        "args": {
            "url": "Target URL (required)",
            "filter": "Filter by request type or URL pattern",
        },
        "example": {
            "script_name": "network",
            "url": "https://example.com",
            "args": {"filter": "/api/"},
        },
    },
    "capture-evidence": {
        "description": "Capture comprehensive evidence (screenshot, console, network)",
        "args": {
            "url": "Target URL (required)",
            "featureId": "Feature ID for evidence storage",
            "criterionId": "Criterion ID for evidence storage",
        },
        "example": {
            "script_name": "capture-evidence",
            "url": "https://example.com/feature",
            "args": {"featureId": "FEAT-001", "criterionId": "ac-001"},
        },
    },
    "expand": {
        "description": "Expand collapsed UI elements and take screenshot",
        "args": {
            "url": "Target URL (required)",
            "selector": "CSS selector for expandable element",
        },
        "example": {
            "script_name": "expand",
            "url": "https://example.com",
            "args": {"selector": "[data-expandable]"},
        },
    },
}


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
    import os

    # Merge with current environment
    full_env = os.environ.copy()
    if env:
        full_env.update(env)

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
        proc.kill()
        await proc.wait()
        return -1, "", f"Command timed out after {timeout}s"
    except Exception as e:
        return -1, "", str(e)


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
    # Get test from registry
    test = tests_storage.get_test(project_id, test_id)
    if not test:
        raise ValueError(f"Test not found: {test_id}")

    # Get project config
    config = get_project_config(project_id)
    if not config:
        raise ValueError(f"Project not found: {project_id}")

    # Dispatch to type-specific runner
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

    # Store result in test_runs table
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

    # Register evidence if this is a UI test with evidence
    if test_type == "ui" and result.evidence_path and test_run:
        from . import evidence_manager

        evidence_manager.register_test_evidence(
            project_id=project_id,
            test_id=test_id,
            test_run_id=test_run["id"],
            evidence_path=result.evidence_path,
        )

    # Update test.last_* fields
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
    # Get tests to run
    if test_ids:
        tests = [tests_storage.get_test(project_id, tid) for tid in test_ids]
        tests = [t for t in tests if t is not None]
    else:
        # Filter by tier if specified
        all_tests = tests_storage.list_tests(project_id)
        if tier == "smoke":
            # Smoke = fast tests (pytest, ruff, mypy)
            tests = [t for t in all_tests if t["test_type"] in ("pytest", "ruff", "mypy")]
        elif tier == "unit":
            tests = [t for t in all_tests if t["test_type"] in ("pytest", "vitest")]
        elif tier == "integration":
            tests = [t for t in all_tests if t["test_type"] in ("ui", "api")]
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
    """Run a pytest test.

    Args:
        test: Test dict from registry
        config: Project configuration

    Returns:
        TestResult with pass/fail status.
    """
    import os

    # Build working directory
    working_dir = os.path.join(config.root_path, config.backend_root)

    # Build command - minimal output for token efficiency
    # Use test command if specified, otherwise use test name as path
    test_path = test["command"] or test["name"]
    command = f"{config.pytest_path} {test_path} -v --tb=no -q"

    timeout = test.get("timeout_seconds", 60)

    exit_code, stdout, stderr = await _run_command(
        command=command,
        working_dir=working_dir,
        timeout=timeout,
    )

    output = stdout + ("\n" + stderr if stderr else "")
    passed = exit_code == 0

    return TestResult(
        passed=passed,
        duration_ms=0,  # Will be set by caller
        output=_truncate_output(output),
        error=stderr if not passed and stderr else None,
    )


async def run_mypy(test: dict[str, Any], config: ProjectConfig) -> TestResult:
    """Run mypy type checking.

    Args:
        test: Test dict from registry
        config: Project configuration

    Returns:
        TestResult with pass/fail status.
    """
    import os

    working_dir = os.path.join(config.root_path, config.backend_root)

    # Use test command if specified, otherwise default path
    test_path = test["command"] or "app/"
    command = f"{config.pytest_path.replace('pytest', 'mypy')} {test_path} --no-error-summary"

    timeout = test.get("timeout_seconds", 120)

    exit_code, stdout, stderr = await _run_command(
        command=command,
        working_dir=working_dir,
        timeout=timeout,
    )

    output = stdout + ("\n" + stderr if stderr else "")
    passed = exit_code == 0

    return TestResult(
        passed=passed,
        duration_ms=0,
        output=_truncate_output(output),
        error=output if not passed else None,
    )


async def run_ruff(test: dict[str, Any], config: ProjectConfig) -> TestResult:
    """Run ruff linting.

    Args:
        test: Test dict from registry
        config: Project configuration

    Returns:
        TestResult with pass/fail status.
    """
    import os

    working_dir = os.path.join(config.root_path, config.backend_root)

    # Use test command if specified, otherwise default path
    test_path = test["command"] or "app/"
    command = f"ruff check {test_path} --output-format=concise"

    timeout = test.get("timeout_seconds", 60)

    exit_code, stdout, stderr = await _run_command(
        command=command,
        working_dir=working_dir,
        timeout=timeout,
    )

    output = stdout + ("\n" + stderr if stderr else "")
    passed = exit_code == 0

    return TestResult(
        passed=passed,
        duration_ms=0,
        output=_truncate_output(output),
        error=output if not passed else None,
    )


async def run_vitest(test: dict[str, Any], config: ProjectConfig) -> TestResult:
    """Run vitest JavaScript/TypeScript tests.

    Args:
        test: Test dict from registry
        config: Project configuration

    Returns:
        TestResult with pass/fail status.
    """
    import os

    working_dir = os.path.join(config.root_path, config.frontend_root)

    # Use test command if specified, otherwise use test name as path
    test_path = test["command"] or test["name"]
    command = f"{config.node_path} vitest run --reporter=dot {test_path}"

    timeout = test.get("timeout_seconds", 120)

    exit_code, stdout, stderr = await _run_command(
        command=command,
        working_dir=working_dir,
        timeout=timeout,
    )

    output = stdout + ("\n" + stderr if stderr else "")
    passed = exit_code == 0

    return TestResult(
        passed=passed,
        duration_ms=0,
        output=_truncate_output(output),
        error=stderr if not passed and stderr else None,
    )


async def run_api_test(test: dict[str, Any], config: ProjectConfig) -> TestResult:
    """Run HTTP API test.

    Uses curl command from test.command or builds from test.config.
    Supports jq assertions in test.config.assertions.

    Args:
        test: Test dict from registry
        config: Project configuration

    Returns:
        TestResult with pass/fail status.
    """
    command = test.get("command")
    test_config = test.get("config", {})

    if not command and test_config:
        # Build curl command from config
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

    exit_code, stdout, stderr = await _run_command(
        command=command,
        working_dir=config.root_path,
        timeout=timeout,
    )

    # Check HTTP status code
    passed = exit_code == 0

    # Check assertions if defined
    assertions = test_config.get("assertions", [])
    if passed and assertions:
        for assertion in assertions:
            jq_filter = assertion.get("jq")
            expected = assertion.get("expected")
            if jq_filter:
                # Run jq to check assertion
                jq_cmd = f"jq '{jq_filter}' /tmp/api_response.json"
                _jq_exit, jq_out, _ = await _run_command(jq_cmd, config.root_path, timeout=10)
                actual = jq_out.strip()
                if str(actual) != str(expected):
                    passed = False
                    stdout += f"\nAssertion failed: {jq_filter} = {actual}, expected {expected}"
                    break

    output = stdout + ("\n" + stderr if stderr else "")

    return TestResult(
        passed=passed,
        duration_ms=0,
        output=_truncate_output(output),
        error=stderr if not passed and stderr else None,
    )


async def run_ui_test(test: dict[str, Any], config: ProjectConfig) -> TestResult:
    """Run browser automation UI test.

    Uses browser-automation skill scripts from ~/.claude/skills/browser-automation/scripts/.

    Test configuration (in test['config']):
        script_name: Name of browser-automation script (screenshot, interact, etc.)
        url: Target URL to test
        args: Additional arguments to pass to the script
        assertions: List of assertions to check after execution
        output_path: Custom output path for evidence

    Alternatively, use test['script'] for inline JS or test['command'] for raw command.

    Args:
        test: Test dict from registry
        config: Project configuration

    Returns:
        TestResult with pass/fail status and evidence path.
    """
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

        # Build command based on script type
        command = _build_browser_script_command(
            script_path=script_path,
            script_name=script_name,
            url=url,
            args=args,
            output_path=output_path,
        )

        timeout = test.get("timeout_seconds", 120)
        exit_code, stdout, stderr = await _run_command(
            command=command,
            working_dir=config.root_path,
            timeout=timeout,
        )

        # Parse output for structured results
        result = _parse_browser_script_output(stdout, stderr, exit_code)

        # Check assertions if defined
        assertions = test_config.get("assertions", [])
        if result.passed and assertions:
            assertion_result = await _check_ui_assertions(assertions, stdout, config)
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

            exit_code, stdout, stderr = await _run_command(
                command=command,
                working_dir=config.root_path,
                timeout=timeout,
            )

            output = stdout + ("\n" + stderr if stderr else "")
            passed = exit_code == 0

            # Try to find evidence path from output
            evidence_path = _extract_evidence_path(stdout)

            return TestResult(
                passed=passed,
                duration_ms=0,
                output=_truncate_output(output),
                error=stderr if not passed and stderr else None,
                evidence_path=evidence_path,
            )
        finally:
            Path(temp_script_path).unlink(missing_ok=True)

    # Priority 3: Raw command
    command = test.get("command")
    if command:
        timeout = test.get("timeout_seconds", 120)

        exit_code, stdout, stderr = await _run_command(
            command=command,
            working_dir=config.root_path,
            timeout=timeout,
        )

        output = stdout + ("\n" + stderr if stderr else "")
        passed = exit_code == 0

        return TestResult(
            passed=passed,
            duration_ms=0,
            output=_truncate_output(output),
            error=stderr if not passed and stderr else None,
        )

    return TestResult(
        passed=False,
        duration_ms=0,
        output="",
        error="UI test requires script_name (in config), script (inline), or command",
    )


def _build_browser_script_command(
    script_path: Path,
    script_name: str,
    url: str,
    args: dict[str, Any],
    output_path: str | None = None,
) -> str:
    """Build command to run a browser-automation script.

    Different scripts have different argument patterns:
    - screenshot.js: node screenshot.js <url> [--output <path>] [--fullPage]
    - interact.js: node interact.js <url> --actions '<json>'
    - regression-check.js: node regression-check.js <url>
    """
    import shlex

    cmd_parts = ["node", str(script_path)]

    # URL is typically the first positional argument
    if url:
        cmd_parts.append(shlex.quote(url))

    # Handle common args
    if output_path:
        cmd_parts.extend(["--output", shlex.quote(output_path)])

    # Script-specific argument handling
    if script_name == "screenshot":
        if args.get("fullPage", True):
            cmd_parts.append("--fullPage")
        if args.get("selector"):
            cmd_parts.extend(["--selector", shlex.quote(args["selector"])])

    elif script_name in ("click-screenshot", "tab-click-screenshot"):
        if args.get("selector"):
            cmd_parts.extend(["--selector", shlex.quote(args["selector"])])

    elif script_name == "interact":
        if args.get("actions"):
            cmd_parts.extend(["--actions", shlex.quote(json.dumps(args["actions"]))])

    elif script_name == "regression-check":
        if args.get("checkConsole", True):
            cmd_parts.append("--checkConsole")
        if args.get("checkNetwork", True):
            cmd_parts.append("--checkNetwork")

    elif script_name in ("console", "network"):
        if args.get("filter"):
            cmd_parts.extend(["--filter", shlex.quote(args["filter"])])

    elif script_name == "capture-evidence":
        if args.get("featureId"):
            cmd_parts.extend(["--featureId", shlex.quote(args["featureId"])])
        if args.get("criterionId"):
            cmd_parts.extend(["--criterionId", shlex.quote(args["criterionId"])])

    elif script_name == "expand":
        if args.get("selector"):
            cmd_parts.extend(["--selector", shlex.quote(args["selector"])])

    # Pass any other args as JSON
    other_args = {
        k: v
        for k, v in args.items()
        if k
        not in (
            "fullPage",
            "selector",
            "actions",
            "checkConsole",
            "checkNetwork",
            "filter",
            "featureId",
            "criterionId",
        )
    }
    if other_args:
        cmd_parts.extend(["--extra", shlex.quote(json.dumps(other_args))])

    return " ".join(cmd_parts)


def _parse_browser_script_output(stdout: str, stderr: str, exit_code: int) -> TestResult:
    """Parse output from a browser-automation script.

    Scripts may output JSON with structured results:
    {
        "success": true/false,
        "screenshot": "/path/to/screenshot.png",
        "errors": ["error1", "error2"],
        "console": [...],
        "network": [...]
    }
    """
    output = stdout + ("\n" + stderr if stderr else "")
    passed = exit_code == 0
    evidence_path = None
    error = None

    # Try to parse JSON from output
    try:
        # Look for JSON in output (may be mixed with other text)
        for line in stdout.split("\n"):
            line = line.strip()
            if line.startswith("{") and line.endswith("}"):
                result_json = json.loads(line)

                # Check for explicit success/failure
                if "success" in result_json:
                    passed = result_json["success"]

                # Extract evidence path
                if result_json.get("screenshot"):
                    evidence_path = result_json["screenshot"]
                elif result_json.get("evidence_path"):
                    evidence_path = result_json["evidence_path"]

                # Extract errors
                if result_json.get("errors"):
                    error = "; ".join(result_json["errors"])
                    if error:
                        passed = False

                break
    except json.JSONDecodeError:
        pass

    # If exit code is non-zero and no error extracted, use stderr
    if not passed and not error and stderr:
        error = stderr.strip()

    return TestResult(
        passed=passed,
        duration_ms=0,
        output=_truncate_output(output),
        error=error,
        evidence_path=evidence_path,
    )


def _extract_evidence_path(output: str) -> str | None:
    """Extract evidence path from script output.

    Looks for patterns like:
    - Screenshot saved: /path/to/file.png
    - Evidence: /path/to/dir
    - {"screenshot": "/path/to/file.png"}
    """
    import re

    # Try JSON first
    try:
        for line in output.split("\n"):
            line = line.strip()
            if line.startswith("{"):
                data = json.loads(line)
                return data.get("screenshot") or data.get("evidence_path")
    except (json.JSONDecodeError, AttributeError):
        pass

    # Try common patterns
    patterns = [
        r"Screenshot saved[:\s]+(.+\.png)",
        r"Evidence[:\s]+(.+)",
        r"Output[:\s]+(.+\.png)",
    ]
    for pattern in patterns:
        match = re.search(pattern, output, re.IGNORECASE)
        if match:
            return match.group(1).strip()

    return None


async def _check_ui_assertions(
    assertions: list[dict[str, Any]], output: str, config: ProjectConfig
) -> tuple[bool, str | None]:
    """Check assertions after UI test execution.

    Supported assertion types:
    - console_errors: Check that no console errors occurred
    - network_failures: Check that no network requests failed
    - element_exists: Check that an element exists in screenshot/DOM
    - output_contains: Check that output contains expected text
    - exit_code: Check exit code (already handled by caller)
    """
    for assertion in assertions:
        assertion_type = assertion.get("type")

        if assertion_type == "console_errors":
            # Check for console errors in output
            if "console.error" in output.lower() or '"level":"error"' in output.lower():
                return False, "Console errors detected"

        elif assertion_type == "network_failures":
            # Check for network failures in output
            if "failed" in output.lower() and "network" in output.lower():
                return False, "Network failures detected"

        elif assertion_type == "output_contains":
            expected = assertion.get("expected", "")
            if expected and expected not in output:
                return False, f"Output does not contain: {expected}"

        elif assertion_type == "output_not_contains":
            forbidden = assertion.get("forbidden", "")
            if forbidden and forbidden in output:
                return False, f"Output contains forbidden text: {forbidden}"

        elif assertion_type == "element_exists":
            # This would require parsing the page content
            # For now, just check if the selector appears in output
            selector = assertion.get("selector", "")
            if selector and f"Element not found: {selector}" in output:
                return False, f"Element not found: {selector}"

    return True, None
