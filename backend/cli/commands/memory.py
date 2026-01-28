"""Memory commands for the CLI - interact with Agent Hub memory system."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any, cast

import httpx
import typer

from ..output import is_compact, output_error, output_json

app = typer.Typer(help="Memory system commands (Agent Hub)")

# Agent Hub API base URL
AGENT_HUB_URL = "http://localhost:8003"


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

    url = f"{AGENT_HUB_URL}{path}"

    try:
        with httpx.Client(timeout=30.0) as client:
            if method == "GET":
                response = client.get(url, params=params, headers=headers)
            elif method == "DELETE":
                response = client.delete(url, headers=headers)
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
        output_error("Cannot connect to Agent Hub at localhost:8003")
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

    Examples:
        st memory save "Always use async for DB operations" --tier reference
        st memory save "NEVER modify node_modules" --tier guardrail --confidence 95
        st memory save "Use TIMESTAMPTZ for dates" --tier mandate --confidence 100
    """
    if tier not in ("mandate", "guardrail", "reference"):
        output_error(f"Invalid tier: {tier}. Must be mandate, guardrail, or reference.")
        raise typer.Exit(1)

    if confidence < 0 or confidence > 100:
        output_error(f"Invalid confidence: {confidence}. Must be 0-100.")
        raise typer.Exit(1)

    payload: dict[str, Any] = {
        "content": content,
        "injection_tier": tier,
        "confidence": confidence,
    }
    if context:
        payload["context"] = context

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
    uuid: Annotated[
        str,
        typer.Argument(help="Episode UUID to retrieve"),
    ],
) -> None:
    """Get details for a single episode by UUID.

    Returns full episode information including usage statistics
    (helpful_count, harmful_count, loaded_count, referenced_count).

    Examples:
        st memory get abc12345-full-uuid-here
    """
    result = _agent_hub_request(
        "GET",
        f"/api/memory/episode/{uuid}",
        tool_name="st memory get",
    )

    if "detail" in result:
        # Handle error response
        output_error(result["detail"])
        raise typer.Exit(1)

    if is_compact():
        _format_get_compact(result)
    else:
        output_json(result)


def _format_get_compact(result: dict[str, Any]) -> None:
    """Format single episode details in compact mode."""
    uuid_short = result.get("uuid", "")[:8]
    tier = result.get("injection_tier", "unknown")
    content = result.get("content", "")[:60]
    helpful = result.get("helpful_count", 0)
    harmful = result.get("harmful_count", 0)
    loaded = result.get("loaded_count", 0)
    referenced = result.get("referenced_count", 0)

    # First line: UUID, tier, content preview
    typer.echo(f"{uuid_short} [{tier}] {content}...")
    # Second line: usage stats
    typer.echo(
        f"  Stats: loaded={loaded} referenced={referenced} helpful={helpful} harmful={harmful}"
    )


@app.command()
def delete(
    uuids: Annotated[
        list[str],
        typer.Argument(help="Episode UUID(s) to delete"),
    ],
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="Skip confirmation prompt"),
    ] = False,
) -> None:
    """Delete one or more episodes from memory.

    Removes episodes and cleans up orphaned entities/edges
    that were only connected through these episodes.

    Examples:
        st memory delete abc12345-uuid
        st memory delete uuid1 uuid2 uuid3 --yes
    """
    if not yes:
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
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="Skip confirmation prompt"),
    ] = False,
) -> None:
    """Update an episode (delete + recreate).

    Note: Graphiti has no native update - this deletes and recreates.
    Usage stats (helpful_count, harmful_count, etc.) will be RESET.

    Examples:
        st memory update abc12345 --content "New content here"
        st memory update abc12345 --tier mandate
        st memory update abc12345 --content "New" --tier guardrail --yes
    """
    if not content and not tier:
        typer.echo("Error: Must specify --content and/or --tier")
        raise typer.Exit(1)

    # Get existing episode details
    existing = _agent_hub_request("GET", f"/api/memory/episode/{uuid}", tool_name="st memory update")
    if "detail" in existing:
        typer.echo(f"Error: {existing['detail']}")
        raise typer.Exit(1)

    old_tier = existing.get("injection_tier", "reference")
    old_content = existing.get("content", "")

    new_content = content if content else old_content
    new_tier = tier if tier else old_tier

    if not yes:
        typer.echo("WARNING: Update will RESET usage stats (helpful_count, etc.)")
        typer.echo(f"  UUID: {uuid[:8]}...")
        typer.echo(f"  Tier: {old_tier} -> {new_tier}")
        if content:
            typer.echo(f"  Content: {old_content[:40]}... -> {new_content[:40]}...")

        if not typer.confirm("Proceed with update?"):
            typer.echo("Cancelled.")
            raise typer.Exit(0)

    # Delete existing
    delete_result = _agent_hub_request("DELETE", f"/api/memory/episode/{uuid}", tool_name="st memory update")
    if not delete_result.get("success"):
        typer.echo(f"Error deleting: {delete_result.get('detail', 'Unknown error')}")
        raise typer.Exit(1)

    # Create new
    create_result = _agent_hub_request(
        "POST",
        "/api/memory/add",
        json={
            "content": new_content,
            "name": existing.get("name", "updated_episode"),
            "injection_tier": new_tier,
        },
        tool_name="st memory update",
    )

    new_uuid = create_result.get("uuid")
    if new_uuid:
        typer.echo(f"Updated: {uuid[:8]} -> {new_uuid[:8]}")
        typer.echo(f"  Tier: {new_tier}")
    else:
        typer.echo(f"Error creating new episode: {create_result}")
        raise typer.Exit(1)
