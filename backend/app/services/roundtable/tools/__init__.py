"""Tool definitions and categories for Roundtable agents.

This module provides tool definitions organized by category:
- READ_ONLY_TOOLS: File reading, search, structure exploration
- WRITE_TOOLS: File creation, editing, deletion (require permission)
- EXPLORER_TOOLS: Codebase analysis via Explorer API

Note: Executor components (RoundtableToolExecutor, ToolResult, etc.) are in
the executor module. Import from roundtable package or executor directly.
"""

from .categories import (
    ALL_CATEGORIES,
    EXPLORER_TOOLS,
    READ_ONLY_TOOLS,
    WRITE_TOOLS,
    ToolCategory,
)
from .definitions import (
    TOOL_REGISTRY,
    get_codebase_metrics_tool,
    get_coverage_gaps_tool,
    get_create_directory_tool,
    get_delete_file_tool,
    get_edit_file_tool,
    get_find_complex_files_tool,
    get_list_files_tool,
    get_project_structure_tool,
    get_read_file_tool,
    get_refactor_targets_tool,
    get_search_code_tool,
    get_tdd_suggestions_tool,
    get_tool_definition,
    get_write_file_tool,
)

__all__ = [
    # Categories
    "ALL_CATEGORIES",
    "EXPLORER_TOOLS",
    "READ_ONLY_TOOLS",
    "TOOL_REGISTRY",
    "WRITE_TOOLS",
    "ToolCategory",
    # Individual tool getters
    "get_codebase_metrics_tool",
    "get_coverage_gaps_tool",
    "get_create_directory_tool",
    "get_delete_file_tool",
    "get_edit_file_tool",
    "get_find_complex_files_tool",
    "get_list_files_tool",
    "get_project_structure_tool",
    "get_read_file_tool",
    "get_refactor_targets_tool",
    "get_search_code_tool",
    "get_tdd_suggestions_tool",
    "get_tool_definition",
    "get_write_file_tool",
]
