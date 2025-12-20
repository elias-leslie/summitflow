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

import fnmatch
import logging
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Maximum file size to read (5MB)
MAX_FILE_SIZE = 5 * 1024 * 1024

# Maximum lines to return from search
MAX_SEARCH_RESULTS = 100

# Allowed base directories for file access
ALLOWED_BASES = [
    "/home/kasadis/summitflow",
    "/home/kasadis/portfolio-ai",
]


# =============================================================================
# Tool Definitions
# =============================================================================


def get_read_file_tool() -> dict[str, Any]:
    """Read file tool definition."""
    return {
        "name": "read_file",
        "description": (
            "Read the contents of a file from the codebase. Use this to examine "
            "source code, configuration files, documentation, or any text file. "
            "Returns the file contents as text. Will fail if the file doesn't exist, "
            "is too large (>5MB), or is outside the allowed project directories."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": (
                        "Absolute path to the file, e.g. "
                        "/home/kasadis/summitflow/backend/app/main.py"
                    ),
                },
            },
            "required": ["file_path"],
        },
    }


def get_search_code_tool() -> dict[str, Any]:
    """Search code tool definition."""
    return {
        "name": "search_code",
        "description": (
            "Search for a pattern in the codebase using ripgrep. Returns matching "
            "lines with file paths and line numbers. Use this to find function "
            "definitions, class declarations, imports, or any text pattern. "
            "Supports regex patterns. Limited to 100 results."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": (
                        "Search pattern (regex supported), e.g. 'def create_feature', "
                        "'class.*Service', 'import.*fastapi'"
                    ),
                },
                "path": {
                    "type": "string",
                    "description": (
                        "Directory to search in. Defaults to /home/kasadis/summitflow"
                    ),
                },
                "file_type": {
                    "type": "string",
                    "description": (
                        "File type filter: 'py', 'ts', 'tsx', 'json', 'sql', 'md'. "
                        "Leave empty for all files."
                    ),
                },
            },
            "required": ["pattern"],
        },
    }


def get_list_files_tool() -> dict[str, Any]:
    """List files tool definition."""
    return {
        "name": "list_files",
        "description": (
            "List files matching a glob pattern in the codebase. Use this to "
            "explore directory structure, find files by name pattern, or get an "
            "overview of a directory. Returns file paths sorted by modification time."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": (
                        "Glob pattern, e.g. '**/*.py', 'backend/app/api/*.py', "
                        "'frontend/components/**/*.tsx'"
                    ),
                },
                "path": {
                    "type": "string",
                    "description": (
                        "Base directory for the search. Defaults to /home/kasadis/summitflow"
                    ),
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of files to return (default 50)",
                },
            },
            "required": ["pattern"],
        },
    }


def get_project_structure_tool() -> dict[str, Any]:
    """Get project structure tool definition."""
    return {
        "name": "get_project_structure",
        "description": (
            "Get an overview of a project's directory structure. Shows directories "
            "and key files (README, config files, etc.) to help understand the "
            "project layout. Useful as a first step before diving into specific files."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "project": {
                    "type": "string",
                    "description": (
                        "Project to explore: 'summitflow' or 'portfolio-ai'"
                    ),
                    "enum": ["summitflow", "portfolio-ai"],
                },
                "depth": {
                    "type": "integer",
                    "description": "Directory depth to show (default 2, max 4)",
                },
            },
            "required": ["project"],
        },
    }


# =============================================================================
# Tool Categories
# =============================================================================


@dataclass
class ToolCategory:
    """Category of tools with access control."""

    name: str
    description: str
    tools: list[dict[str, Any]]
    requires_permission: bool = False


# Default read-only tools (always available)
READ_ONLY_TOOLS = ToolCategory(
    name="read_only",
    description="Read-only access to codebase (files, search, structure)",
    tools=[
        get_read_file_tool(),
        get_search_code_tool(),
        get_list_files_tool(),
        get_project_structure_tool(),
    ],
    requires_permission=False,
)

