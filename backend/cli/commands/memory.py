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
    seed_impl,
    stats_impl,
    update_impl,
)
from .memory_options import (
    BatchTierOpt,
    ConfidenceOpt,
    ConfirmOpt,
    ContentArg,
    ContentOpt,
    ContextOpt,
    CursorOpt,
    DryRunOpt,
    FullExportOpt,
    InputFileOpt,
    InputPathArg,
    JsonInputOpt,
    LimitOpt,
    MinScoreOpt,
    OrphanedOpt,
    OutputOpt,
    PinnedOpt,
    PinnedUpdateOpt,
    QueryArg,
    ScopeIdOpt,
    ScopeOpt,
    SearchLimitOpt,
    StaleOpt,
    SummaryOpt,
    SummaryUpdateOpt,
    TierFilterOpt,
    TierOpt,
    TierUpdateOpt,
    TriggerTypesOpt,
    TriggerTypesUpdateOpt,
    TtlDaysOpt,
    UUIDArg,
    UUIDsArg,
    UUIDsBatchArg,
    UUIDsDeleteArg,
    UUIDsOptArg,
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
    scope: ScopeOpt = "global",
    scope_id: ScopeIdOpt = None,
) -> None:
    """Get memory statistics."""
    stats_impl(ctx.obj, scope, scope_id)


@app.command()
def save(
    ctx: typer.Context,
    content: ContentArg,
    summary: SummaryOpt,
    tier: TierOpt = "reference",
    confidence: ConfidenceOpt = 80,
    context: ContextOpt = None,
    pinned: PinnedOpt = False,
    trigger_types: TriggerTypesOpt = None,
    scope: ScopeOpt = "global",
    scope_id: ScopeIdOpt = None,
) -> None:
    """Save a learning to the memory system."""
    save_impl(
        ctx.obj, content, summary, tier, confidence, context, pinned, trigger_types, scope, scope_id
    )


@app.command("list")
def list_cmd(
    ctx: typer.Context,
    limit: LimitOpt = 50,
    cursor: CursorOpt = None,
    tier: TierFilterOpt = None,
    scope: ScopeOpt = "global",
    scope_id: ScopeIdOpt = None,
) -> None:
    """List memory episodes with pagination."""
    list_impl(ctx.obj, limit, cursor, tier, scope, scope_id)


@app.command()
def search(
    ctx: typer.Context,
    query: QueryArg,
    limit: SearchLimitOpt = 10,
    min_score: MinScoreOpt = 0.0,
    scope: ScopeOpt = "global",
    scope_id: ScopeIdOpt = None,
) -> None:
    """Search memory for relevant episodes."""
    search_impl(ctx.obj, query, limit, min_score, scope, scope_id)


@app.command()
def get(ctx: typer.Context, uuids: UUIDsArg) -> None:
    """Get details for one or more episodes by UUID."""
    get_impl(ctx.obj, uuids)


@app.command()
def delete(uuids: UUIDsDeleteArg, confirm: ConfirmOpt = False) -> None:
    """Delete one or more episodes from memory."""
    delete_impl(uuids, confirm)


@app.command()
def update(
    uuid: UUIDArg,
    content: ContentOpt = None,
    tier: TierUpdateOpt = None,
    summary: SummaryUpdateOpt = None,
    trigger_types: TriggerTypesUpdateOpt = None,
    pinned: PinnedUpdateOpt = None,
    confirm: ConfirmOpt = False,
) -> None:
    """Update an episode (delete + recreate for content/tier, PATCH for properties)."""
    update_impl(uuid, content, tier, summary, trigger_types, pinned, confirm)


@app.command("batch-tier")
def batch_tier(
    ctx: typer.Context,
    input_file: InputFileOpt = None,
    json_input: JsonInputOpt = None,
    tier: BatchTierOpt = None,
    uuids: UUIDsBatchArg = None,
) -> None:
    """Batch update tier for multiple episodes."""
    batch_tier_impl(ctx.obj, input_file, json_input, tier, uuids)


@app.command("export")
def export_cmd(
    tier: TierFilterOpt = None,
    uuids: UUIDsOptArg = None,
    output: OutputOpt = None,
    full: FullExportOpt = False,
    scope: ScopeOpt = "global",
    scope_id: ScopeIdOpt = None,
) -> None:
    """Export episodes as JSON. Use directory path (no extension) for tier-split files."""
    export_impl(tier, uuids, output, scope, scope_id, full)


@app.command("import")
def import_cmd(ctx: typer.Context, input_path: InputPathArg, dry_run: DryRunOpt = False) -> None:
    """Import episodes from JSON file or directory. Directories process all .json files."""
    import_impl(ctx.obj, input_path, dry_run)


@app.command("cleanup")
def cleanup(
    ctx: typer.Context,
    orphaned: OrphanedOpt = False,
    stale: StaleOpt = False,
    ttl_days: TtlDaysOpt = 30,
    scope: ScopeOpt = "global",
    scope_id: ScopeIdOpt = None,
) -> None:
    """Clean up memory system."""
    cleanup_impl(ctx.obj, orphaned, stale, ttl_days, scope, scope_id)


@app.command("seed")
def seed(
    directory: Annotated[Path, typer.Argument(help="Directory containing .md skill files")],
    dry_run: DryRunOpt = False,
    project: str | None = typer.Option(None, "--project", "-p", help="Project name for scoping"),
    scope: ScopeOpt = "global",
    scope_id: ScopeIdOpt = None,
) -> None:
    """Seed memory episodes from markdown skill files.

    Reads .md files with YAML frontmatter from a directory and upserts
    them as memory episodes. Uses skill:<filename> tag for idempotent
    re-seeding.
    """
    seed_impl(directory, scope, scope_id, dry_run, project)
