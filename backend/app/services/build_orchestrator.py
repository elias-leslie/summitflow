"""Build orchestrator service - TDD agent build loop.

This module orchestrates the Test-Driven Development (TDD) build process:
1. Identifies failing capabilities (tests not passing)
2. Orders by priority
3. For each capability: run tests → call agent → verify → repeat

The build loop implements:
- Smoke tests for fast feedback
- Full test suite when smoke passes
- Retry logic with configurable max attempts
- Session tracking with detailed stats
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from ..storage import agent_sessions as sessions_storage
from ..storage import capabilities as caps_storage
from ..storage import tests as tests_storage
from .agents import get_agent
from .test_runner import TestResult, get_project_config, run_test

logger = logging.getLogger(__name__)

# Build configuration
MAX_RETRY_ATTEMPTS = 5
SMOKE_TEST_TYPES = {"pytest", "vitest"}  # Quick-running test types

# TDD System Prompt for agent fix calls
TDD_SYSTEM_PROMPT = """You are a TDD (Test-Driven Development) agent fixing failing tests.

Your task is to analyze the test failures and implement code changes to make the tests pass.

RULES:
1. Focus ONLY on making the failing tests pass
2. Do NOT add new features or refactor unrelated code
3. Make minimal changes required to fix the tests
4. If a test is genuinely wrong, explain why and suggest a fix
5. Preserve existing functionality - don't break passing tests

When writing code changes:
- Use the exact file paths from the test output
- Make targeted, surgical fixes
- Include brief comments explaining non-obvious changes

After making changes, the tests will be re-run automatically.
If tests still fail, you'll receive the new output and can try again.
"""


@dataclass
class BuildStatus:
    """Current build status."""

    session_id: str
    status: str  # 'running', 'paused', 'completed', 'failed'
    current_capability: str | None = None
    capabilities_total: int = 0
    capabilities_completed: int = 0
    tests_run: int = 0
    tests_passed: int = 0
    tests_failed: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for API response."""
        return {
            "session_id": self.session_id,
            "status": self.status,
            "current_capability": self.current_capability,
            "capabilities_total": self.capabilities_total,
            "capabilities_completed": self.capabilities_completed,
            "tests_run": self.tests_run,
            "tests_passed": self.tests_passed,
            "tests_failed": self.tests_failed,
            "progress_percent": (
                round(self.capabilities_completed / self.capabilities_total * 100)
                if self.capabilities_total > 0
                else 0
            ),
        }


# Active builds tracker (in-memory for now, could be Redis)
_active_builds: dict[str, BuildStatus] = {}


async def start_build(
    project_id: str,
    component_id: int | None = None,
    agent_type: str = "claude",
) -> dict[str, Any]:
    """Start a new TDD build session.

    Args:
        project_id: Project ID
        component_id: Optional component ID to filter capabilities
        agent_type: Agent to use ('claude', 'gemini')

    Returns:
        Dict with session_id and build info.
    """
    # Check if there's already an active build for this project
    for session_id, status in _active_builds.items():
        if status.status == "running":
            session = sessions_storage.get_session(project_id, session_id)
            if session:
                raise ValueError(f"Build already running: {session_id}")

    # Create agent session
    session = sessions_storage.create_session(project_id, agent_type)
    session_id = session["session_id"]

    # Get failing capabilities (status != 'passing' and not locked)
    all_capabilities = caps_storage.list_capabilities(project_id, component_id)
    failing_caps = [cap for cap in all_capabilities if cap["status"] not in ("passing", "locked")]

    # Order by priority (lower = higher priority)
    failing_caps.sort(key=lambda c: (c["priority"], c["capability_id"]))

    # Initialize build status
    build_status = BuildStatus(
        session_id=session_id,
        status="running",
        capabilities_total=len(failing_caps),
    )
    _active_builds[session_id] = build_status

    logger.info(
        f"Started build session {session_id} for project {project_id} "
        f"with {len(failing_caps)} failing capabilities"
    )

    return {
        "session_id": session_id,
        "project_id": project_id,
        "agent_type": agent_type,
        "capabilities_to_build": [c["capability_id"] for c in failing_caps],
        "total_capabilities": len(failing_caps),
    }


