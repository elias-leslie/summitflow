"""Tool categories for Roundtable agents.

Categories group tools by access level:
- read_only: Always available (file reading, search, structure)
- write: Require explicit permission (create, edit, delete)
- explorer: Codebase analysis via Explorer API
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .definitions import (
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
    get_write_file_tool,
)


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

# Write tools (require explicit permission)
WRITE_TOOLS = ToolCategory(
    name="write",
    description="Write access to codebase (create, edit, delete files)",
    tools=[
        get_write_file_tool(),
        get_edit_file_tool(),
        get_create_directory_tool(),
        get_delete_file_tool(),
    ],
    requires_permission=True,
)

# Explorer tools (codebase analysis via Explorer API)
EXPLORER_TOOLS = ToolCategory(
    name="explorer",
    description="Codebase analysis tools via Explorer (metrics, complexity, coverage)",
    tools=[
        get_codebase_metrics_tool(),
        get_find_complex_files_tool(),
        get_refactor_targets_tool(),
        get_tdd_suggestions_tool(),
        get_coverage_gaps_tool(),
    ],
    requires_permission=False,
)

# All tool categories
ALL_CATEGORIES = {
    "read_only": READ_ONLY_TOOLS,
    "write": WRITE_TOOLS,
    "explorer": EXPLORER_TOOLS,
}
