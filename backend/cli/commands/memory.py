"""Memory commands for the CLI - interact with Agent Hub memory system."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated

import typer

from .compactness import warn_memory_compactness
from .memory_commands import (
    batch_tier_impl,
    cleanup_impl,
    delete_impl,
    export_impl,
    get_impl,
    import_impl,
    list_impl,
    restore_impl,
    revisions_impl,
    save_impl,
    search_impl,
    seed_impl,
    stats_impl,
    status_impl,
    tag_impl,
    update_impl,
)
from .memory_options import (
    AgentSlugsOpt,
    AudienceTagsOpt,
    BatchTierOpt,
    ChangeReasonOpt,
    ClearApplicabilityOpt,
    ClearTagsOpt,
    ConfidenceOpt,
    ConsumerProfilesOpt,
    ContentArg,
    ContentFileOpt,
    ContentOpt,
    ContextKindOpt,
    ContextKindUpdateOpt,
    ContextOpt,
    CursorOpt,
    DryRunOpt,
    ExcludeAgentSlugsOpt,
    ExcludeAudienceTagsOpt,
    ExcludeConsumerProfilesOpt,
    FormatInstructionOpt,
    FormatProhibitionOpt,
    FormatSummaryOpt,
    FormatTopicOpt,
    FormatWhyOpt,
    FullExportOpt,
    HistoryLimitOpt,
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
    RevisionArg,
    SaveSummaryOpt,
    ScopeIdOpt,
    ScopeOpt,
    SearchLimitOpt,
    StaleOpt,
    SummaryUpdateOpt,
    TagsOpt,
    TagsUpdateOpt,
    TierFilterOpt,
    TierOpt,
    TierUpdateOpt,
    TriggerPhasesOpt,
    TriggerPhasesUpdateOpt,
    TriggerTypesOpt,
    TriggerTypesUpdateOpt,
    TtlDaysOpt,
    UUIDArg,
    UUIDsArg,
    UUIDsBatchArg,
    UUIDsDeleteArg,
    UUIDsOptArg,
)
from .memory_validation import (
    build_episode_content,
    emit_save_quickstart_error,
    suggest_summary,
    validate_content_format,
)

app = typer.Typer(help="Memory system commands (Agent Hub)")


def _resolve_content(content: str | None, content_file: str | None, *, require_value: bool) -> str | None:
    """Resolve content from inline text or file/stdin."""
    if content and content_file:
        raise typer.BadParameter("Specify only one of --content or --content-file")

    if content_file is None:
        if require_value and not content:
            raise typer.BadParameter("Provide content or use --content-file")
        return content

    if content_file == "-":
        return sys.stdin.read()

    path = Path(content_file)
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        from ..output import output_error
        output_error(f"Content file not found: {content_file}")
        raise typer.Exit(1) from None
    except PermissionError:
        from ..output import output_error
        output_error(f"Permission denied reading content file: {content_file}")
        raise typer.Exit(1) from None


def _resolve_and_validate_save(
    summary: str | None, content: str | None, content_file: str | None,
) -> str:
    """Validate save inputs, emitting quickstart on error; return resolved content."""
    missing_summary = summary is None or not summary.strip()
    missing_content = content_file is None and not (content and content.strip())
    if missing_summary or missing_content:
        emit_save_quickstart_error(missing_summary=missing_summary, missing_content=missing_content)
    resolved = _resolve_content(content, content_file, require_value=False)
    if resolved is None or not resolved.strip():
        emit_save_quickstart_error(blank_content=True)
    return resolved  # type: ignore[return-value]


@app.callback(invoke_without_command=True)
def memory_default(ctx: typer.Context) -> None:
    """Show memory stats (default command)."""
    if ctx.invoked_subcommand is None:
        stats(ctx)


@app.command()
def stats(ctx: typer.Context, scope: ScopeOpt = "global", scope_id: ScopeIdOpt = None) -> None:
    """Get memory statistics."""
    stats_impl(ctx.obj, scope, scope_id)


@app.command()
def status(
    ctx: typer.Context,
    scope: ScopeOpt = "global",
    scope_id: ScopeIdOpt = None,
    consumer_profile: Annotated[
        str,
        typer.Option("--consumer-profile", help="Consumer profile to probe"),
    ] = "claude_session_start",
    current_branch: Annotated[
        str | None,
        typer.Option("--branch", help="Optional branch for continuity-scoped probes"),
    ] = None,
) -> None:
    """Check live progressive-context delivery health."""
    healthy = status_impl(ctx.obj, scope, scope_id, consumer_profile, current_branch)
    if not healthy:
        raise typer.Exit(1)


@app.command()
def save(
    ctx: typer.Context,
    summary: SaveSummaryOpt = None,
    content: ContentArg = None,
    content_file: ContentFileOpt = None,
    tier: TierOpt = "reference",
    confidence: ConfidenceOpt = 80,
    context: ContextOpt = None,
    pinned: PinnedOpt = False,
    trigger_types: TriggerTypesOpt = None,
    trigger_phases: TriggerPhasesOpt = None,
    context_kind: ContextKindOpt = None,
    consumer_profiles: ConsumerProfilesOpt = None,
    exclude_consumer_profiles: ExcludeConsumerProfilesOpt = None,
    agent_slugs: AgentSlugsOpt = None,
    exclude_agent_slugs: ExcludeAgentSlugsOpt = None,
    audience_tags: AudienceTagsOpt = None,
    exclude_audience_tags: ExcludeAudienceTagsOpt = None,
    tags: TagsOpt = None,
    scope: ScopeOpt = "global",
    scope_id: ScopeIdOpt = None,
    change_reason: ChangeReasonOpt = None,
) -> None:
    """Save a learning to the memory system."""
    resolved_content = _resolve_and_validate_save(summary, content, content_file)
    assert summary is not None
    warn_memory_compactness(summary, resolved_content)
    save_impl(
        ctx.obj, resolved_content, summary, tier, confidence, context, pinned,
        trigger_types, trigger_phases, context_kind, consumer_profiles,
        exclude_consumer_profiles, agent_slugs, exclude_agent_slugs,
        audience_tags, exclude_audience_tags, tags, scope, scope_id, change_reason,
    )


@app.command("format")
def format_cmd(
    tier: TierOpt = "reference",
    topic: FormatTopicOpt = ...,
    instruction: FormatInstructionOpt = ...,
    prohibition: FormatProhibitionOpt = None,
    why: FormatWhyOpt = None,
    summary: FormatSummaryOpt = None,
) -> None:
    """Generate a standard memory episode body and compact summary."""
    content = build_episode_content(topic, instruction, prohibition, why)
    resolved_summary = (summary.strip() if summary else suggest_summary(instruction)) or "Memory episode"
    validate_content_format(content, resolved_summary, tier)
    typer.echo(f"SUMMARY: {resolved_summary}")
    typer.echo("CONTENT:")
    typer.echo(content)


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
    tier: TierFilterOpt = None,
    scope: ScopeOpt = "global",
    scope_id: ScopeIdOpt = None,
) -> None:
    """Search memory for relevant episodes."""
    search_impl(ctx.obj, query, limit, min_score, tier, scope, scope_id)


@app.command()
def get(ctx: typer.Context, uuids: UUIDsArg) -> None:
    """Get details for one or more episodes by UUID."""
    get_impl(ctx.obj, uuids)


@app.command()
def delete(uuids: UUIDsDeleteArg, change_reason: ChangeReasonOpt = None) -> None:
    """Delete one or more episodes from memory."""
    delete_impl(uuids, change_reason=change_reason)


@app.command()
def update(
    uuid: UUIDArg,
    content: ContentOpt = None,
    content_file: ContentFileOpt = None,
    tier: TierUpdateOpt = None,
    summary: SummaryUpdateOpt = None,
    trigger_types: TriggerTypesUpdateOpt = None,
    trigger_phases: TriggerPhasesUpdateOpt = None,
    pinned: PinnedUpdateOpt = None,
    context_kind: ContextKindUpdateOpt = None,
    consumer_profiles: ConsumerProfilesOpt = None,
    exclude_consumer_profiles: ExcludeConsumerProfilesOpt = None,
    agent_slugs: AgentSlugsOpt = None,
    exclude_agent_slugs: ExcludeAgentSlugsOpt = None,
    audience_tags: AudienceTagsOpt = None,
    exclude_audience_tags: ExcludeAudienceTagsOpt = None,
    clear_applicability: ClearApplicabilityOpt = False,
    tags: TagsUpdateOpt = None,
    clear_tags: ClearTagsOpt = False,
    change_reason: ChangeReasonOpt = None,
) -> None:
    """Update an episode in place (content/tier and properties)."""
    resolved_content = _resolve_content(content, content_file, require_value=False)
    if resolved_content is not None:
        warn_memory_compactness(uuid, resolved_content)
    update_impl(
        uuid, resolved_content, tier, summary, trigger_types, trigger_phases,
        pinned, context_kind, consumer_profiles, exclude_consumer_profiles,
        agent_slugs, exclude_agent_slugs, audience_tags, exclude_audience_tags,
        clear_applicability, tags, clear_tags, change_reason,
    )


@app.command("tag")
def tag(
    uuids: UUIDsArg,
    add_tags: Annotated[str | None, typer.Option("--add-tags", help="Comma-separated tags to add")] = None,
    remove_tags: Annotated[str | None, typer.Option("--remove-tags", help="Comma-separated tags to remove")] = None,
) -> None:
    """Add/remove tags on one or more episodes without replacing the full list."""
    tag_impl(uuids, add_tags=add_tags, remove_tags=remove_tags)


@app.command("revisions")
def revisions(ctx: typer.Context, uuid: UUIDArg, limit: HistoryLimitOpt = 20) -> None:
    """List immutable revision history for one episode."""
    revisions_impl(ctx.obj, uuid, limit)


@app.command()
def restore(uuid: UUIDArg, revision_id: RevisionArg, change_reason: ChangeReasonOpt = None) -> None:
    """Restore an episode to a historical revision."""
    restore_impl(uuid, revision_id, change_reason=change_reason)


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
