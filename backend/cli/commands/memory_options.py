"""Common Typer option definitions for memory commands."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

# Scope options
ScopeOpt = Annotated[
    str,
    typer.Option("--scope", "-s", help="Memory scope (global or project)"),
]

ScopeIdOpt = Annotated[
    str | None,
    typer.Option("--scope-id", help="Scope identifier (e.g., project ID)"),
]

# Tier options
TierOpt = Annotated[
    str,
    typer.Option("--tier", "-t", help="Injection tier (mandate, guardrail, reference)"),
]

TierFilterOpt = Annotated[
    str | None,
    typer.Option("--tier", "-t", help="Filter by tier (mandate, guardrail, reference)"),
]

TierUpdateOpt = Annotated[
    str | None,
    typer.Option("--tier", "-t", help="New tier (mandate/guardrail/reference)"),
]

# Content and metadata options
ContentArg = Annotated[str, typer.Argument(help="Learning content to save")]

ContentOpt = Annotated[
    str | None,
    typer.Option("--content", "-c", help="New content for the episode"),
]

ContentFileOpt = Annotated[
    str | None,
    typer.Option(
        "--content-file",
        help="Read new content from a file path or '-' for stdin",
    ),
]

SummaryOpt = Annotated[
    str,
    typer.Option(
        "--summary", "-S", help="REQUIRED: Short action phrase (~35 chars) for TOON index"
    ),
]

SummaryUpdateOpt = Annotated[
    str | None,
    typer.Option("--summary", "-S", help="Update summary (~35 chars for TOON index)"),
]

ConfidenceOpt = Annotated[
    int,
    typer.Option("--confidence", "-c", help="Confidence level 0-100"),
]

ContextOpt = Annotated[
    str | None,
    typer.Option("--context", help="Optional context about the learning source"),
]

PinnedOpt = Annotated[
    bool,
    typer.Option("--pinned", "-p", help="Pin episode (always inject regardless of budget)"),
]

PinnedUpdateOpt = Annotated[
    bool | None,
    typer.Option(
        "--pinned/--no-pinned", help="Pin episode (always inject regardless of budget)"
    ),
]

TriggerTypesOpt = Annotated[
    str | None,
    typer.Option(
        "--trigger-types", "-T", help="Comma-separated task types (e.g., database,memory)"
    ),
]

TriggerTypesUpdateOpt = Annotated[
    str | None,
    typer.Option(
        "--trigger-types", help="Comma-separated task types (backend,frontend,database,etc.)"
    ),
]

# Query and search options
QueryArg = Annotated[str, typer.Argument(help="Search query")]

LimitOpt = Annotated[
    int,
    typer.Option("--limit", "-l", help="Max episodes to return (1-300)"),
]

SearchLimitOpt = Annotated[
    int,
    typer.Option("--limit", "-l", help="Max results (1-300)"),
]

MinScoreOpt = Annotated[
    float,
    typer.Option("--min-score", help="Minimum relevance score (0.0-1.0)"),
]

CursorOpt = Annotated[
    str | None,
    typer.Option("--cursor", help="Pagination cursor from previous response"),
]

# UUID options
UUIDsArg = Annotated[list[str], typer.Argument(help="Episode UUID(s) to retrieve")]
UUIDsDeleteArg = Annotated[list[str], typer.Argument(help="Episode UUID(s) to delete")]
UUIDArg = Annotated[str, typer.Argument(help="Episode UUID to update")]
UUIDsOptArg = Annotated[
    list[str] | None,
    typer.Argument(help="Specific UUIDs to export (optional)"),
]
UUIDsBatchArg = Annotated[
    list[str] | None,
    typer.Argument(help="UUIDs to update (when using --tier)"),
]

# Batch operation options
InputFileOpt = Annotated[
    Path | None,
    typer.Option("--file", "-f", help="JSON file with updates [{uuid, tier}]"),
]

JsonInputOpt = Annotated[
    str | None,
    typer.Option("--json", "-j", help="JSON string with updates"),
]

BatchTierOpt = Annotated[
    str | None,
    typer.Option("--tier", "-t", help="Tier to apply to all UUIDs"),
]

# Import/export options
OutputOpt = Annotated[
    Path | None,
    typer.Option(
        "--output",
        "-o",
        help="Output file or directory (no extension = directory with tier-split files)",
    ),
]

FullExportOpt = Annotated[
    bool,
    typer.Option(
        "--full", "-f", help="Export all fields (default: minimal fields for tune_it)"
    ),
]

InputPathArg = Annotated[
    Path,
    typer.Argument(help="JSON file or directory to import (from st memory export)"),
]

DryRunOpt = Annotated[
    bool,
    typer.Option("--dry-run", help="Show what would change without applying"),
]

# Cleanup options
OrphanedOpt = Annotated[
    bool,
    typer.Option("--orphaned", help="Clean up orphaned edges (stale episode refs)"),
]

StaleOpt = Annotated[
    bool,
    typer.Option("--stale", help="Clean up stale memories not accessed within TTL"),
]

TtlDaysOpt = Annotated[
    int,
    typer.Option("--ttl-days", help="TTL in days for stale cleanup (default 30)"),
]
