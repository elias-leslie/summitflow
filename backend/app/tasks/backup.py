"""Background tasks for backup and restore operations.

Tasks:
- create_backup: Create a new backup for a project
- restore_backup: Restore from a backup archive
- run_scheduled_backups: Check and run due scheduled backups

This module serves as the main entry point and re-exports all backup functionality
to maintain backward compatibility with existing imports.
"""

from __future__ import annotations

# Re-export all public functions from submodules
from .backup_executor import create_backup
from .backup_restore import restore_backup
from .backup_scheduler import run_scheduled_backups

# Re-export internal utilities for testing
from .backup_utils import (
    calculate_next_run as _calculate_next_run,
)
from .backup_utils import (
    parse_backup_output as _parse_backup_output,
)
from .backup_utils import parse_size as _parse_size

__all__ = [
    "_calculate_next_run",
    "_parse_backup_output",
    "_parse_size",
    "create_backup",
    "restore_backup",
    "run_scheduled_backups",
]