async def build_capability(
    project_id: str,
    session_id: str,
    capability_id: str,
) -> dict[str, Any]:
    """Build a single capability using TDD loop.

    TDD Loop:
    1. Run tests for capability (expect failure initially)
    2. Call agent to implement/fix
    3. Run smoke tests (quick feedback)
    4. If smoke passes, run full tests
    5. Repeat up to MAX_RETRY_ATTEMPTS

    Args:
        project_id: Project ID
        session_id: Build session ID
        capability_id: Capability to build

    Returns:
        Dict with build result and test stats.
    """
    # Get capability
    capability = caps_storage.get_capability(project_id, capability_id)
    if not capability:
        raise ValueError(f"Capability not found: {capability_id}")

    # Get project config
    config = get_project_config(project_id)
    if not config:
        raise ValueError(f"Project config not found: {project_id}")

    # Mark as attempted in session
    sessions_storage.add_capability_attempted(project_id, session_id, capability_id)

    # Update build status
    if session_id in _active_builds:
        _active_builds[session_id].current_capability = capability_id

    # Get tests for this capability
    tests = tests_storage.get_tests_for_capability(project_id, capability["id"])
    if not tests:
        logger.warning(f"No tests found for capability {capability_id}")
        # Mark as passed (no tests = assume passing)
        caps_storage.update_capability(project_id, capability_id, status="passing")
        sessions_storage.mark_capability_passed(project_id, session_id, capability_id)
        return {
            "capability_id": capability_id,
            "status": "passed",
            "reason": "no_tests",
            "tests_run": 0,
        }

    # Separate smoke vs full tests
    smoke_tests = [t for t in tests if t["test_type"] in SMOKE_TEST_TYPES]
    full_tests = tests

    # TDD Loop
    for attempt in range(1, MAX_RETRY_ATTEMPTS + 1):
        logger.info(f"Building {capability_id}: attempt {attempt}/{MAX_RETRY_ATTEMPTS}")

        # Run smoke tests first
        smoke_results = await _run_test_batch(project_id, session_id, smoke_tests)

        if smoke_results["all_passed"]:
            # Smoke passed, run full suite
            full_results = await _run_test_batch(project_id, session_id, full_tests)

            if full_results["all_passed"]:
                # Success! Mark capability as passing
                caps_storage.update_capability(project_id, capability_id, status="passing")
                sessions_storage.mark_capability_passed(project_id, session_id, capability_id)

                if session_id in _active_builds:
                    _active_builds[session_id].capabilities_completed += 1

                return {
                    "capability_id": capability_id,
                    "status": "passed",
                    "attempts": attempt,
                    "tests_run": full_results["tests_run"],
                    "tests_passed": full_results["tests_passed"],
                }

        # Tests failed - call agent to fix
        failure_info = _get_failure_info(
            smoke_results if not smoke_results["all_passed"] else full_results
        )

        logger.info(
            f"Capability {capability_id} attempt {attempt} failed: {failure_info['summary']}"
        )

        # Call agent to fix the failures
        agent_result = await call_agent_for_fix(
            project_id=project_id,
            capability=capability,
            failure_info=failure_info,
            session_id=session_id,
        )

        if not agent_result["success"]:
            # Agent call failed - record error and continue to next attempt
            logger.error(f"Agent fix failed: {agent_result.get('error', 'unknown')}")
            continue

        # Agent provided a fix - log and continue to re-run tests
        logger.info(
            f"Agent fix attempt {attempt}: received {len(agent_result.get('response', ''))} chars"
        )
        # The actual code changes would be applied by the agent tool calls
        # For now, we just log and continue - tests will be re-run on next iteration

    # All attempts exhausted - mark as failing
    caps_storage.update_capability(project_id, capability_id, status="failing")
    sessions_storage.mark_capability_failed(project_id, session_id, capability_id)

    if session_id in _active_builds:
        _active_builds[session_id].capabilities_completed += 1

    return {
        "capability_id": capability_id,
        "status": "failed",
        "attempts": attempt,
        "failure_info": failure_info,
    }


async def _run_test_batch(
    project_id: str,
    session_id: str,
    tests: list[dict[str, Any]],
) -> dict[str, Any]:
    """Run a batch of tests and aggregate results.

    Args:
        project_id: Project ID
        session_id: Session ID for tracking
        tests: List of test dicts

    Returns:
        Dict with aggregated results.
    """
    results: list[TestResult] = []

    for test in tests:
        result = await run_test(project_id, test["test_id"])
        results.append(result)

    passed = sum(1 for r in results if r.passed)
    failed = len(results) - passed

    # Update session stats
    sessions_storage.increment_test_counts(project_id, session_id, passed=passed, failed=failed)

    # Update in-memory status
    if session_id in _active_builds:
        _active_builds[session_id].tests_run += len(results)
        _active_builds[session_id].tests_passed += passed
        _active_builds[session_id].tests_failed += failed

    return {
        "tests_run": len(results),
        "tests_passed": passed,
        "tests_failed": failed,
        "all_passed": failed == 0,
        "results": [r.to_dict() for r in results],
    }


