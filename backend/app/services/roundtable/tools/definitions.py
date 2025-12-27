"""Tool definitions for Roundtable agents.

Each tool is defined with a name, description, and input schema.
The TOOL_REGISTRY provides a unified lookup for all tool definitions.
"""

from __future__ import annotations

from typing import Any


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
                    "description": "Directory to search in. Defaults to /home/kasadis/summitflow",
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
                    "description": "Base directory for the search. Defaults to /home/kasadis/summitflow",
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
                    "description": "Project to explore: 'summitflow' or 'portfolio-ai'",
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


def get_write_file_tool() -> dict[str, Any]:
    """Write file tool definition."""
    return {
        "name": "write_file",
        "description": (
            "Create or overwrite a file with the given content. Use this to create "
            "new files or completely replace existing file contents. REQUIRES WRITE "
            "PERMISSION. Will fail if path is outside allowed directories."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Absolute path to the file to write",
                },
                "content": {
                    "type": "string",
                    "description": "Content to write to the file",
                },
            },
            "required": ["file_path", "content"],
        },
    }


def get_edit_file_tool() -> dict[str, Any]:
    """Edit file tool definition."""
    return {
        "name": "edit_file",
        "description": (
            "Make a targeted edit to an existing file by replacing specific text. "
            "Use this for surgical edits without rewriting the entire file. The "
            "old_string must match exactly (including whitespace). REQUIRES WRITE "
            "PERMISSION."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Absolute path to the file to edit",
                },
                "old_string": {
                    "type": "string",
                    "description": "Exact text to replace (must match exactly)",
                },
                "new_string": {
                    "type": "string",
                    "description": "Text to replace it with",
                },
            },
            "required": ["file_path", "old_string", "new_string"],
        },
    }


def get_create_directory_tool() -> dict[str, Any]:
    """Create directory tool definition."""
    return {
        "name": "create_directory",
        "description": (
            "Create a new directory (and parent directories if needed). REQUIRES "
            "WRITE PERMISSION. Will fail if path is outside allowed directories."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute path to the directory to create",
                },
            },
            "required": ["path"],
        },
    }


def get_delete_file_tool() -> dict[str, Any]:
    """Delete file tool definition."""
    return {
        "name": "delete_file",
        "description": (
            "Delete a file. REQUIRES WRITE PERMISSION. Use with caution. Will fail "
            "if file doesn't exist or path is outside allowed directories."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Absolute path to the file to delete",
                },
            },
            "required": ["file_path"],
        },
    }


def get_codebase_metrics_tool() -> dict[str, Any]:
    """Get codebase metrics tool definition."""
    return {
        "name": "get_codebase_metrics",
        "description": (
            "Get summary metrics about the codebase from Explorer. Returns counts "
            "of files, endpoints, pages, tables, and health status breakdown. "
            "Optionally filter by path prefix to analyze a specific directory."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "string",
                    "description": "Project ID (e.g., 'summitflow', 'portfolio-ai')",
                },
                "path": {
                    "type": "string",
                    "description": "Optional path prefix to filter metrics (e.g., 'backend/app')",
                },
            },
            "required": ["project_id"],
        },
    }


def get_find_complex_files_tool() -> dict[str, Any]:
    """Find complex files tool definition."""
    return {
        "name": "find_complex_files",
        "description": (
            "Find files with high complexity scores that may need refactoring. "
            "Returns files sorted by complexity with metrics like line count, "
            "function count, and class count."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "string",
                    "description": "Project ID (e.g., 'summitflow')",
                },
                "threshold": {
                    "type": "number",
                    "description": "Minimum complexity score (default 10)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum files to return (default 20)",
                },
            },
            "required": ["project_id"],
        },
    }


def get_refactor_targets_tool() -> dict[str, Any]:
    """Get refactor targets tool definition."""
    return {
        "name": "get_refactor_targets",
        "description": (
            "Get files that are candidates for refactoring based on complexity "
            "and line count. Returns files with high or medium priority along "
            "with specific reasons for refactoring."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "string",
                    "description": "Project ID (e.g., 'summitflow')",
                },
                "priority": {
                    "type": "string",
                    "enum": ["high", "medium"],
                    "description": "Filter by priority level (default: all)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum targets to return (default 20)",
                },
            },
            "required": ["project_id"],
        },
    }


def get_tdd_suggestions_tool() -> dict[str, Any]:
    """Get TDD suggestions tool definition."""
    return {
        "name": "get_tdd_suggestions",
        "description": (
            "Get suggestions for TDD structure based on codebase analysis. "
            "Returns suggested components, existing tests found, and coverage "
            "summary for endpoints and pages."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "string",
                    "description": "Project ID (e.g., 'summitflow')",
                },
            },
            "required": ["project_id"],
        },
    }


def get_coverage_gaps_tool() -> dict[str, Any]:
    """Get coverage gaps tool definition."""
    return {
        "name": "get_coverage_gaps",
        "description": (
            "Find endpoints, pages, and tables that are not linked to any "
            "capability. These represent gaps in TDD coverage that should "
            "be addressed."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "string",
                    "description": "Project ID (e.g., 'summitflow')",
                },
            },
            "required": ["project_id"],
        },
    }


# Unified tool registry - Single Source of Truth for all tools
TOOL_REGISTRY: dict[str, dict[str, Any]] = {
    # Read-only tools
    "read_file": {
        "getter": get_read_file_tool,
        "category": "read_only",
        "requires_permission": False,
    },
    "search_code": {
        "getter": get_search_code_tool,
        "category": "read_only",
        "requires_permission": False,
    },
    "list_files": {
        "getter": get_list_files_tool,
        "category": "read_only",
        "requires_permission": False,
    },
    "get_project_structure": {
        "getter": get_project_structure_tool,
        "category": "read_only",
        "requires_permission": False,
    },
    # Write tools
    "write_file": {
        "getter": get_write_file_tool,
        "category": "write",
        "requires_permission": True,
    },
    "edit_file": {
        "getter": get_edit_file_tool,
        "category": "write",
        "requires_permission": True,
    },
    "create_directory": {
        "getter": get_create_directory_tool,
        "category": "write",
        "requires_permission": True,
    },
    "delete_file": {
        "getter": get_delete_file_tool,
        "category": "write",
        "requires_permission": True,
    },
    # Explorer tools
    "get_codebase_metrics": {
        "getter": get_codebase_metrics_tool,
        "category": "explorer",
        "requires_permission": False,
    },
    "find_complex_files": {
        "getter": get_find_complex_files_tool,
        "category": "explorer",
        "requires_permission": False,
    },
    "get_refactor_targets": {
        "getter": get_refactor_targets_tool,
        "category": "explorer",
        "requires_permission": False,
    },
    "get_tdd_suggestions": {
        "getter": get_tdd_suggestions_tool,
        "category": "explorer",
        "requires_permission": False,
    },
    "get_coverage_gaps": {
        "getter": get_coverage_gaps_tool,
        "category": "explorer",
        "requires_permission": False,
    },
}


def get_tool_definition(tool_name: str) -> dict[str, Any] | None:
    """Get the full tool definition by name.

    Args:
        tool_name: Name of the tool

    Returns:
        Tool definition dict, or None if not found
    """
    entry = TOOL_REGISTRY.get(tool_name)
    if entry:
        getter = entry["getter"]
        result: dict[str, Any] = getter()
        return result
    return None
