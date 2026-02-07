"""Step verification for autonomous execution.

Handles parsing and executing verification commands with proper output matching.
Supports multiple verification patterns:
- Exit code checks (returncode == 0)
- Output contains checks (expected string in stdout)
- Command aliases (dt -> actual commands)
- Venv path resolution (resolves relative .venv paths to absolute)
- Smoke tests for changed Python files (import + __all__ checks)
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ...core.debug import debug_error, debug_success
from ...logging_config import get_logger
from ...storage.projects import get_project_root_path

logger = get_logger(__name__)

COMMAND_ALIASES: dict[str, str] = {
    # dt commands run as-is - they have proper TOON output format
    # No expansion needed since dt is in PATH (~/.local/bin/dt)
}


def _resolve_venv_paths(cmd: str, project_id: str) -> str:
    """Resolve .venv paths to absolute paths.

    Args:
        cmd: Command that may contain .venv references
        project_id: Project ID to look up repo path

    Returns:
        Command with absolute venv paths
    """
    if ".venv" not in cmd:
        return cmd

    main_repo = get_project_root_path(project_id)
    if not main_repo:
        return cmd

    main_backend_venv = Path(main_repo) / "backend" / ".venv"
    if not main_backend_venv.exists():
        return cmd

    # Handle both "backend/.venv/bin/" and bare ".venv/bin/" patterns
    # Must check backend/ prefix first to avoid double-replacement
    if "backend/.venv/bin/" in cmd:
        return cmd.replace("backend/.venv/bin/", f"{main_backend_venv}/bin/")
    return cmd.replace(".venv/bin/", f"{main_backend_venv}/bin/")


@dataclass
class VerificationResult:
    """Result of a step verification."""

    passed: bool
    step_number: int
    output: str
    returncode: int
    reason: str


def expand_command(cmd: str) -> str:
    """Expand command aliases to full commands."""
    for alias, expansion in COMMAND_ALIASES.items():
        if cmd.strip().startswith(alias):
            remainder = cmd.strip()[len(alias) :].strip()
            return f"{expansion} {remainder}".strip()
    return cmd


def parse_expected(expected: str | None) -> tuple[str, str | None]:
    """Parse expected_output into (check_type, value).

    Returns:
        (check_type, value) where check_type is one of:
        - "exit_code": Check returncode == 0
        - "contains": Check value in output
        - "exact": Check output == value
    """
    if not expected:
        return ("exit_code", None)

    expected_lower = expected.lower().strip()

    if expected_lower.startswith("exit code"):
        return ("exit_code", None)

    # Note: "lint:ok", "types:ok", "test:ok" are now checked as output content
    # Previously only checked exit code, which caused false positives when
    # commands failed but pipeline exit code was 0

    if expected_lower.startswith("contains:"):
        return ("contains", expected[9:].strip())

    return ("contains", expected)


def verify_step(
    step: dict[str, Any],
    working_dir: str,
    timeout: int = 60,
    project_id: str | None = None,
) -> VerificationResult:
    """Verify a single step.

    Args:
        step: Step dict with verify_command and expected_output
        working_dir: Directory to run command in
        timeout: Command timeout in seconds
        project_id: Project ID for resolving venv paths

    Returns:
        VerificationResult with pass/fail status
    """
    step_num = step.get("step_number", 0)
    verify_cmd = step.get("verify_command")
    expected = step.get("expected_output", "")

    if not verify_cmd:
        return VerificationResult(
            passed=True,
            step_number=step_num,
            output="",
            returncode=0,
            reason="no_verify_command",
        )

    expanded_cmd = expand_command(verify_cmd)
    if project_id:
        expanded_cmd = _resolve_venv_paths(expanded_cmd, project_id)
    check_type, check_value = parse_expected(expected)

    if any(cmd in expanded_cmd for cmd in ["dt ", "commit.sh", "npm run build"]):
        timeout = max(timeout, 300)

    effective_cwd = working_dir
    backend_dir = str(Path(working_dir) / "backend")
    if Path(backend_dir).is_dir():
        if "pytest backend/" in expanded_cmd or "python -c" in expanded_cmd:
            effective_cwd = backend_dir
            expanded_cmd = expanded_cmd.replace("backend/tests/", "tests/").replace(
                "backend/.venv/", ".venv/"
            )

    logger.info(
        "Verifying step",
        step_num=step_num,
        original_cmd=verify_cmd[:80],
        expanded_cmd=expanded_cmd[:80] if expanded_cmd != verify_cmd else None,
        check_type=check_type,
        check_value=check_value[:50] if check_value else None,
        cwd=effective_cwd,
    )

    try:
        result = subprocess.run(
            expanded_cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=effective_cwd,
        )

        output = result.stdout.strip()
        stderr = result.stderr.strip()
        full_output = f"{output}\n{stderr}".strip() if stderr else output

        if check_type == "exit_code":
            passed = result.returncode == 0
            reason = "exit_code_0" if passed else f"exit_code_{result.returncode}"
        elif check_type == "contains":
            passed = check_value in full_output if check_value else True
            reason = "contains_match" if passed else "contains_not_found"
        else:
            passed = result.returncode == 0
            reason = "default_exit_code"

        logger.info(
            "Step verification result",
            step_num=step_num,
            passed=passed,
            returncode=result.returncode,
            check_type=check_type,
            reason=reason,
            output_preview=full_output[:200] if full_output else "(empty)",
        )

        if passed:
            debug_success(
                f"Step {step_num} verified",
                step=step_num,
                check_type=check_type,
                output_preview=full_output[:100] if full_output else "(empty)",
            )
        else:
            debug_error(
                f"Step {step_num} failed",
                step=step_num,
                check_type=check_type,
                reason=reason,
                output_preview=full_output[:200] if full_output else "(empty)",
            )

        return VerificationResult(
            passed=passed,
            step_number=step_num,
            output=full_output[:1000],
            returncode=result.returncode,
            reason=reason,
        )

    except subprocess.TimeoutExpired:
        logger.warning("Step verification timed out", step_num=step_num, timeout=timeout)
        return VerificationResult(
            passed=False,
            step_number=step_num,
            output="",
            returncode=-1,
            reason="timeout",
        )
    except Exception as e:
        logger.warning("Step verification error", step_num=step_num, error=str(e))
        return VerificationResult(
            passed=False,
            step_number=step_num,
            output="",
            returncode=-1,
            reason=f"error: {e}",
        )


@dataclass
class SmokeTestResult:
    """Result of a smoke test on changed files."""

    passed: bool
    files_tested: list[str] = field(default_factory=list)
    failures: list[dict[str, str]] = field(default_factory=list)


def _detect_changed_files(project_path: str) -> list[str]:
    """Detect Python files changed in the last commit.

    Uses git diff HEAD~1 to find files modified by the agent.

    Returns:
        List of changed .py file paths relative to project root.
    """
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", "HEAD~1", "--", "*.py"],
            cwd=project_path,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            logger.warning("git_diff_failed", stderr=result.stderr[:200])
            return []

        files = [f.strip() for f in result.stdout.strip().split("\n") if f.strip()]
        logger.info("smoke_test_files_detected", count=len(files), files=files[:10])
        return files
    except Exception as e:
        logger.warning("smoke_test_detect_error", error=str(e))
        return []


def _file_to_module(project_path: str, file_path: str) -> str | None:
    """Convert file path to Python module name.

    Args:
        project_path: Root path of the project
        file_path: Relative path like 'backend/cli/output.py'

    Returns:
        Module name like 'cli.output' or None if not importable.
    """
    if not file_path.endswith(".py"):
        return None
    file_path = file_path[:-12] if file_path.endswith("__init__.py") else file_path[:-3]

    # Handle backend/ prefix - strip it for module path
    if file_path.startswith("backend/"):
        file_path = file_path[8:]

    # Handle app/ prefix - keep it for summitflow backend structure
    # Convert path separators to dots
    module_name = file_path.replace("/", ".").replace("\\", ".")

    # Skip test files and migrations
    if "test" in module_name.lower() or "migration" in module_name.lower():
        return None

    return module_name if module_name else None


def _smoke_test_module(project_path: str, module_name: str) -> dict[str, str] | None:
    """Attempt to import a module to catch import-time errors.

    This is a simple smoke test that verifies the module can be imported.
    Catches: import errors, circular imports, missing dependencies, syntax errors.

    For function-body bugs (like fmt._truncate), rely on unit tests.
    Per Gemini Pro: AST analysis is overkill - if mypy passes, a custom parser
    adds maintenance weight without solving the core problem.

    Args:
        project_path: Project root (for venv path)
        module_name: Dotted module name like 'cli.output'

    Returns:
        Error dict with 'module' and 'error' keys, or None if passed.
    """
    # Use project's venv Python
    backend_path = Path(project_path) / "backend"
    venv_python = backend_path / ".venv" / "bin" / "python"
    if not venv_python.exists():
        venv_python = Path(project_path) / ".venv" / "bin" / "python"

    python_cmd = str(venv_python) if venv_python.exists() else "python"

    # Simple import test - catches import errors, circular imports, missing deps
    import_cmd = f"import {module_name}"

    try:
        result = subprocess.run(
            [python_cmd, "-c", import_cmd],
            cwd=str(backend_path) if backend_path.exists() else project_path,
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode != 0:
            error_msg = result.stderr.strip()
            # Extract the actual error from traceback
            if "Error:" in error_msg:
                error_lines = error_msg.split("\n")
                error_msg = next(
                    (line for line in reversed(error_lines) if "Error:" in line),
                    error_msg[-500:],
                )
            return {"module": module_name, "error": error_msg[:500]}

        return None

    except subprocess.TimeoutExpired:
        return {"module": module_name, "error": "import timed out after 30s"}
    except Exception as e:
        return {"module": module_name, "error": str(e)[:500]}


def run_smoke_tests(project_path: str, changed_files: list[str] | None = None) -> SmokeTestResult:
    """Run smoke tests on changed Python files.

    Automatically detects changed files if not provided.
    Tests each file by attempting to import its module.

    Args:
        project_path: Project root path
        changed_files: Optional list of changed files (auto-detected if None)

    Returns:
        SmokeTestResult with pass/fail status and any failures.
    """
    if changed_files is None:
        changed_files = _detect_changed_files(project_path)

    if not changed_files:
        logger.info("smoke_test_skipped", reason="no changed files")
        return SmokeTestResult(passed=True)

    failures: list[dict[str, str]] = []
    tested: list[str] = []

    for file_path in changed_files:
        module_name = _file_to_module(project_path, file_path)
        if not module_name:
            continue

        tested.append(module_name)
        error = _smoke_test_module(project_path, module_name)
        if error:
            failures.append(error)
            logger.warning(
                "smoke_test_failed",
                module=module_name,
                error=error["error"][:200],
            )
        else:
            debug_success(f"Smoke test passed: {module_name}")

    passed = len(failures) == 0
    if passed:
        logger.info("smoke_tests_passed", tested=len(tested))
    else:
        logger.error(
            "smoke_tests_failed",
            tested=len(tested),
            failed=len(failures),
            failures=failures,
        )
        debug_error(
            "Smoke tests failed",
            tested=len(tested),
            failed=len(failures),
        )

    return SmokeTestResult(
        passed=passed,
        files_tested=tested,
        failures=failures,
    )
