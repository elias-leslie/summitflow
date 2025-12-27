"""Test runner package - Execute tests by type with token-optimized output.

This package provides async test execution for various test types:
- pytest: Python unit/integration tests
- mypy: Python type checking
- ruff: Python linting
- vitest: JavaScript/TypeScript unit tests
- api: HTTP API tests (curl-based)
- ui: Browser automation tests (using browser-automation skill)

Results are stored in the test_runs table and test metadata is updated.
"""

# Re-export base types
from .base import (
    BROWSER_AUTOMATION_SCRIPTS_PATH,
    MAX_OUTPUT_LENGTH,
    TEST_TOOL_SPECS,
    TIER_TEST_TYPES,
    ProjectConfig,
    TestResult,
    TestToolSpec,
)

# Re-export UI test utilities
from .ui_tests import (
    BROWSER_SCRIPTS,
    UI_TEST_SCRIPTS_DOCS,
    UITestConfig,
    build_browser_script_command,
    check_ui_assertions,
    extract_evidence_path,
    get_available_browser_scripts,
    parse_browser_script_output,
    resolve_browser_script,
    validate_ui_test_config,
)

__all__ = [
    "BROWSER_AUTOMATION_SCRIPTS_PATH",
    "BROWSER_SCRIPTS",
    "MAX_OUTPUT_LENGTH",
    "TEST_TOOL_SPECS",
    "TIER_TEST_TYPES",
    "UI_TEST_SCRIPTS_DOCS",
    "ProjectConfig",
    # Base types
    "TestResult",
    "TestToolSpec",
    # UI test utilities
    "UITestConfig",
    "build_browser_script_command",
    "check_ui_assertions",
    "extract_evidence_path",
    "get_available_browser_scripts",
    "parse_browser_script_output",
    "resolve_browser_script",
    "validate_ui_test_config",
]
