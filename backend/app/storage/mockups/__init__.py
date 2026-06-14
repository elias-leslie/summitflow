"""Mockups Storage - Database operations for design mockups.

This module handles all database interactions for mockup records:
- CRUD operations for mockups
- Query filtering and pagination
- Approval workflow
- Provenance tracking

Modules:
    core: Constants, ID generation, row mapping, and create operations
    queries: Read operations, filtering, and pagination
    updates: Update operations and status transitions
    history: History tracking and statistics
"""

from .comments import (
    create_mockup_comment,
    delete_mockup_comment,
    list_mockup_comments,
    update_mockup_comment,
)
from .core import (
    MOCKUP_SELECT_COLUMNS,
    MOCKUP_STATUSES,
    MOCKUP_TYPES,
    create_mockup,
    generate_mockup_id,
    get_mockup_by_db_id,
)
from .history import get_mockup_history, get_mockup_stats
from .queries import (
    get_mockup,
    get_mockups_for_page,
    get_mockups_for_task,
    list_mockups,
)
from .updates import (
    archive_mockup,
    delete_mockup,
    set_mockup_rating,
    update_mockup,
    update_mockup_status,
)

__all__ = [
    "MOCKUP_SELECT_COLUMNS",
    "MOCKUP_STATUSES",
    "MOCKUP_TYPES",
    "archive_mockup",
    "create_mockup",
    "create_mockup_comment",
    "delete_mockup",
    "delete_mockup_comment",
    "generate_mockup_id",
    "get_mockup",
    "get_mockup_by_db_id",
    "get_mockup_history",
    "get_mockup_stats",
    "get_mockups_for_page",
    "get_mockups_for_task",
    "list_mockup_comments",
    "list_mockups",
    "set_mockup_rating",
    "update_mockup",
    "update_mockup_comment",
    "update_mockup_status",
]
