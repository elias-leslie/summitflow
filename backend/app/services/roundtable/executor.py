"""Tool definitions and executor for Roundtable agents.

Provides read-only codebase access by default, with the ability to grant
additional tools dynamically.

Tools:
- read_file: Read file contents
- search_code: Search for patterns in code (grep)
- list_files: List files matching a pattern (glob)
- get_project_structure: Get project directory overview
"""

from __future__ import annotations

import json
import logging
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..explorer.constants import SKIP_DIRS
from .tools.categories import (
    EXPLORER_TOOLS,
    READ_ONLY_TOOLS,
    WRITE_TOOLS,
)
from .validation import (
    get_allowed_bases,
    require_param,
    require_valid_path,
    validate_file_exists,
)


def get_default_project_path() -> str:
    """Get default project path (first allowed base)."""
    bases = get_allowed_bases()
    if not bases:
        raise RuntimeError("No projects registered in database")
    return bases[0]


logger = logging.getLogger(__name__)

# Maximum file size to read (5MB)
MAX_FILE_SIZE = 5 * 1024 * 1024

# Maximum lines to return from search
MAX_SEARCH_RESULTS = 100

# File type to glob pattern mapping for code search
FILE_TYPE_MAP: dict[str, str] = {
    "py": "*.py",
    "ts": "*.ts",
    "tsx": "*.tsx",
    "js": "*.js",
    "jsx": "*.jsx",
    "json": "*.json",
    "sql": "*.sql",
    "md": "*.md",
}


# =============================================================================
# Search Helpers
# =============================================================================


def _build_grep_command(pattern: str, search_path: str, file_type: str = "") -> list[str]:
    """Build grep command with appropriate flags.

    Args:
        pattern: Search pattern (regex)
        search_path: Path to search in
        file_type: Optional file type filter (py, ts, etc.)

    Returns:
        Command list for subprocess.run()
    """
    # Use grep -r for recursive, -n for line numbers, -E for extended regex
    if file_type:
        glob_pattern = FILE_TYPE_MAP.get(file_type, f"*.{file_type}")
        cmd = ["grep", "-r", "-n", "-E", f"--include={glob_pattern}"]
    else:
        cmd = ["grep", "-r", "-n", "-E", "--include=*"]
    cmd.extend([pattern, search_path])
    return cmd


def _limit_search_results(output: str, max_results: int = MAX_SEARCH_RESULTS) -> str:
    """Limit search results to max lines.

    Args:
        output: Raw output string
        max_results: Maximum lines to include

    Returns:
        Truncated output with count of omitted lines.
    """
    if not output.strip():
        return "No matches found"

    lines = output.strip().split("\n")
    if len(lines) > max_results:
        result = "\n".join(lines[:max_results])
        result += f"\n... ({len(lines) - max_results} more results)"
        return result
    return output.strip()


# =============================================================================
# Tree Rendering Helpers
# =============================================================================


def _should_ignore_item(name: str) -> bool:
    """Check if an item should be ignored in directory tree."""
    return name in SKIP_DIRS


def _build_directory_tree(base: Path, max_depth: int) -> list[str]:
    """Build a directory tree representation.

    Args:
        base: Base directory path
        max_depth: Maximum depth to traverse

    Returns:
        List of formatted tree lines.
    """
    output_lines: list[str] = []

    def add_dir(path: Path, prefix: str, current_depth: int) -> None:
        if current_depth > max_depth:
            return

        try:
            items = sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name))
        except PermissionError:
            return

        # Filter ignored items
        items = [i for i in items if not _should_ignore_item(i.name)]

        for i, item in enumerate(items):
            is_last = i == len(items) - 1
            connector = "└── " if is_last else "├── "
            child_prefix = "    " if is_last else "│   "

            if item.is_dir():
                output_lines.append(f"{prefix}{connector}{item.name}/")
                add_dir(item, prefix + child_prefix, current_depth + 1)
            else:
                output_lines.append(f"{prefix}{connector}{item.name}")

    add_dir(base, "", 1)
    return output_lines


# =============================================================================
# Tool Executor
# =============================================================================


@dataclass
class ToolResult:
    """Result from tool execution."""

    success: bool
    output: str
    error: str | None = None


