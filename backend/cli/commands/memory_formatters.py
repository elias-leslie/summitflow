"""Formatting functions for memory command output."""

from __future__ import annotations

from typing import Any

import typer


def format_stats_compact(stats: dict[str, Any]) -> None:
    """Format memory stats in TOON style."""
    total = stats.get("total", stats.get("total_count", 0))
    by_category = stats.get("by_category", [])

    category_parts = []
    if isinstance(by_category, list):
        for item in by_category:
            cat = item.get("category", "?")
            count = item.get("count", 0)
            category_parts.append(f"{cat}={count}")
    elif isinstance(by_category, dict):
        for cat, count in sorted(by_category.items()):
            category_parts.append(f"{cat}={count}")

    category_str = "|".join(category_parts) if category_parts else "empty"
    print(f"MEMORY[{total}]:{category_str}")


def format_save_compact(result: dict[str, Any]) -> None:
    """Format save result in TOON style."""
    if result.get("is_duplicate"):
        uuid = result.get("reinforced_uuid", "?")
        status = result.get("status", "?")
        print(f"DUPLICATE:{uuid}:{status}")
    elif result.get("uuid"):
        uuid = result.get("uuid", "?")
        status = result.get("status", "?")
        print(f"SAVED:{uuid}:{status}")
    else:
        status = result.get("status", "rejected")
        message = result.get("message", "")
        print(f"REJECTED:{status}:{message}")


def format_list_compact(result: dict[str, Any]) -> None:
    """Format episode list in TOON style."""
    episodes = result.get("episodes", [])
    cursor = result.get("cursor")

    cursor_str = f"cursor={cursor}" if cursor else "cursor=none"
    print(f"EPISODES[{len(episodes)}]:{cursor_str}")

    for ep in episodes:
        uuid = ep.get("uuid", "?")[:8]
        tier = ep.get("category") or ep.get("injection_tier", "?")
        summary = ep.get("summary", "")
        content = ep.get("content", "")
        print(f"  {uuid} [{tier}] summary={summary}")
        print(f"    {content}")


def format_search_compact(result: dict[str, Any]) -> None:
    """Format search results in TOON style."""
    results = result.get("results", [])
    query = result.get("query", "")

    print(f'RESULTS[{len(results)}]:query="{query}"')

    for r in results:
        uuid = r.get("uuid", "?")[:8]
        score = r.get("relevance_score", 0.0)
        content = r.get("content", "")
        print(f"  {uuid} {score:.2f}")
        print(f"    {content}")


def format_get_compact(result: dict[str, Any]) -> None:
    """Format single episode details - shows FULL content for retrieval."""
    uuid_short = result.get("uuid", "")[:8]
    tier = result.get("injection_tier", "unknown")
    content = result.get("content", "")
    helpful = result.get("helpful_count", 0)
    harmful = result.get("harmful_count", 0)
    loaded = result.get("loaded_count", 0)
    summary = result.get("summary")
    trigger_types = result.get("trigger_task_types", [])
    pinned = result.get("pinned", False)

    typer.echo(f"{uuid_short} [{tier}] loaded={loaded} helpful={helpful} harmful={harmful}")
    if summary:
        typer.echo(f"Summary: {summary}")
    if trigger_types:
        typer.echo(f"Triggers: {', '.join(trigger_types)}")
    if pinned:
        typer.echo("Pinned: yes")
    typer.echo("")
    typer.echo(content)


def format_batch_get_compact(result: dict[str, Any]) -> None:
    """Format batch get results - shows FULL content for each episode."""
    episodes = result.get("episodes", {})
    found = result.get("found", 0)
    missing = result.get("missing", [])

    total_requested = found + len(missing)
    typer.echo(f"GET[{found}/{total_requested}]:missing={len(missing)}")

    for uuid, ep in episodes.items():
        uuid_short = uuid[:8]
        tier = ep.get("injection_tier", "?")
        content = ep.get("content", "")
        helpful = ep.get("helpful_count", 0)
        harmful = ep.get("harmful_count", 0)
        loaded = ep.get("loaded_count", 0)
        summary = ep.get("summary")

        typer.echo("")
        typer.echo(f"{uuid_short} [{tier}] loaded={loaded} helpful={helpful} harmful={harmful}")
        if summary:
            typer.echo(f"Summary: {summary}")
        typer.echo(content)

    if missing:
        typer.echo(f"\nMISSING: {', '.join(u[:8] for u in missing)}")


def format_batch_tier_compact(result: dict[str, Any]) -> None:
    """Format batch tier update in TOON format."""
    updated = result.get("updated", 0)
    total = result.get("total", 0)
    failed = result.get("failed", 0)

    if failed == 0:
        typer.echo(f"BATCH_TIER[{total}]:updated={updated}:OK")
    else:
        typer.echo(f"BATCH_TIER[{total}]:updated={updated}|failed={failed}:PARTIAL")
        for r in result.get("results", []):
            if not r.get("success"):
                typer.echo(f"  FAIL:{r['uuid'][:8]}:{r.get('error', 'unknown')}")


def format_orphaned_cleanup_compact(result: dict[str, Any]) -> None:
    """Format orphaned edge cleanup results in TOON style."""
    updated = result.get("edges_updated", 0)
    deleted = result.get("edges_deleted", 0)
    stale_refs = result.get("stale_refs_removed", 0)
    error = result.get("error")

    if error:
        print(f"CLEANUP:FAIL:{error}")
    else:
        print(f"ORPHANED:updated={updated}|deleted={deleted}|stale_refs={stale_refs}")


def format_stale_cleanup_compact(result: dict[str, Any]) -> None:
    """Format stale memory cleanup results in TOON style."""
    deleted = result.get("deleted", 0)
    skipped = result.get("skipped", False)
    reason = result.get("reason")

    if skipped:
        print(f"STALE:SKIP:{reason or 'unknown'}")
    else:
        print(f"STALE:deleted={deleted}")
