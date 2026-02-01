"""Memory commands for the CLI - interact with Agent Hub memory system."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from .memory_commands import (
    batch_tier_impl,
    cleanup_impl,
    delete_impl,
    export_impl,
    get_impl,
    import_impl,
    list_impl,
    save_impl,
    search_impl,
    stats_impl,
    update_impl,
)

app = typer.Typer(help="Memory system commands (Agent Hub)")


@app.callback(invoke_without_command=True)
def memory_default(ctx: typer.Context) -> None:
    """Show memory stats (default command)."""
    if ctx.invoked_subcommand is None:
        stats(ctx)


@app.command()
def stats(
    ctx: typer.Context,
    scope: Annotated[
        str,
        typer.Option("--scope", "-s", help="Memory scope (global or project)"),
    ] = "global",
    scope_id: Annotated[
        str | None,
        typer.Option("--scope-id", help="Scope identifier (e.g., project ID)"),
    ] = None,
) -> None:
    """Get memory statistics."""
    stats_impl(ctx.obj, scope, scope_id)


@app.command()
def save(
    ctx: typer.Context,
    content: Annotated[str, typer.Argument(help="Learning content to save")],
    summary: Annotated[
        str,
        typer.Option(
            "--summary", "-S", help="REQUIRED: Short action phrase (~35 chars) for TOON index"
        ),
    ],
    tier: Annotated[
        str,
        typer.Option("--tier", "-t", help="Injection tier (mandate, guardrail, reference)"),
    ] = "reference",
    confidence: Annotated[
        int,
        typer.Option("--confidence", "-c", help="Confidence level 0-100"),
    ] = 80,
    context: Annotated[
        str | None,
        typer.Option("--context", help="Optional context about the learning source"),
    ] = None,
    pinned: Annotated[
        bool,
        typer.Option("--pinned", "-p", help="Pin episode (always inject regardless of budget)"),
    ] = False,
    trigger_types: Annotated[
        str | None,
        typer.Option(
            "--trigger-types", "-T", help="Comma-separated task types (e.g., database,memory)"
        ),
    ] = None,
    scope: Annotated[
        str,
        typer.Option("--scope", "-s", help="Memory scope (global or project)"),
    ] = "global",
    scope_id: Annotated[
        str | None,
        typer.Option("--scope-id", help="Scope identifier (e.g., project ID)"),
    ] = None,
) -> None:
    """Save a learning to the memory system."""
    save_impl(
        ctx.obj, content, summary, tier, confidence, context, pinned, trigger_types, scope, scope_id
    )


@app.command("list")
def list_cmd(
    ctx: typer.Context,
    limit: Annotated[
        int,
        typer.Option("--limit", "-l", help="Max episodes to return (1-300)"),
    ] = 50,
    cursor: Annotated[
        str | None,
        typer.Option("--cursor", help="Pagination cursor from previous response"),
    ] = None,
    tier: Annotated[
        str | None,
        typer.Option("--tier", "-t", help="Filter by tier (mandate, guardrail, reference)"),
    ] = None,
    scope: Annotated[
        str,
        typer.Option("--scope", "-s", help="Memory scope (global or project)"),
    ] = "global",
    scope_id: Annotated[
        str | None,
        typer.Option("--scope-id", help="Scope identifier (e.g., project ID)"),
    ] = None,
) -> None:
    """List memory episodes with pagination."""
    list_impl(ctx.obj, limit, cursor, tier, scope, scope_id)


@app.command()
def search(
    ctx: typer.Context,
    query: Annotated[str, typer.Argument(help="Search query")],
    limit: Annotated[
        int,
        typer.Option("--limit", "-l", help="Max results (1-300)"),
    ] = 10,
    min_score: Annotated[
        float,
        typer.Option("--min-score", help="Minimum relevance score (0.0-1.0)"),
    ] = 0.0,
    scope: Annotated[
        str,
        typer.Option("--scope", "-s", help="Memory scope (global or project)"),
    ] = "global",
    scope_id: Annotated[
        str | None,
        typer.Option("--scope-id", help="Scope identifier (e.g., project ID)"),
    ] = None,
) -> None:
    """Search memory for relevant episodes."""
    search_impl(ctx.obj, query, limit, min_score, scope, scope_id)


@app.command()
def get(
    ctx: typer.Context,
    uuids: Annotated[list[str], typer.Argument(help="Episode UUID(s) to retrieve")],
) -> None:
    """Get details for one or more episodes by UUID."""
    get_impl(ctx.obj, uuids)


@app.command()
def delete(
    uuids: Annotated[list[str], typer.Argument(help="Episode UUID(s) to delete")],
    confirm: Annotated[
        bool,
        typer.Option("--confirm", help="Require confirmation prompt (default: no confirmation)"),
    ] = False,
) -> None:
    """Delete one or more episodes from memory."""
    delete_impl(uuids, confirm)


@app.command()
def update(
    uuid: Annotated[str, typer.Argument(help="Episode UUID to update")],
    content: Annotated[
        str | None,
        typer.Option("--content", "-c", help="New content for the episode"),
    ] = None,
    tier: Annotated[
        str | None,
        typer.Option("--tier", "-t", help="New tier (mandate/guardrail/reference)"),
    ] = None,
    summary: Annotated[
        str | None,
        typer.Option("--summary", "-S", help="Update summary (~35 chars for TOON index)"),
    ] = None,
    trigger_types: Annotated[
        str | None,
        typer.Option(
            "--trigger-types", help="Comma-separated task types (backend,frontend,database,etc.)"
        ),
    ] = None,
    pinned: Annotated[
        bool | None,
        typer.Option(
            "--pinned/--no-pinned", help="Pin episode (always inject regardless of budget)"
        ),
    ] = None,
    confirm: Annotated[
        bool,
        typer.Option("--confirm", help="Require confirmation prompt (default: no confirmation)"),
    ] = False,
) -> None:
    """Update an episode (delete + recreate for content/tier, PATCH for properties)."""
    update_impl(uuid, content, tier, summary, trigger_types, pinned, confirm)


@app.command("batch-tier")
def batch_tier(
    ctx: typer.Context,
    input_file: Annotated[
        Path | None,
        typer.Option("--file", "-f", help="JSON file with updates [{uuid, tier}]"),
    ] = None,
    json_input: Annotated[
        str | None,
        typer.Option("--json", "-j", help="JSON string with updates"),
    ] = None,
    tier: Annotated[
        str | None,
        typer.Option("--tier", "-t", help="Tier to apply to all UUIDs"),
    ] = None,
    uuids: Annotated[
        list[str] | None,
        typer.Argument(help="UUIDs to update (when using --tier)"),
    ] = None,
) -> None:
    """Batch update tier for multiple episodes."""
    batch_tier_impl(ctx.obj, input_file, json_input, tier, uuids)


@app.command("export")
def export_cmd(
    tier: Annotated[
        str | None,
        typer.Option("--tier", "-t", help="Filter by tier (mandate, guardrail, reference)"),
    ] = None,
    uuids: Annotated[
        list[str] | None,
        typer.Argument(help="Specific UUIDs to export (optional)"),
    ] = None,
    output: Annotated[
        Path | None,
        typer.Option(
            "--output",
            "-o",
            help="Output file or directory (no extension = directory with tier-split files)",
        ),
    ] = None,
    full: Annotated[
        bool,
        typer.Option(
            "--full", "-f", help="Export all fields (default: minimal fields for tune_it)"
        ),
    ] = False,
    scope: Annotated[
        str,
        typer.Option("--scope", "-s", help="Memory scope (global or project)"),
    ] = "global",
    scope_id: Annotated[
        str | None,
        typer.Option("--scope-id", help="Scope identifier (e.g., project ID)"),
    ] = None,
) -> None:
    """Export episodes as JSON. Use directory path (no extension) for tier-split files."""
    export_impl(tier, uuids, output, scope, scope_id, full)


@app.command("import")
def import_cmd(
    ctx: typer.Context,
    input_path: Annotated[
        Path,
        typer.Argument(help="JSON file or directory to import (from st memory export)"),
    ],
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Show what would change without applying"),
    ] = False,
) -> None:
    """Import episodes from JSON file or directory. Directories process all .json files."""
    import_impl(ctx.obj, input_path, dry_run)


@app.command("cleanup")
def cleanup(
    ctx: typer.Context,
    orphaned: Annotated[
        bool,
        typer.Option("--orphaned", help="Clean up orphaned edges (stale episode refs)"),
    ] = False,
    stale: Annotated[
        bool,
        typer.Option("--stale", help="Clean up stale memories not accessed within TTL"),
    ] = False,
    ttl_days: Annotated[
        int,
        typer.Option("--ttl-days", help="TTL in days for stale cleanup (default 30)"),
    ] = 30,
    scope: Annotated[
        str,
        typer.Option("--scope", "-s", help="Memory scope (global or project)"),
    ] = "global",
    scope_id: Annotated[
        str | None,
        typer.Option("--scope-id", help="Scope identifier (e.g., project ID)"),
    ] = None,
) -> None:
    """Clean up memory system."""
    cleanup_impl(ctx.obj, orphaned, stale, ttl_days, scope, scope_id)