@dataclass
class RoundtableToolExecutor:
    """Executes tools for Roundtable agents with security controls.

    Default: read-only access to codebase
    Can be extended with additional permissions per session.
    """

    # Active tool categories
    enabled_categories: list[str] = field(default_factory=lambda: ["read_only"])

    # Custom allowed paths (in addition to defaults)
    allowed_paths: list[str] = field(default_factory=list)

    # YOLO mode - auto-approve all permission requests
    yolo_mode: bool = False

    def get_available_tools(self) -> list[dict[str, Any]]:
        """Get all available tool definitions based on enabled categories."""
        tools = []
        if "read_only" in self.enabled_categories:
            tools.extend(READ_ONLY_TOOLS.tools)
        if "write" in self.enabled_categories:
            tools.extend(WRITE_TOOLS.tools)
        if "explorer" in self.enabled_categories:
            tools.extend(EXPLORER_TOOLS.tools)
        return tools

    def has_write_access(self) -> bool:
        """Check if write access is enabled."""
        return "write" in self.enabled_categories

    def enable_write_access(self) -> None:
        """Enable write access tools."""
        if "write" not in self.enabled_categories:
            self.enabled_categories.append("write")

    def disable_write_access(self) -> None:
        """Disable write access tools."""
        if "write" in self.enabled_categories:
            self.enabled_categories.remove("write")

    def execute(self, tool_name: str, parameters: dict[str, Any]) -> ToolResult:
        """Execute a tool with the given parameters.

        Args:
            tool_name: Name of the tool to execute
            parameters: Tool parameters

        Returns:
            ToolResult with output or error
        """
        # Check if tool requires write access
        if tool_name in WRITE_TOOL_NAMES and not self.has_write_access():
            return ToolResult(
                success=False,
                output="",
                error=f"Tool '{tool_name}' requires write access. Enable write access to use this tool.",
            )

        executors = {
            "read_file": self._execute_read_file,
            "search_code": self._execute_search_code,
            "list_files": self._execute_list_files,
            "get_project_structure": self._execute_get_project_structure,
            "write_file": self._execute_write_file,
            "edit_file": self._execute_edit_file,
            "create_directory": self._execute_create_directory,
            "delete_file": self._execute_delete_file,
            # Explorer tools
            "get_codebase_metrics": self._execute_get_codebase_metrics,
            "find_complex_files": self._execute_find_complex_files,
            "get_refactor_targets": self._execute_get_refactor_targets,
            "get_tdd_suggestions": self._execute_get_tdd_suggestions,
            "get_coverage_gaps": self._execute_get_coverage_gaps,
        }

        executor = executors.get(tool_name)
        if not executor:
            return ToolResult(
                success=False,
                output="",
                error=f"Unknown tool: {tool_name}",
            )

        try:
            return executor(parameters)
        except Exception as e:
            logger.error(f"Tool execution error: {tool_name} - {e}")
            return ToolResult(
                success=False,
                output="",
                error=f"Tool execution failed: {e}",
            )

    def _require_valid_path(
        self, path: str, default_base: str | None = None
    ) -> tuple[Path, ToolResult | None]:
        """Validate path and return Path object or error ToolResult.

        Wrapper around validation.require_valid_path that converts to ToolResult.

        Usage:
            path, err = self._require_valid_path(file_path)
            if err:
                return err
        """
        path_obj, error = require_valid_path(path, default_base, self.allowed_paths)
        if error:
            return Path(""), ToolResult(False, "", error)
        return path_obj, None  # type: ignore[return-value]

    def _require_param(self, params: dict[str, Any], key: str) -> tuple[str, ToolResult | None]:
        """Extract required parameter, returning ToolResult on error.

        Wrapper around validation.require_param that converts to ToolResult.
        """
        value, error = require_param(params, key)
        if error:
            return "", ToolResult(False, "", error)
        return value, None

    def _validate_file_exists(
        self, path: Path, file_path: str, *, is_dir_error: str | None = None
    ) -> ToolResult | None:
        """Validate file exists, returning ToolResult on error.

        Wrapper around validation.validate_file_exists that converts to ToolResult.
        """
        error = validate_file_exists(path, file_path, is_dir_error=is_dir_error)
        if error:
            return ToolResult(False, "", error)
        return None

    def _execute_read_file(self, params: dict[str, Any]) -> ToolResult:
        """Execute read_file tool."""
        file_path, err = self._require_param(params, "file_path")
        if err:
            return err

        # Validate path
        path, err = self._require_valid_path(file_path)
        if err:
            return err

        # Check file exists
        if err := self._validate_file_exists(path, file_path):
            return err

        # Check file size
        size = path.stat().st_size
        if size > MAX_FILE_SIZE:
            return ToolResult(False, "", f"File too large: {size} bytes (max {MAX_FILE_SIZE})")

        # Read file
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
            return ToolResult(True, content)
        except Exception as e:
            return ToolResult(False, "", f"Failed to read file: {e}")

    def _execute_search_code(self, params: dict[str, Any]) -> ToolResult:
        """Execute search_code tool using grep."""
        pattern, err = self._require_param(params, "pattern")
        if err:
            return err

        search_path = params.get("path", get_default_project_path())
        file_type = params.get("file_type", "")

        # Validate path (handles relative paths)
        path, err = self._require_valid_path(search_path, default_base=get_default_project_path())
        if err:
            return err

        cmd = _build_grep_command(pattern, str(path), file_type)

        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

            # grep returns 1 for no matches, 0 for matches
            if proc.returncode == 1 and not proc.stdout:
                return ToolResult(True, "No matches found")

            if proc.returncode not in (0, 1):
                return ToolResult(False, "", f"Search failed: {proc.stderr}")

            return ToolResult(True, _limit_search_results(proc.stdout))
        except subprocess.TimeoutExpired:
            return ToolResult(False, "", "Search timed out")
        except Exception as e:
            return ToolResult(False, "", f"Search failed: {e}")

    def _execute_list_files(self, params: dict[str, Any]) -> ToolResult:
        """Execute list_files tool using glob."""
        pattern, err = self._require_param(params, "pattern")
        if err:
            return err

        base_path = params.get("path", get_default_project_path())
        limit = min(params.get("limit", 50), 200)  # Max 200 files

        # Validate path (handles relative paths)
        base, err = self._require_valid_path(base_path, default_base=get_default_project_path())
        if err:
            return err

        try:
            # Use glob to find files
            matches = list(base.glob(pattern))

            # Sort by modification time (newest first)
            matches.sort(key=lambda p: p.stat().st_mtime, reverse=True)

            # Limit results
            matches = matches[:limit]

            # Format output
            output_lines = []
            for match in matches:
                rel_path = match.relative_to(base)
                if match.is_dir():
                    output_lines.append(f"{rel_path}/")
                else:
                    size = match.stat().st_size
                    output_lines.append(f"{rel_path} ({size} bytes)")

            if not output_lines:
                return ToolResult(True, "No files found matching pattern")

            return ToolResult(True, "\n".join(output_lines))
        except Exception as e:
            return ToolResult(False, "", f"List failed: {e}")

    def _execute_get_project_structure(self, params: dict[str, Any]) -> ToolResult:
        """Execute get_project_structure tool."""
        project = params.get("project", "summitflow")
        depth = min(params.get("depth", 2), 4)

        # Build project paths from allowed bases (project name = directory name)
        project_paths = {Path(p).name: p for p in get_allowed_bases()}

        base_path = project_paths.get(project)
        if not base_path:
            return ToolResult(False, "", f"Unknown project: {project}")

        # Validate path
        base, err = self._require_valid_path(base_path)
        if err:
            return err

        try:
            output_lines = [f"{project}/"]
            output_lines.extend(_build_directory_tree(base, depth))
            return ToolResult(True, "\n".join(output_lines))
        except Exception as e:
            return ToolResult(False, "", f"Failed to get structure: {e}")

    # =========================================================================
    # Write Tool Executors
    # =========================================================================

    def _execute_write_file(self, params: dict[str, Any]) -> ToolResult:
        """Execute write_file tool."""
        file_path, err = self._require_param(params, "file_path")
        if err:
            return err
        content = params.get("content", "")

        # Validate path
        path, err = self._require_valid_path(file_path)
        if err:
            return err

        try:
            # Create parent directories if needed
            path.parent.mkdir(parents=True, exist_ok=True)

            # Write file
            path.write_text(content, encoding="utf-8")

            return ToolResult(
                True,
                f"Successfully wrote {len(content)} bytes to {file_path}",
            )
        except Exception as e:
            return ToolResult(False, "", f"Failed to write file: {e}")

    def _execute_edit_file(self, params: dict[str, Any]) -> ToolResult:
        """Execute edit_file tool."""
        file_path, err = self._require_param(params, "file_path")
        if err:
            return err
        old_string, err = self._require_param(params, "old_string")
        if err:
            return err
        new_string = params.get("new_string", "")

        # Validate path
        path, err = self._require_valid_path(file_path)
        if err:
            return err

        if err := self._validate_file_exists(path, file_path):
            return err

        try:
            # Read current content
            content = path.read_text(encoding="utf-8")

            # Check if old_string exists
            if old_string not in content:
                return ToolResult(
                    False,
                    "",
                    "old_string not found in file. Make sure it matches exactly.",
                )

            # Count occurrences
            count = content.count(old_string)
            if count > 1:
                return ToolResult(
                    False,
                    "",
                    f"old_string found {count} times. It must be unique for safe replacement.",
                )

            # Replace
            new_content = content.replace(old_string, new_string, 1)
            path.write_text(new_content, encoding="utf-8")

            return ToolResult(
                True,
                f"Successfully edited {file_path}",
            )
        except Exception as e:
            return ToolResult(False, "", f"Failed to edit file: {e}")

    def _execute_create_directory(self, params: dict[str, Any]) -> ToolResult:
        """Execute create_directory tool."""
        dir_path, err = self._require_param(params, "path")
        if err:
            return err

        # Validate path
        path, err = self._require_valid_path(dir_path)
        if err:
            return err

        try:
            path.mkdir(parents=True, exist_ok=True)
            return ToolResult(True, f"Successfully created directory: {dir_path}")
        except Exception as e:
            return ToolResult(False, "", f"Failed to create directory: {e}")

    def _execute_delete_file(self, params: dict[str, Any]) -> ToolResult:
        """Execute delete_file tool."""
        file_path, err = self._require_param(params, "file_path")
        if err:
            return err

        # Validate path
        path, err = self._require_valid_path(file_path)
        if err:
            return err

        if err := self._validate_file_exists(
            path, file_path, is_dir_error="Not a file (use rmdir for directories)"
        ):
            return err

        try:
            path.unlink()
            return ToolResult(True, f"Successfully deleted: {file_path}")
        except Exception as e:
            return ToolResult(False, "", f"Failed to delete file: {e}")

    # =========================================================================
    # Explorer Tool Executors
    # =========================================================================

    def _execute_explorer_tool(
        self,
        params: dict[str, Any],
        executor_fn: Callable[[str, dict[str, Any]], Any],
        error_msg: str,
    ) -> ToolResult:
        """Generic executor for explorer-backed tools.

        Args:
            params: Tool parameters (must include project_id)
            executor_fn: Function to call with (project_id, params)
            error_msg: Error message prefix on failure

        Returns:
            ToolResult with JSON-serialized result or error
        """
        project_id, err = self._require_param(params, "project_id")
        if err:
            return err

        try:
            result = executor_fn(project_id, params)
            return ToolResult(True, json.dumps(result, indent=2, default=str))
        except Exception as e:
            return ToolResult(False, "", f"{error_msg}: {e}")

    def _execute_get_codebase_metrics(self, params: dict[str, Any]) -> ToolResult:
        """Execute get_codebase_metrics tool."""

        def get_metrics(project_id: str, params: dict[str, Any]) -> dict[str, Any]:
            from ...services import explorer as explorer_service

            stats = explorer_service.get_stats(project_id)
            path_filter = params.get("path")
            if path_filter:
                from ...storage import explorer as explorer_storage

                entries = explorer_storage.get_entries(
                    project_id, {"path": path_filter, "limit": 10000}
                )
                stats["filtered_count"] = len(entries)
                stats["filter_path"] = path_filter
            return stats

        return self._execute_explorer_tool(params, get_metrics, "Failed to get metrics")

    def _execute_find_complex_files(self, params: dict[str, Any]) -> ToolResult:
        """Execute find_complex_files tool."""

        def find_complex(project_id: str, params: dict[str, Any]) -> dict[str, Any]:
            from ...storage import explorer as explorer_storage

            threshold = float(params.get("threshold", 10))
            limit = int(params.get("limit", 20))
            return explorer_storage.get_refactor_targets(
                project_id, min_complexity=threshold, limit=limit
            )

        return self._execute_explorer_tool(params, find_complex, "Failed to find complex files")

    def _execute_get_refactor_targets(self, params: dict[str, Any]) -> ToolResult:
        """Execute get_refactor_targets tool."""

        def get_targets(project_id: str, params: dict[str, Any]) -> dict[str, Any]:
            from ...storage import explorer as explorer_storage

            priority = params.get("priority")
            limit = int(params.get("limit", 20))
            return explorer_storage.get_refactor_targets(project_id, priority=priority, limit=limit)

        return self._execute_explorer_tool(params, get_targets, "Failed to get refactor targets")

    def _execute_get_tdd_suggestions(self, params: dict[str, Any]) -> ToolResult:
        """Execute get_tdd_suggestions tool."""

        def get_suggestions(project_id: str, _params: dict[str, Any]) -> dict[str, Any]:
            from ...services import tdd_suggestions

            return tdd_suggestions.get_tdd_suggestions(project_id)

        return self._execute_explorer_tool(params, get_suggestions, "Failed to get TDD suggestions")

    def _execute_get_coverage_gaps(self, params: dict[str, Any]) -> ToolResult:
        """Execute get_coverage_gaps tool."""

        def get_gaps(project_id: str, _params: dict[str, Any]) -> dict[str, Any]:
            from ...storage import explorer as explorer_storage

            gaps = explorer_storage.get_coverage_gaps(project_id)
            return {"gaps": gaps, "count": len(gaps)}

        return self._execute_explorer_tool(params, get_gaps, "Failed to get coverage gaps")