# Future: Additional tool categories that require permission
# WRITE_TOOLS = ToolCategory(...)
# EXECUTE_TOOLS = ToolCategory(...)


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

    def get_available_tools(self) -> list[dict[str, Any]]:
        """Get all available tool definitions based on enabled categories."""
        tools = []
        if "read_only" in self.enabled_categories:
            tools.extend(READ_ONLY_TOOLS.tools)
        # Future: Add more categories here
        return tools

    def execute(self, tool_name: str, parameters: dict[str, Any]) -> ToolResult:
        """Execute a tool with the given parameters.

        Args:
            tool_name: Name of the tool to execute
            parameters: Tool parameters

        Returns:
            ToolResult with output or error
        """
        executors = {
            "read_file": self._execute_read_file,
            "search_code": self._execute_search_code,
            "list_files": self._execute_list_files,
            "get_project_structure": self._execute_get_project_structure,
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

    def _validate_path(self, path: str, default_base: str | None = None) -> tuple[bool, str]:
        """Validate that a path is within allowed directories.

        Handles both absolute and relative paths. Relative paths are resolved
        against the default_base (typically /home/kasadis/summitflow).

        Returns:
            (is_valid, resolved_path or error_message)
        """
        try:
            path_obj = Path(path)

            # If relative path, try to resolve against allowed bases
            if not path_obj.is_absolute():
                # Try default base first
                if default_base:
                    candidate = Path(default_base) / path
                    if candidate.exists():
                        path_obj = candidate
                    else:
                        # Try other allowed bases
                        for base in ALLOWED_BASES:
                            candidate = Path(base) / path
                            if candidate.exists():
                                path_obj = candidate
                                break
                else:
                    # Try all allowed bases
                    for base in ALLOWED_BASES:
                        candidate = Path(base) / path
                        if candidate.exists():
                            path_obj = candidate
                            break

            # Resolve to absolute path
            resolved = path_obj.resolve()
            resolved_str = str(resolved)

            # Check against allowed bases
            all_allowed = ALLOWED_BASES + self.allowed_paths
            for base in all_allowed:
                if resolved_str.startswith(base):
                    return True, resolved_str

            return False, f"Path not in allowed directories: {path}"
        except Exception as e:
            return False, f"Invalid path: {e}"

    def _execute_read_file(self, params: dict[str, Any]) -> ToolResult:
        """Execute read_file tool."""
        file_path = params.get("file_path", "")
        if not file_path:
            return ToolResult(False, "", "file_path is required")

        # Validate path
        is_valid, result = self._validate_path(file_path)
        if not is_valid:
            return ToolResult(False, "", result)

        path = Path(result)

        # Check file exists
        if not path.exists():
            return ToolResult(False, "", f"File not found: {file_path}")

        if not path.is_file():
            return ToolResult(False, "", f"Not a file: {file_path}")

        # Check file size
        size = path.stat().st_size
        if size > MAX_FILE_SIZE:
            return ToolResult(
                False, "", f"File too large: {size} bytes (max {MAX_FILE_SIZE})"
            )

        # Read file
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
            return ToolResult(True, content)
        except Exception as e:
            return ToolResult(False, "", f"Failed to read file: {e}")

    def _execute_search_code(self, params: dict[str, Any]) -> ToolResult:
        """Execute search_code tool using ripgrep."""
        pattern = params.get("pattern", "")
        if not pattern:
            return ToolResult(False, "", "pattern is required")

        search_path = params.get("path", "/home/kasadis/summitflow")
        file_type = params.get("file_type", "")

        # Validate path (handles relative paths)
        is_valid, result = self._validate_path(
            search_path, default_base="/home/kasadis/summitflow"
        )
        if not is_valid:
            return ToolResult(False, "", result)

        # Build grep command (more universally available than ripgrep)
        # Use grep -r for recursive, -n for line numbers, -E for extended regex
        cmd = ["grep", "-r", "-n", "-E", "--include=*"]

        # Add file type filter
        if file_type:
            type_map = {
                "py": "*.py",
                "ts": "*.ts",
                "tsx": "*.tsx",
                "js": "*.js",
                "jsx": "*.jsx",
                "json": "*.json",
                "sql": "*.sql",
                "md": "*.md",
            }
            glob_pattern = type_map.get(file_type, f"*.{file_type}")
            cmd = ["grep", "-r", "-n", "-E", f"--include={glob_pattern}"]

        cmd.extend([pattern, result])

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
            )

            # grep returns 1 for no matches, 0 for matches
            if proc.returncode == 1 and not proc.stdout:
                return ToolResult(True, "No matches found")

            if proc.returncode not in (0, 1):
                return ToolResult(False, "", f"Search failed: {proc.stderr}")

            # Limit output
            lines = proc.stdout.strip().split("\n")
            if len(lines) > MAX_SEARCH_RESULTS:
                output = "\n".join(lines[:MAX_SEARCH_RESULTS])
                output += f"\n... ({len(lines) - MAX_SEARCH_RESULTS} more results)"
            else:
                output = proc.stdout.strip()

            return ToolResult(True, output or "No matches found")
        except subprocess.TimeoutExpired:
            return ToolResult(False, "", "Search timed out")
        except Exception as e:
            return ToolResult(False, "", f"Search failed: {e}")

    def _execute_list_files(self, params: dict[str, Any]) -> ToolResult:
        """Execute list_files tool using glob."""
        pattern = params.get("pattern", "")
        if not pattern:
            return ToolResult(False, "", "pattern is required")

        base_path = params.get("path", "/home/kasadis/summitflow")
        limit = min(params.get("limit", 50), 200)  # Max 200 files

        # Validate path (handles relative paths)
        is_valid, result = self._validate_path(
            base_path, default_base="/home/kasadis/summitflow"
        )
        if not is_valid:
            return ToolResult(False, "", result)

        base = Path(result)

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

        project_paths = {
            "summitflow": "/home/kasadis/summitflow",
            "portfolio-ai": "/home/kasadis/portfolio-ai",
        }

        base_path = project_paths.get(project)
        if not base_path:
            return ToolResult(False, "", f"Unknown project: {project}")

        # Validate path
        is_valid, result = self._validate_path(base_path)
        if not is_valid:
            return ToolResult(False, "", result)

        base = Path(result)

        try:
            # Build tree structure
            output_lines = [f"{project}/"]

            def add_dir(path: Path, prefix: str, current_depth: int) -> None:
                if current_depth > depth:
                    return

                try:
                    items = sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name))
                except PermissionError:
                    return

                # Filter out hidden and common ignore patterns
                ignore_patterns = {
                    ".git",
                    ".venv",
                    "node_modules",
                    "__pycache__",
                    ".next",
                    ".pytest_cache",
                    "dist",
                    "build",
                    ".mypy_cache",
                }

                items = [i for i in items if i.name not in ignore_patterns]

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

            return ToolResult(True, "\n".join(output_lines))
        except Exception as e:
            return ToolResult(False, "", f"Failed to get structure: {e}")


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
