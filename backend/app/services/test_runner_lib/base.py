"""Base test runner types and configuration.

Contains shared dataclasses used across all test types.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any

# Browser automation scripts path - uses ~/.claude/skills/browser-automation/scripts/ by default
BROWSER_AUTOMATION_SCRIPTS_PATH = os.environ.get(
    "BROWSER_AUTOMATION_SCRIPTS_PATH",
    os.path.expanduser("~/.claude/skills/browser-automation/scripts"),
)


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


@dataclass(frozen=True)
class TestToolSpec:
    """Configuration for a test tool (pytest, mypy, ruff, vitest)."""

    name: str
    root_attr: str  # "backend_root" or "frontend_root"
    default_path: str
    command_template: str  # {tool_path} and {test_path} placeholders
    default_timeout: int = 60
    use_stderr_as_error: bool = False


# Tool specifications for generic test runner
TEST_TOOL_SPECS: dict[str, TestToolSpec] = {
    "pytest": TestToolSpec(
        name="pytest",
        root_attr="backend_root",
        default_path="tests/",
        command_template="{tool_path} {test_path} -v --tb=no -q",
        default_timeout=60,
        use_stderr_as_error=True,
    ),
    "mypy": TestToolSpec(
        name="mypy",
        root_attr="backend_root",
        default_path="app/",
        command_template="{tool_path} {test_path} --no-error-summary",
        default_timeout=120,
        use_stderr_as_error=False,
    ),
    "ruff": TestToolSpec(
        name="ruff",
        root_attr="backend_root",
        default_path="app/",
        command_template="ruff check {test_path} --output-format=concise",
        default_timeout=60,
        use_stderr_as_error=False,
    ),
    "vitest": TestToolSpec(
        name="vitest",
        root_attr="frontend_root",
        default_path="",
        command_template="{tool_path} vitest run --reporter=dot {test_path}",
        default_timeout=120,
        use_stderr_as_error=True,
    ),
}

# Maximum output length to store (token efficiency)
MAX_OUTPUT_LENGTH = 1000

# Test tier to test type mapping
TIER_TEST_TYPES: dict[str, tuple[str, ...]] = {
    "smoke": ("pytest", "ruff", "mypy"),
    "unit": ("pytest", "vitest"),
    "integration": ("ui", "api"),
}