# =============================================================================
# Helper Functions
# =============================================================================


def get_default_executor() -> RoundtableToolExecutor:
    """Get a default tool executor with read-only access."""
    return RoundtableToolExecutor()


def format_tool_results_for_prompt(results: list[tuple[str, ToolResult]]) -> str:
    """Format tool results for inclusion in the next prompt.

    Args:
        results: List of (tool_name, ToolResult) tuples

    Returns:
        Formatted string for the prompt
    """
    parts = []
    for tool_name, result in results:
        if result.success:
            parts.append(f"=== {tool_name} result ===\n{result.output}")
        else:
            parts.append(f"=== {tool_name} ERROR ===\n{result.error}")

    return "\n\n".join(parts)


# =============================================================================
# SDK Format Converters
# =============================================================================

# Tool name sets for permission handling
READ_TOOL_NAMES = {"read_file", "search_code", "list_files", "get_project_structure"}
WRITE_TOOL_NAMES = {"write_file", "edit_file", "delete_file", "create_directory"}
EXPLORER_TOOL_NAMES = {
    "get_codebase_metrics",
    "find_complex_files",
    "get_refactor_targets",
    "get_tdd_suggestions",
    "get_coverage_gaps",
}


def get_tool_description(tool_name: str) -> str:
    """Get the description for a tool by name.

    Args:
        tool_name: Name of the tool

    Returns:
        Tool description string, or empty string if not found
    """
    from .tools.definitions import get_tool_definition

    tool_def = get_tool_definition(tool_name)
    if tool_def:
        desc = tool_def.get("description", "")
        return str(desc) if desc else ""
    return ""


