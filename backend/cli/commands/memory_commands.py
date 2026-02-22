"""Command implementations for memory system.

This module delegates to specialized submodules:
- memory_validation.py: Format standard validation
- memory_crud.py: Basic CRUD operations
- memory_batch.py: Batch operations and import/export
"""

from __future__ import annotations

from pathlib import Path

from ..output_context import OutputContext
from .memory_batch import (
    batch_tier_impl,
    cleanup_impl,
    export_impl,
    import_impl,
)
from .memory_crud import (
    delete_impl,
    get_impl,
    list_impl,
    save_impl,
    search_impl,
    stats_impl,
    update_impl,
)
from .memory_seed import seed_impl

# Re-export all implementations for backward compatibility
__all__ = [
    "batch_tier_impl",
    "cleanup_impl",
    "delete_impl",
    "export_impl",
    "get_impl",
    "import_impl",
    "list_impl",
    "save_impl",
    "search_impl",
    "seed_impl",
    "stats_impl",
    "update_impl",
]


# These functions are just thin wrappers for backward compatibility
def stats(out: OutputContext, scope: str, scope_id: str | None) -> None:
    """Get memory statistics."""
    stats_impl(out, scope, scope_id)


def save(
    out: OutputContext,
    content: str,
    summary: str,
    tier: str,
    confidence: int,
    context: str | None,
    pinned: bool,
    trigger_types: str | None,
    scope: str,
    scope_id: str | None,
) -> None:
    """Save a new memory episode."""
    save_impl(
        out, content, summary, tier, confidence, context, pinned, trigger_types, scope, scope_id
    )


def list_episodes(
    out: OutputContext,
    limit: int,
    cursor: str | None,
    tier: str | None,
    scope: str,
    scope_id: str | None,
) -> None:
    """List memory episodes."""
    list_impl(out, limit, cursor, tier, scope, scope_id)


def search(
    out: OutputContext,
    query: str,
    limit: int,
    min_score: float,
    scope: str,
    scope_id: str | None,
) -> None:
    """Search memory episodes."""
    search_impl(out, query, limit, min_score, scope, scope_id)


def get(out: OutputContext, uuids: list[str]) -> None:
    """Get memory episode(s) by UUID."""
    get_impl(out, uuids)


def delete(uuids: list[str]) -> None:
    """Delete memory episode(s)."""
    delete_impl(uuids)


def update(
    uuid: str,
    content: str | None,
    tier: str | None,
    summary: str | None,
    trigger_types: str | None,
    pinned: bool | None,
) -> None:
    """Update a memory episode."""
    update_impl(uuid, content, tier, summary, trigger_types, pinned)


def batch_tier(
    out: OutputContext,
    input_file: Path | None,
    json_input: str | None,
    tier: str | None,
    uuids: list[str] | None,
) -> None:
    """Batch update episode tiers."""
    batch_tier_impl(out, input_file, json_input, tier, uuids)


def export(
    tier: str | None,
    uuids: list[str] | None,
    output: Path | None,
    scope: str,
    scope_id: str | None,
    full: bool = False,
) -> None:
    """Export memory episodes."""
    export_impl(tier, uuids, output, scope, scope_id, full)


def import_episodes(out: OutputContext, input_path: Path, dry_run: bool) -> None:
    """Import memory episodes."""
    import_impl(out, input_path, dry_run)


def cleanup(
    out: OutputContext,
    orphaned: bool,
    stale: bool,
    ttl_days: int,
    scope: str,
    scope_id: str | None,
) -> None:
    """Clean up orphaned or stale episodes."""
    cleanup_impl(out, orphaned, stale, ttl_days, scope, scope_id)
