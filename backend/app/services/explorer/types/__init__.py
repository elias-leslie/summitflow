"""Type registry for Explorer scanners.

Registers scanner classes by entry type. New scanners should be
added here when implemented.

Usage:
    from app.services.explorer.types import get_scanner, SCANNERS

    # Get scanner class for an entry type
    scanner_class = get_scanner("file")
    if scanner_class:
        scanner = scanner_class(project_id)
        result = scanner.run()
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..base import BaseScanner

# Import scanners
from .database import DatabaseScanner
from .files import FileScanner

# Registry of scanner classes by entry type
# Format: {entry_type: ScannerClass}
# Add new scanners here as they are implemented
SCANNERS: dict[str, type["BaseScanner"]] = {
    "file": FileScanner,
    "table": DatabaseScanner,
    # "task": TaskScanner,      # TODO: Phase 2
    # "endpoint": EndpointScanner, # TODO: Phase 2
}


def get_scanner(entry_type: str) -> type["BaseScanner"] | None:
    """Get the scanner class for an entry type.

    Args:
        entry_type: The type of entries to scan ('file', 'table', 'task', 'endpoint')

    Returns:
        Scanner class or None if not registered
    """
    return SCANNERS.get(entry_type)


def register_scanner(entry_type: str, scanner_class: type["BaseScanner"]) -> None:
    """Register a scanner class for an entry type.

    Args:
        entry_type: The type of entries the scanner produces
        scanner_class: The scanner class to register
    """
    SCANNERS[entry_type] = scanner_class


def list_registered_types() -> list[str]:
    """List all registered entry types.

    Returns:
        List of registered entry type names
    """
    return list(SCANNERS.keys())
