"""Table creation modules for database schema.

This package contains modular table definitions organized by functional domain.
"""

from .agent import create_agent_tables
from .core import create_core_tables
from .design import create_design_tables
from .migrations import apply_schema_migrations
from .notifications import create_notifications_tables
from .push_subscriptions import create_push_subscriptions_table

__all__ = [
    "apply_schema_migrations",
    "create_agent_tables",
    "create_core_tables",
    "create_design_tables",
    "create_notifications_tables",
    "create_push_subscriptions_table",
]
