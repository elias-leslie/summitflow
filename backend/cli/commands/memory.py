"""Memory commands for the CLI - interact with Agent Hub memory system."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any, cast

import httpx
import typer

from ..config import get_agent_hub_url
from ..output import is_compact, output_error, output_json

app = typer.Typer(help="Memory system commands (Agent Hub)")


def _load_credentials() -> tuple[str, str, str]:
    """Load credentials from ~/.env.local."""
    env_file = Path.home() / ".env.local"
    if not env_file.exists():
        output_error("~/.env.local not found - required for Agent Hub authentication")
        raise typer.Exit(1)

    creds: dict[str, str] = {}
    for line in env_file.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            key, val = line.split("=", 1)
            creds[key.strip()] = val.strip()

    client_id = creds.get("SUMMITFLOW_CLIENT_ID")
    client_secret = creds.get("SUMMITFLOW_CLIENT_SECRET")
    request_source = "st-memory"

    if not client_id or not client_secret:
        output_error("Missing SUMMITFLOW_CLIENT_ID/SECRET in ~/.env.local")
        raise typer.Exit(1)

    return client_id, client_secret, request_source


def _agent_hub_request(
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    json: dict[str, Any] | None = None,
    scope: str = "global",
    scope_id: str | None = None,
    tool_name: str = "st memory",
) -> dict[str, Any]:
    """Make a request to Agent Hub API with proper authentication.

    Args:
        method: HTTP method (GET, POST, DELETE).
        path: API path (e.g., "/api/memory/stats").
        params: Query parameters.
        json: JSON body for POST requests.
        scope: Memory scope ("global" or "project").
        scope_id: Scope identifier when scope is "project".
        tool_name: Specific command name for tracking.

    Returns:
        Response JSON as dict.

    Raises:
        typer.Exit: On API error.
    """
    client_id, client_secret, request_source = _load_credentials()

    headers = {
        "X-Client-Id": client_id,
        "X-Client-Secret": client_secret,
        "X-Request-Source": request_source,
        "X-Source-Client": "st-cli",
        "X-Tool-Name": tool_name,
    }
    if scope != "global":
        headers["X-Memory-Scope"] = scope
    if scope_id:
        headers["X-Scope-Id"] = scope_id

    agent_hub_url = get_agent_hub_url()
    url = f"{agent_hub_url}{path}"

    try:
        with httpx.Client(timeout=30.0) as client:
            if method == "GET":
                response = client.get(url, params=params, headers=headers)
            elif method == "DELETE":
                response = client.delete(url, headers=headers)
            elif method == "PATCH":
                response = client.patch(url, json=json, headers=headers)
            else:
                response = client.post(url, json=json, headers=headers)

            if response.status_code >= 400:
                try:
                    detail = response.json().get("detail", response.text)
                except Exception:
                    detail = response.text
                output_error(f"API error ({response.status_code}): {detail}")
                raise typer.Exit(1) from None

            return cast(dict[str, Any], response.json())
    except httpx.ConnectError:
        output_error(f"Cannot connect to Agent Hub at {agent_hub_url}")
        raise typer.Exit(1) from None
    except typer.Exit:
        raise
    except Exception as e:
        output_error(f"Request failed: {e}")
        raise typer.Exit(1) from None


def _format_stats_compact(stats: dict[str, Any]) -> None:
    """Format memory stats in TOON style.

    Format:
    MEMORY[total]:by_category
    """
    total = stats.get("total", stats.get("total_count", 0))
    by_category = stats.get("by_category", [])

    category_parts = []
    # Handle both list of dicts and dict format
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


def _format_save_compact(result: dict[str, Any]) -> None:
    """Format save result in TOON style.

    Format:
    SAVED|DUPLICATE|REJECTED:uuid|reinforced:status
    """
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
        print(f"REJECTED:{status}:{message[:50]}")


def _format_list_compact(result: dict[str, Any]) -> None:
    """Format episode list in TOON style.

    Format:
    EPISODES[count]:cursor=X
      uuid name content_preview
    """
    episodes = result.get("episodes", [])
    cursor = result.get("cursor")

    cursor_str = f"cursor={cursor[:20]}..." if cursor else "cursor=none"
    print(f"EPISODES[{len(episodes)}]:{cursor_str}")

    for ep in episodes[:20]:  # Limit output
        uuid = ep.get("uuid", "?")[:8]
        name = ep.get("name", "-")[:20]
        content = ep.get("content", "-")[:50]
        if len(content) == 50:
            content += "..."
        print(f"  {uuid} {name} {content}")


def _format_search_compact(result: dict[str, Any]) -> None:
    """Format search results in TOON style.

    Format:
    RESULTS[count]:query="X"
      uuid score content_preview
    """
    results = result.get("results", [])
    query = result.get("query", "")

    print(f'RESULTS[{len(results)}]:query="{query[:30]}"')

    for r in results[:20]:  # Limit output
        uuid = r.get("uuid", "?")[:8]
        score = r.get("relevance_score", 0.0)
        content = r.get("content", "-")[:50]
        if len(content) == 50:
            content += "..."
        print(f"  {uuid} {score:.2f} {content}")


@app.callback(invoke_without_command=True)
def memory_default(ctx: typer.Context) -> None:
    """Show memory stats (default command).

    Examples:
        st memory
        st memory --human
    """
    if ctx.invoked_subcommand is None:
        stats()


@app.command()
def stats(
    scope: Annotated[
        str,
        typer.Option("--scope", "-s", help="Memory scope (global or project)"),
    ] = "global",
    scope_id: Annotated[
        str | None,
        typer.Option("--scope-id", help="Scope identifier (e.g., project ID)"),
    ] = None,
) -> None:
    """Get memory statistics.

    Shows total count and breakdown by category.

    Examples:
        st memory stats
        st memory stats --scope project --scope-id summitflow
    """
    result = _agent_hub_request(
        "GET",
        "/api/memory/stats",
        scope=scope,
        scope_id=scope_id,
        tool_name="st memory stats",
    )

    if is_compact():
        _format_stats_compact(result)
    else:
        output_json(result)


@app.command()
def save(
    content: Annotated[
        str,
        typer.Argument(help="Learning content to save"),
    ],
    summary: Annotated[
        str,
        typer.Option(
            "--summary", "-S", help="REQUIRED: Short action phrase (~20 chars) for TOON index"
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
    """Save a learning to the memory system.

    Learnings are stored with confidence levels:
    - 70-89%: provisional (needs reinforcement to promote)
    - 90+%: canonical (immediately trusted)

    REQUIRED: --summary must be a short action phrase (~20 chars) for the TOON index.
    No auto-generation - caller must provide a quality summary.

    Examples:
        st memory save "Always use async for DB" --summary "use async for DB" --tier reference
        st memory save "NEVER modify node_modules" --summary "no node_modules edit" --tier guardrail
        st memory save "Use TIMESTAMPTZ for dates" --summary "use TIMESTAMPTZ" --tier mandate
        st memory save "Memory workflow docs" --summary "memory workflow" --tier reference --pinned
        st memory save "Database pattern" --summary "db pattern" -T database,backend
    """
    if tier not in ("mandate", "guardrail", "reference"):
        output_error(f"Invalid tier: {tier}. Must be mandate, guardrail, or reference.")
        raise typer.Exit(1)

    if confidence < 0 or confidence > 100:
        output_error(f"Invalid confidence: {confidence}. Must be 0-100.")
        raise typer.Exit(1)

    if not summary or not summary.strip():
        output_error("--summary is required. Provide a short action phrase (~20 chars).")
        raise typer.Exit(1)

    summary = summary.strip()
    if len(summary) > 30:
        output_error(f"Summary too long ({len(summary)} chars). Keep it under 30 chars.")
        raise typer.Exit(1)

    payload: dict[str, Any] = {
        "content": content,
        "injection_tier": tier,
        "confidence": confidence,
        "summary": summary,
    }
    if context:
        payload["context"] = context
    if pinned:
        payload["pinned"] = True
    if trigger_types:
        payload["trigger_task_types"] = [t.strip() for t in trigger_types.split(",")]

    result = _agent_hub_request(
        "POST",
        "/api/memory/save-learning",
        json=payload,
        scope=scope,
        scope_id=scope_id,
        tool_name="st memory save",
    )

    if is_compact():
        _format_save_compact(result)
    else:
        output_json(result)


@app.command("list")
def list_cmd(
    limit: Annotated[
        int,
        typer.Option("--limit", "-l", help="Max episodes to return (1-100)"),
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
    """List memory episodes with pagination.

    Returns episodes in reverse chronological order.

    Examples:
        st memory list
        st memory list --limit 10
        st memory list --tier mandate
        st memory list --cursor "2026-01-20T..."
    """
    params: dict[str, Any] = {"limit": limit}
    if cursor:
        params["cursor"] = cursor
    if tier:
        # Map tier to category for the API
        # mandate/guardrail/reference are tiers, API uses category
        params["category"] = tier

    result = _agent_hub_request(
        "GET",
        "/api/memory/list",
        params=params,
        scope=scope,
        scope_id=scope_id,
        tool_name="st memory list",
    )

    if is_compact():
        _format_list_compact(result)
    else:
        output_json(result)


@app.command()
def search(
    query: Annotated[
        str,
        typer.Argument(help="Search query"),
    ],
    limit: Annotated[
        int,
        typer.Option("--limit", "-l", help="Max results (1-100)"),
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
    """Search memory for relevant episodes.

    Uses semantic search to find relevant learnings.

    Examples:
        st memory search "database patterns"
        st memory search "error handling" --limit 5
        st memory search "testing" --min-score 0.5
    """
    params: dict[str, Any] = {
        "query": query,
        "limit": limit,
        "min_score": min_score,
    }

    result = _agent_hub_request(
        "GET",
        "/api/memory/search",
        params=params,
        scope=scope,
        scope_id=scope_id,
        tool_name="st memory search",
    )

    if is_compact():
        _format_search_compact(result)
    else:
        output_json(result)


@app.command()
def get(
    uuids: Annotated[
        list[str],
        typer.Argument(help="Episode UUID(s) to retrieve"),
    ],
) -> None:
    """Get details for one or more episodes by UUID.

    Returns full episode information including usage statistics
    (helpful_count, harmful_count, loaded_count, referenced_count).

    Accepts full UUIDs or 8-character prefixes.

    Examples:
        st memory get abc12345
        st memory get abc12345 def67890 ghi11111
    """
    if not uuids:
        output_error("At least one UUID required")
        raise typer.Exit(1)

    if len(uuids) == 1:
        # Single get - use direct endpoint
        result = _agent_hub_request(
            "GET",
            f"/api/memory/episode/{uuids[0]}",
            tool_name="st memory get",
        )

        if "detail" in result:
            output_error(result["detail"])
            raise typer.Exit(1)

        if is_compact():
            _format_get_compact(result)
        else:
            output_json(result)
    else:
        # Batch get
        result = _agent_hub_request(
            "POST",
            "/api/memory/batch-get",
            json={"uuids": uuids},
            tool_name="st memory get",
        )

        if is_compact():
            _format_batch_get_compact(result)
        else:
            output_json(result)


def _format_get_compact(result: dict[str, Any]) -> None:
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

    # Header line: UUID, tier, stats
    typer.echo(f"{uuid_short} [{tier}] loaded={loaded} helpful={helpful} harmful={harmful}")
    if summary:
        typer.echo(f"Summary: {summary}")
    if trigger_types:
        typer.echo(f"Triggers: {', '.join(trigger_types)}")
    if pinned:
        typer.echo("Pinned: yes")
    typer.echo("")
    # Full content (the whole point of 'get' is retrieval)
    typer.echo(content)


def _format_batch_get_compact(result: dict[str, Any]) -> None:
    """Format batch get results in TOON style."""
    episodes = result.get("episodes", {})
    found = result.get("found", 0)
    missing = result.get("missing", [])

    total_requested = found + len(missing)
    print(f"GET[{found}/{total_requested}]:missing={len(missing)}")

    for uuid, ep in episodes.items():
        uuid_short = uuid[:8]
        tier = ep.get("injection_tier", "?")
        content = ep.get("content", "-")[:50]
        if len(content) == 50:
            content += "..."
        print(f"  {uuid_short} [{tier}] {content}")

    if missing:
        print(f"  MISSING: {', '.join(u[:8] for u in missing)}")


@app.command()
def delete(
    uuids: Annotated[
        list[str],
        typer.Argument(help="Episode UUID(s) to delete"),
    ],
    confirm: Annotated[
        bool,
        typer.Option("--confirm", help="Require confirmation prompt (default: no confirmation)"),
    ] = False,
) -> None:
    """Delete one or more episodes from memory.

    Removes episodes and cleans up orphaned entities/edges
    that were only connected through these episodes.

    Examples:
        st memory delete abc12345-uuid
        st memory delete uuid1 uuid2 uuid3
        st memory delete uuid1 --confirm  # Require confirmation
    """
    if confirm:
        # Show what will be deleted
        typer.echo(f"Will delete {len(uuids)} episode(s):")
        for uuid in uuids:
            typer.echo(f"  - {uuid[:8]}...")

        if not typer.confirm("Proceed with deletion?"):
            typer.echo("Cancelled.")
            raise typer.Exit(0)

    deleted = 0
    failed = 0

    for uuid in uuids:
        result = _agent_hub_request(
            "DELETE",
            f"/api/memory/episode/{uuid}",
            tool_name="st memory delete",
        )
        if result.get("success"):
            typer.echo(f"Deleted: {uuid[:8]}")
            deleted += 1
        else:
            typer.echo(f"Failed: {uuid[:8]} - {result.get('detail', 'Unknown error')}")
            failed += 1

    typer.echo(f"\nDeleted: {deleted}, Failed: {failed}")


@app.command()
def update(
    uuid: Annotated[
        str,
        typer.Argument(help="Episode UUID to update"),
    ],
    content: Annotated[
        str | None,
        typer.Option("--content", "-c", help="New content for the episode"),
    ] = None,
    tier: Annotated[
        str | None,
        typer.Option("--tier", "-t", help="New tier (mandate/guardrail/reference)"),
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
    """Update an episode (delete + recreate for content/tier, PATCH for properties).

    Note: Content/tier changes use delete+recreate (stats preserved).
    Properties (trigger-types, pinned) use PATCH endpoint.

    Examples:
        st memory update abc12345 --content "New content here"
        st memory update abc12345 --tier mandate
        st memory update abc12345 --trigger-types backend,database
        st memory update abc12345 --pinned
        st memory update abc12345 --content "New" --tier guardrail --trigger-types frontend
    """
    # Validate at least one option provided
    if not any([content, tier, trigger_types, pinned is not None]):
        typer.echo(
            "Error: Must specify at least one of: --content, --tier, --trigger-types, --pinned"
        )
        raise typer.Exit(1)

    # Get existing episode details
    existing = _agent_hub_request(
        "GET", f"/api/memory/episode/{uuid}", tool_name="st memory update"
    )
    if "detail" in existing:
        typer.echo(f"Error: {existing['detail']}")
        raise typer.Exit(1)

    full_uuid = existing.get("uuid", uuid)
    old_tier = existing.get("injection_tier", "reference")
    old_content = existing.get("content", "")

    # Determine what's changing
    content_or_tier_changed = bool(content or tier)
    properties_changed = bool(trigger_types or pinned is not None)

    if confirm:
        typer.echo(f"  UUID: {uuid[:8]}...")
        if tier:
            typer.echo(f"  Tier: {old_tier} -> {tier}")
        if content:
            typer.echo(f"  Content: {old_content[:40]}... -> {content[:40]}...")
        if trigger_types:
            typer.echo(f"  Trigger types: {trigger_types}")
        if pinned is not None:
            typer.echo(f"  Pinned: {pinned}")
        if content_or_tier_changed:
            typer.echo("  Usage stats will be preserved.")

        if not typer.confirm("Proceed with update?"):
            typer.echo("Cancelled.")
            raise typer.Exit(0)

    target_uuid = full_uuid

    # Handle content/tier changes via delete+create
    if content_or_tier_changed:
        new_content = content if content else old_content
        new_tier = tier if tier else old_tier

        create_result = _agent_hub_request(
            "POST",
            "/api/memory/add",
            json={
                "content": new_content,
                "name": existing.get("name", "updated_episode"),
                "injection_tier": new_tier,
                "preserve_stats_from": full_uuid,
            },
            tool_name="st memory update",
        )

        new_uuid = create_result.get("uuid")
        if not new_uuid:
            typer.echo(f"Error creating new episode: {create_result}")
            raise typer.Exit(1)

        delete_result = _agent_hub_request(
            "DELETE", f"/api/memory/episode/{uuid}", tool_name="st memory update"
        )
        if not delete_result.get("success"):
            typer.echo(
                f"Warning: Failed to delete original: {delete_result.get('detail', 'Unknown')}"
            )
            typer.echo(f"New episode created: {new_uuid[:8]}")
            typer.echo(f"Please manually delete: {uuid[:8]}")
            raise typer.Exit(1)

        target_uuid = new_uuid
        typer.echo(f"Updated: {uuid[:8]} -> {new_uuid[:8]}")
        if tier:
            typer.echo(f"  Tier: {new_tier}")

    # Handle properties via PATCH
    if properties_changed:
        props: dict[str, Any] = {}
        if trigger_types:
            props["trigger_task_types"] = [t.strip() for t in trigger_types.split(",")]
        if pinned is not None:
            props["pinned"] = pinned

        patch_result = _agent_hub_request(
            "PATCH",
            f"/api/memory/episode/{target_uuid}/properties",
            json=props,
            tool_name="st memory update",
        )

        if not patch_result.get("success"):
            typer.echo(
                f"Warning: Failed to update properties: {patch_result.get('message', 'Unknown')}"
            )
        else:
            if trigger_types:
                typer.echo(f"  Trigger types: {props['trigger_task_types']}")
            if pinned is not None:
                typer.echo(f"  Pinned: {pinned}")

    if not content_or_tier_changed and not properties_changed:
        typer.echo("No changes made.")


@app.command("batch-tier")
def batch_tier(
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
    """Batch update tier for multiple episodes.

    Three usage patterns:

    1. JSON file:
        st memory batch-tier -f updates.json
        # File format: [{"uuid": "abc12345", "tier": "reference"}, ...]

    2. JSON string:
        st memory batch-tier -j '[{"uuid": "abc12345", "tier": "reference"}]'

    3. UUIDs with tier flag:
        st memory batch-tier abc12345 def67890 ghi12345 -t reference

    Examples:
        st memory batch-tier 448b0dd7 2b39cbf6 537fc685 -t reference
        st memory batch-tier -f demotions.json
    """
    import json as json_lib

    updates: list[dict[str, str]] = []

    if input_file:
        if not input_file.exists():
            typer.echo(f"Error: File not found: {input_file}")
            raise typer.Exit(1)
        updates = json_lib.loads(input_file.read_text())
    elif json_input:
        updates = json_lib.loads(json_input)
    elif tier and uuids:
        updates = [{"uuid": u, "tier": tier} for u in uuids]
    else:
        typer.echo("Error: Provide --file, --json, or (UUIDs with --tier)")
        raise typer.Exit(1)

    if not updates:
        typer.echo("Error: No updates provided")
        raise typer.Exit(1)

    result = _agent_hub_request(
        "POST",
        "/api/memory/batch-update-tier",
        json={"updates": updates},
        tool_name="st memory batch-tier",
    )

    if is_compact():
        _format_batch_tier_compact(result)
    else:
        typer.echo(f"Updated: {result['updated']}/{result['total']}")
        if result.get("failed", 0) > 0:
            typer.echo("Failed updates:")
            for r in result.get("results", []):
                if not r.get("success"):
                    typer.echo(f"  {r['uuid'][:8]}: {r.get('error', 'Unknown')}")


def _format_batch_tier_compact(result: dict[str, Any]) -> None:
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


@app.command("export")
def export_cmd(
    tier: Annotated[
        str | None,
        typer.Option("--tier", "-t", help="Filter by tier (mandate, guardrail, reference)"),
    ] = None,
    limit: Annotated[
        int,
        typer.Option("--limit", "-l", help="Max episodes to export (default: all)"),
    ] = 500,
    uuids: Annotated[
        list[str] | None,
        typer.Argument(help="Specific UUIDs to export (optional)"),
    ] = None,
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Output file (default: stdout)"),
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
    """Export episodes as JSON for batch operations.

    Exports episodes with all fields for editing and re-import.
    Output can be piped to a file or used with --output.

    Examples:
        st memory export --tier reference > references.json
        st memory export --tier reference -o references.json
        st memory export abc12345 def67890 > selected.json
        st memory export --limit 50 | jq '.episodes | length'
    """
    import json as json_lib

    episodes: list[dict[str, Any]] = []

    if uuids:
        result = _agent_hub_request(
            "POST",
            "/api/memory/batch-get",
            json={"uuids": uuids},
            scope=scope,
            scope_id=scope_id,
            tool_name="st memory export",
        )
        episodes = list(result.get("episodes", {}).values())
    else:
        params: dict[str, Any] = {"limit": limit}
        if tier:
            params["category"] = tier

        result = _agent_hub_request(
            "GET",
            "/api/memory/list",
            params=params,
            scope=scope,
            scope_id=scope_id,
            tool_name="st memory export",
        )
        episodes = result.get("episodes", [])

        cursor = result.get("cursor")
        while cursor and len(episodes) < limit:
            params["cursor"] = cursor
            result = _agent_hub_request(
                "GET",
                "/api/memory/list",
                params=params,
                scope=scope,
                scope_id=scope_id,
                tool_name="st memory export",
            )
            episodes.extend(result.get("episodes", []))
            cursor = result.get("cursor")
            if not result.get("has_more"):
                break

    export_data = {
        "exported_at": __import__("datetime").datetime.now().isoformat(),
        "count": len(episodes),
        "episodes": episodes,
    }

    json_output = json_lib.dumps(export_data, indent=2, default=str)

    if output:
        output.write_text(json_output)
        typer.echo(f"Exported {len(episodes)} episodes to {output}")
    else:
        typer.echo(json_output)


@app.command("import")
def import_cmd(
    input_file: Annotated[
        Path,
        typer.Argument(help="JSON file to import (from st memory export)"),
    ],
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Show what would change without applying"),
    ] = False,
) -> None:
    """Import episodes from JSON and update changed fields.

    Reads JSON exported by 'st memory export' and updates episodes
    with any changed fields (summary, trigger_task_types, tier, pinned, etc).

    Examples:
        st memory import references.json
        st memory import --dry-run references.json
    """
    import json as json_lib

    if not input_file.exists():
        output_error(f"File not found: {input_file}")
        raise typer.Exit(1)

    data = json_lib.loads(input_file.read_text())
    episodes = data.get("episodes", [])

    if not episodes:
        typer.echo("No episodes to import")
        return

    updates: list[dict[str, Any]] = []
    for ep in episodes:
        uuid = ep.get("uuid")
        if not uuid:
            continue

        update: dict[str, Any] = {"uuid": uuid}
        if ep.get("injection_tier"):
            update["injection_tier"] = ep["injection_tier"]
        if ep.get("summary") is not None:
            update["summary"] = ep["summary"]
        if ep.get("trigger_task_types") is not None:
            update["trigger_task_types"] = ep["trigger_task_types"]
        if ep.get("pinned") is not None:
            update["pinned"] = ep["pinned"]
        if ep.get("auto_inject") is not None:
            update["auto_inject"] = ep["auto_inject"]
        if ep.get("display_order") is not None:
            update["display_order"] = ep["display_order"]

        if len(update) > 1:
            updates.append(update)

    if dry_run:
        typer.echo(f"DRY RUN: Would update {len(updates)} episodes")
        for u in updates[:10]:
            fields = [k for k in u if k != "uuid"]
            typer.echo(f"  {u['uuid'][:8]}: {', '.join(fields)}")
        if len(updates) > 10:
            typer.echo(f"  ... and {len(updates) - 10} more")
        return

    if not updates:
        typer.echo("No updates needed")
        return

    result = _agent_hub_request(
        "POST",
        "/api/memory/batch-update",
        json={"updates": updates},
        tool_name="st memory import",
    )

    if is_compact():
        updated = result.get("updated", 0)
        failed = result.get("failed", 0)
        typer.echo(f"IMPORT[{len(updates)}]:updated={updated}|failed={failed}")
    else:
        typer.echo(f"Updated: {result.get('updated', 0)}/{result.get('total', 0)}")
        if result.get("failed", 0) > 0:
            typer.echo("Failed updates:")
            for r in result.get("results", []):
                if not r.get("success"):
                    typer.echo(f"  {r['uuid'][:8]}: {r.get('error', 'Unknown')}")


@app.command("cleanup")
def cleanup(
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
    """Clean up memory system.

    Two cleanup modes:
    - --orphaned: Remove edges with stale episode references (Graphiti bug fix)
    - --stale: Remove memories not accessed within TTL period

    Examples:
        st memory cleanup --orphaned
        st memory cleanup --stale --ttl-days 30
        st memory cleanup --orphaned --stale
    """
    if not orphaned and not stale:
        typer.echo("Error: Must specify --orphaned and/or --stale")
        raise typer.Exit(1)

    if orphaned:
        result = _agent_hub_request(
            "POST",
            "/api/memory/cleanup-orphaned",
            scope=scope,
            scope_id=scope_id,
            tool_name="st memory cleanup --orphaned",
        )
        if is_compact():
            _format_orphaned_cleanup_compact(result)
        else:
            output_json(result)

    if stale:
        result = _agent_hub_request(
            "POST",
            f"/api/memory/cleanup?ttl_days={ttl_days}",
            scope=scope,
            scope_id=scope_id,
            tool_name="st memory cleanup --stale",
        )
        if is_compact():
            _format_stale_cleanup_compact(result)
        else:
            output_json(result)


def _format_orphaned_cleanup_compact(result: dict[str, Any]) -> None:
    """Format orphaned edge cleanup results in TOON style."""
    updated = result.get("edges_updated", 0)
    deleted = result.get("edges_deleted", 0)
    stale_refs = result.get("stale_refs_removed", 0)
    error = result.get("error")

    if error:
        print(f"CLEANUP:FAIL:{error}")
    else:
        print(f"ORPHANED:updated={updated}|deleted={deleted}|stale_refs={stale_refs}")


def _format_stale_cleanup_compact(result: dict[str, Any]) -> None:
    """Format stale memory cleanup results in TOON style."""
    deleted = result.get("deleted", 0)
    skipped = result.get("skipped", False)
    reason = result.get("reason")

    if skipped:
        print(f"STALE:SKIP:{reason or 'unknown'}")
    else:
        print(f"STALE:deleted={deleted}")