def to_claude_sdk_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert tools to Claude SDK format.

    Claude SDK uses the same format as Anthropic API, so this is mostly
    a pass-through, but validates the structure.

    Args:
        tools: Tool definitions with name, description, input_schema

    Returns:
        Tools in Claude SDK format (same structure)
    """
    return [
        {
            "name": tool["name"],
            "description": tool.get("description", ""),
            "input_schema": tool.get("input_schema", {"type": "object", "properties": {}}),
        }
        for tool in tools
    ]


def create_tool_function(
    tool_name: str,
    executor: RoundtableToolExecutor,
) -> Callable[..., dict[str, Any]]:
    """Create an executable function for a tool.

    Creates a callable that wraps RoundtableToolExecutor.execute() with
    proper __name__ and __doc__ for ADK FunctionTool.

    Args:
        tool_name: Name of the tool
        executor: Tool executor instance

    Returns:
        Callable that executes the tool and returns result dict
    """

    def tool_fn(**kwargs: Any) -> dict[str, Any]:
        result = executor.execute(tool_name, kwargs)
        return {
            "success": result.success,
            "output": result.output,
            "error": result.error,
        }

    # Set proper function metadata for ADK
    tool_fn.__name__ = tool_name
    tool_fn.__doc__ = get_tool_description(tool_name)

    return tool_fn


def to_adk_function_tools(
    tools: list[dict[str, Any]],
    executor: RoundtableToolExecutor,
) -> list[Callable[..., dict[str, Any]]]:
    """Convert tools to Google ADK function format.

    Creates callable functions from tool definitions that can be passed
    to LlmAgent.tools parameter.

    Args:
        tools: Tool definitions with name, description, input_schema
        executor: Tool executor to run the tools

    Returns:
        List of callable functions with proper __name__ and __doc__

    Note:
        ADK can use raw functions directly - it wraps them internally.
        We don't need to use FunctionTool explicitly.
    """
    return [create_tool_function(tool["name"], executor) for tool in tools]