async def call_agent_for_fix(
    project_id: str,
    capability: dict[str, Any],
    failure_info: dict[str, Any],
    session_id: str,
    agent_type: str = "claude",
) -> dict[str, Any]:
    """Call the LLM agent to fix failing tests.

    Args:
        project_id: Project ID
        capability: Capability dict with name, description
        failure_info: Dict with failure summary and failed tests
        session_id: Build session ID for tracking
        agent_type: Agent to use ('claude' or 'gemini')

    Returns:
        Dict with 'success', 'changes_made', 'response'
    """
    # Build the prompt with context
    prompt = f"""## Capability: {capability.get('name', 'Unknown')}
{capability.get('description', '')}

## Test Failures
{failure_info['summary']}

## Failed Test Details
"""
    for i, test in enumerate(failure_info.get("failed_tests", []), 1):
        prompt += f"\n### Test {i}\n"
        if test.get("error"):
            prompt += f"Error: {test['error']}\n"
        if test.get("output"):
            prompt += f"Output:\n```\n{test['output']}\n```\n"

    prompt += "\n\nAnalyze these failures and provide the code changes needed to fix them."

    try:
        agent = get_agent(agent_type)
        response = agent.generate(
            prompt=prompt,
            system=TDD_SYSTEM_PROMPT,
            max_tokens=4096,
            temperature=0.3,  # Lower temp for more deterministic fixes
        )

        logger.info(
            f"Agent fix response for {capability.get('name')}: "
            f"{len(response.content)} chars, model={response.model}"
        )

        return {
            "success": True,
            "changes_made": True,  # Agent provided response
            "response": response.content,
            "model": response.model,
            "usage": response.usage,
        }

    except Exception as e:
        logger.error(f"Agent fix call failed: {e}")
        return {
            "success": False,
            "changes_made": False,
            "error": str(e),
        }


def _get_failure_info(batch_result: dict[str, Any]) -> dict[str, Any]:
    """Extract failure information from test batch results.

    Args:
        batch_result: Result from _run_test_batch

    Returns:
        Dict with failure summary and details.
    """
    failed_tests = [r for r in batch_result["results"] if not r["passed"]]

    return {
        "summary": f"{len(failed_tests)} test(s) failed",
        "failed_tests": [
            {
                "output": t["output"][:500],  # Truncate for token efficiency
                "error": t["error"],
            }
            for t in failed_tests
        ],
    }


def get_build_status(project_id: str) -> BuildStatus | None:
    """Get the current build status for a project.

    Returns:
        BuildStatus or None if no active build.
    """
    for session_id, status in _active_builds.items():
        session = sessions_storage.get_session(project_id, session_id)
        if session and session.get("status") == "running":
            return status
    return None


def stop_build(project_id: str) -> dict[str, Any] | None:
    """Stop the current build for a project.

    Returns:
        Final build status or None if no active build.
    """
    for session_id, status in list(_active_builds.items()):
        session = sessions_storage.get_session(project_id, session_id)
        if session and session.get("status") == "running":
            # End the session
            sessions_storage.end_session(
                project_id,
                session_id,
                notes="Build stopped by user",
            )

            # Update in-memory status
            status.status = "stopped"

            # Remove from active builds
            del _active_builds[session_id]

            return status.to_dict()

    return None


async def run_full_build(
    project_id: str,
    component_id: int | None = None,
    agent_type: str = "claude",
) -> dict[str, Any]:
    """Run a complete build for all failing capabilities.

    This is the main entry point for a full TDD build cycle.

    Args:
        project_id: Project ID
        component_id: Optional component to scope the build
        agent_type: Agent type to use

    Returns:
        Final build results.
    """
    # Start the build
    start_result = await start_build(project_id, component_id, agent_type)
    session_id = start_result["session_id"]
    capabilities_to_build = start_result["capabilities_to_build"]

    results = []
    for cap_id in capabilities_to_build:
        try:
            result = await build_capability(project_id, session_id, cap_id)
            results.append(result)
        except Exception as e:
            logger.error(f"Failed to build capability {cap_id}: {e}")
            results.append(
                {
                    "capability_id": cap_id,
                    "status": "error",
                    "error": str(e),
                }
            )

    # End the session
    passed_count = sum(1 for r in results if r.get("status") == "passed")
    failed_count = len(results) - passed_count

    notes = f"Build complete: {passed_count}/{len(results)} capabilities passed"
    sessions_storage.end_session(project_id, session_id, notes=notes)

    # Clean up active build
    _active_builds.pop(session_id, None)

    return {
        "session_id": session_id,
        "project_id": project_id,
        "capabilities_built": len(results),
        "capabilities_passed": passed_count,
        "capabilities_failed": failed_count,
        "results": results,
    }
