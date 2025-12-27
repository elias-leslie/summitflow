"""UI test runner - Browser automation using browser-automation skill scripts.

This module handles UI tests using scripts from ~/.claude/skills/browser-automation/scripts/.
Supports screenshot, click-screenshot, interact, regression-check, and other browser automation.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .base import (
    BROWSER_AUTOMATION_SCRIPTS_PATH,
    MAX_OUTPUT_LENGTH,
    ProjectConfig,
    TestResult,
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


def _truncate_output(output: str) -> str:
    """Truncate output to MAX_OUTPUT_LENGTH for token efficiency."""
    if len(output) <= MAX_OUTPUT_LENGTH:
        return output

    half = (MAX_OUTPUT_LENGTH - 50) // 2
    return f"{output[:half]}\n\n... [truncated {len(output) - MAX_OUTPUT_LENGTH} chars] ...\n\n{output[-half:]}"


def _combine_outputs(stdout: str, stderr: str) -> str:
    """Combine stdout and stderr into a single output string."""
    return stdout + ("\n" + stderr if stderr else "")


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


def resolve_browser_script(script_name: str, config: ProjectConfig | None = None) -> Path | None:
    """Resolve a browser-automation script name to its full path.

    Args:
        script_name: Script name (e.g., 'screenshot', 'interact') or filename
        config: Optional project config with custom browser_scripts_path

    Returns:
        Path to the script file if it exists, None otherwise.
    """
    scripts_path = Path(config.browser_scripts_path if config else BROWSER_AUTOMATION_SCRIPTS_PATH)

    if script_name.endswith(".js"):
        script_file = scripts_path / script_name
    else:
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
    has_script_name = config.get("script_name")
    has_script = config.get("script")
    has_command = config.get("command")

    if not any([has_script_name, has_script, has_command]):
        return False, "UI test requires script_name, script, or command"

    if has_script_name:
        available = get_available_browser_scripts(project_config)
        if has_script_name not in available:
            return (
                False,
                f"Unknown script '{has_script_name}'. Available: {', '.join(available)}",
            )

    if has_script_name and has_script_name != "capture-evidence" and not config.get("url"):
        return False, f"Script '{has_script_name}' requires a 'url' parameter"

    assertions = config.get("assertions", [])
    for assertion in assertions:
        if not isinstance(assertion, dict):
            return False, "Each assertion must be a dict"
        if "type" not in assertion:
            return False, "Each assertion must have a 'type' field"

    return True, None


def _add_script_args(
    cmd_parts: list[str],
    script_name: str,
    args: dict[str, Any],
) -> set[str]:
    """Add script-specific arguments and return set of handled arg keys."""
    import shlex

    handled: set[str] = set()

    if script_name == "screenshot":
        if args.get("fullPage", True):
            cmd_parts.append("--fullPage")
        handled.add("fullPage")
        if args.get("selector"):
            cmd_parts.extend(["--selector", shlex.quote(args["selector"])])
            handled.add("selector")

    elif script_name in ("click-screenshot", "tab-click-screenshot", "expand"):
        if args.get("selector"):
            cmd_parts.extend(["--selector", shlex.quote(args["selector"])])
            handled.add("selector")

    elif script_name == "interact":
        if args.get("actions"):
            cmd_parts.extend(["--actions", shlex.quote(json.dumps(args["actions"]))])
            handled.add("actions")

    elif script_name == "regression-check":
        if args.get("checkConsole", True):
            cmd_parts.append("--checkConsole")
        handled.add("checkConsole")
        if args.get("checkNetwork", True):
            cmd_parts.append("--checkNetwork")
        handled.add("checkNetwork")

    elif script_name in ("console", "network"):
        if args.get("filter"):
            cmd_parts.extend(["--filter", shlex.quote(args["filter"])])
            handled.add("filter")

    elif script_name == "capture-evidence":
        if args.get("featureId"):
            cmd_parts.extend(["--featureId", shlex.quote(args["featureId"])])
            handled.add("featureId")
        if args.get("criterionId"):
            cmd_parts.extend(["--criterionId", shlex.quote(args["criterionId"])])
            handled.add("criterionId")

    return handled


def build_browser_script_command(
    script_path: Path,
    script_name: str,
    url: str,
    args: dict[str, Any],
    output_path: str | None = None,
) -> str:
    """Build command to run a browser-automation script."""
    import shlex

    cmd_parts = ["node", str(script_path)]

    if url:
        cmd_parts.append(shlex.quote(url))

    if output_path:
        cmd_parts.extend(["--output", shlex.quote(output_path)])

    handled_keys = _add_script_args(cmd_parts, script_name, args)

    other_args = {k: v for k, v in args.items() if k not in handled_keys}
    if other_args:
        cmd_parts.extend(["--extra", shlex.quote(json.dumps(other_args))])

    return " ".join(cmd_parts)


def parse_browser_script_output(stdout: str, stderr: str, exit_code: int) -> TestResult:
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
    output = _combine_outputs(stdout, stderr)
    passed = exit_code == 0
    evidence_path = None
    error = None

    try:
        for line in stdout.split("\n"):
            line = line.strip()
            if line.startswith("{") and line.endswith("}"):
                result_json = json.loads(line)

                if "success" in result_json:
                    passed = result_json["success"]

                if result_json.get("screenshot"):
                    evidence_path = result_json["screenshot"]
                elif result_json.get("evidence_path"):
                    evidence_path = result_json["evidence_path"]

                if result_json.get("errors"):
                    error = "; ".join(result_json["errors"])
                    if error:
                        passed = False

                break
    except json.JSONDecodeError:
        pass

    if not passed and not error and stderr:
        error = stderr.strip()

    return TestResult(
        passed=passed,
        duration_ms=0,
        output=_truncate_output(output),
        error=error,
        evidence_path=evidence_path,
    )


def extract_evidence_path(output: str) -> str | None:
    """Extract evidence path from script output.

    Looks for patterns like:
    - Screenshot saved: /path/to/file.png
    - Evidence: /path/to/dir
    - {"screenshot": "/path/to/file.png"}
    """
    import re

    try:
        for line in output.split("\n"):
            line = line.strip()
            if line.startswith("{"):
                data = json.loads(line)
                return data.get("screenshot") or data.get("evidence_path")
    except (json.JSONDecodeError, AttributeError):
        pass

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


async def check_ui_assertions(
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
            if "console.error" in output.lower() or '"level":"error"' in output.lower():
                return False, "Console errors detected"

        elif assertion_type == "network_failures":
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
            selector = assertion.get("selector", "")
            if selector and f"Element not found: {selector}" in output:
                return False, f"Element not found: {selector}"

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
