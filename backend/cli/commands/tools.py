"""Tools command - View operator catalog and Agent Hub usage metrics."""

from __future__ import annotations

import os
from typing import Annotated, Any, cast

import httpx
import typer

from ..config import get_agent_hub_url
from ..lib.usage import (
    VALID_MANIFEST_DENSITIES,
    collect_usage_specs,
    filter_specs,
    render_inject,
    select_specs_for_density,
    usage,
)
from ..output import output_error, output_json
from ..output_context import OutputContext
from ..tool_registry import list_operator_tools, tool_registry_path
from ._api_paths import ACCESS_CONTROL_METRICS_PATH
from ._http_errors import parse_error_detail, raise_connect_error, raise_timeout_error

app = typer.Typer(help="Operator tool catalog and Agent Hub usage metrics")

_ST_COMMAND_RE = r"(^|&&\s*|;\s*)st(\s|$)"
_ST_SURFACE_RE = r"(^|&&\s*|;\s*)st\s+(?:(?:-P|--project)\s+\S+\s+)?([a-z][a-z0-9-]*)"
_ST_CHECK_RE = r"(^|&&\s*|;\s*)st\s+(?:(?:-P|--project)\s+\S+\s+)?check\b"
_RAW_QUALITY_RE = (
    r"(^|&&\s*|;\s*)"
    r"(pytest|python[0-9.]*\s+-m\s+pytest|ruff|mypy|ty|npx\s+biome|biome|"
    r"npx\s+tsc|tsc|vitest|pnpm\s+(exec\s+)?vitest)\b"
)
_RAW_VCS_RE = (
    r"(^|&&\s*|;\s*)(git|jj)\s+"
    r"(status|diff|show|log|commit|checkout|reset|push|pull|rebase|merge|branch)\b"
)
_RAW_DB_RE = r"(^|&&\s*|;\s*)(psql|pgcli)\b"
_RAW_SERVICE_RE = (
    r"(^|&&\s*|;\s*)"
    r"(systemctl|service|docker-compose|docker\s+(compose\s+)?"
    r"(restart|reload|start|stop|build|up|down))\b"
)
_RAW_AUDIT_RULES = (
    {
        "finding_type": "raw_quality_tool_bypass",
        "expected_surface": "st.check",
        "component": "sf.quality",
        "severity": "high",
        "pattern": _RAW_QUALITY_RE,
    },
    {
        "finding_type": "raw_vcs_tool_bypass",
        "expected_surface": "st.vcs/st.commit",
        "component": "sf.worktree",
        "severity": "medium",
        "pattern": _RAW_VCS_RE,
    },
    {
        "finding_type": "raw_db_tool_bypass",
        "expected_surface": "st.db",
        "component": "sf.cli",
        "severity": "high",
        "pattern": _RAW_DB_RE,
    },
    {
        "finding_type": "raw_service_tool_bypass",
        "expected_surface": "st.service.rebuild",
        "component": "sf.workflows",
        "severity": "high",
        "pattern": _RAW_SERVICE_RE,
    },
)


def _rough_tokens(text: str) -> int:
    """Cheap context-cost estimate for governance summaries."""
    return max(1, round(len(text) / 4))


def _build_internal_headers() -> dict[str, str]:
    """Build env-backed internal headers for read-only Agent Hub admin surfaces."""
    secret = os.getenv("INTERNAL_SERVICE_SECRET", "").strip()
    if not secret:
        output_error(
            "INTERNAL_SERVICE_SECRET is not configured. "
            "st tools requires the shared internal Agent Hub auth header."
        )
        raise typer.Exit(1) from None
    return {"X-Agent-Hub-Internal": secret}


def _handle_response(response: httpx.Response, agent_hub_url: str) -> dict[str, Any]:
    """Validate and parse a successful HTTP response."""
    if response.status_code >= 400:
        detail = parse_error_detail(response)
        output_error(f"API error ({response.status_code}): {detail}")
        raise typer.Exit(1) from None
    return cast(dict[str, Any], response.json())


def _api_request(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Make request to Agent Hub admin API."""
    agent_hub_url = get_agent_hub_url()
    headers = _build_internal_headers()
    url = f"{agent_hub_url}{path}"

    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.get(url, params=params, headers=headers)
            return _handle_response(response, agent_hub_url)
    except httpx.ConnectError as e:
        raise_connect_error("Agent Hub", agent_hub_url, e)
    except httpx.TimeoutException as e:
        raise_timeout_error("Agent Hub", agent_hub_url, 30.0, e)
    except typer.Exit:
        raise
    except Exception as e:
        output_error(f"Request failed: {e}")
        raise typer.Exit(1) from None


def _format_status_compact(data: dict[str, Any]) -> None:
    """Format tool status in TOON style."""
    summary = data.get("summary", {})
    by_endpoint = data.get("by_endpoint", [])
    by_tool_type = data.get("by_tool_type", [])
    by_tool_name = data.get("by_tool_name", [])

    total = summary.get("total_requests", 0)
    success_rate = summary.get("success_rate", 100.0)
    avg_latency = summary.get("avg_latency_ms", 0)

    print(f"TOOLS[24h]:requests={total} success={success_rate:.1f}% latency={avg_latency:.0f}ms")

    if by_tool_type:
        parts = [f"{t['tool_type']}={t['count']}" for t in by_tool_type]
        print(f"  By type: {' '.join(parts)}")

    if by_tool_name:
        print("  Top tools:")
        for tool in by_tool_name[:5]:
            name = str(tool.get("tool_name") or "?")[:40]
            count = tool.get("count", 0)
            rate = tool.get("success_rate", 100.0)
            latency = tool.get("avg_latency_ms", 0)
            print(f"    {name}  {count} reqs  {rate:.1f}%  {latency:.0f}ms")

    if by_endpoint:
        print("  Top endpoints:")
        for ep in by_endpoint[:5]:
            endpoint = ep.get("endpoint", "?")[:40]
            count = ep.get("count", 0)
            rate = ep.get("success_rate", 100.0)
            latency = ep.get("avg_latency_ms", 0)
            print(f"    {endpoint}  {count} reqs  {rate:.1f}%  {latency:.0f}ms")


def _fetch_adoption_metrics(hours: int, limit: int) -> dict[str, Any]:
    """Summarize agent shell-tool events from Agent Hub session_events."""
    import psycopg

    from .db import _db_url, _psql_project_lock

    summary_sql = """
        WITH tool_cmds AS (
            SELECT COALESCE(tool_input->>'cmd', tool_input->>'command') AS command
            FROM session_events
            WHERE created_at >= now() - (%s * interval '1 hour')
              AND tool_name IN ('Bash', 'bash', 'exec_command')
              AND COALESCE(tool_input->>'cmd', tool_input->>'command') IS NOT NULL
        )
        SELECT
            count(*)::int AS shell_tool_events,
            count(*) FILTER (WHERE command ~ %s)::int AS st_commands,
            count(*) FILTER (WHERE command ~ %s)::int AS raw_quality_commands
        FROM tool_cmds;
    """
    top_st_sql = """
        WITH tool_cmds AS (
            SELECT COALESCE(tool_input->>'cmd', tool_input->>'command') AS command
            FROM session_events
            WHERE created_at >= now() - (%s * interval '1 hour')
              AND tool_name IN ('Bash', 'bash', 'exec_command')
              AND COALESCE(tool_input->>'cmd', tool_input->>'command') IS NOT NULL
              AND COALESCE(tool_input->>'cmd', tool_input->>'command') ~ %s
        )
        SELECT 'st ' || lower((regexp_match(command, %s))[2]) AS surface,
               count(*)::int AS count
        FROM tool_cmds
        WHERE regexp_match(command, %s) IS NOT NULL
        GROUP BY surface
        ORDER BY count DESC, surface
        LIMIT %s;
    """
    with (
        _psql_project_lock("agent-hub"),
        psycopg.connect(
            _db_url("agent-hub"),
            application_name="st-tools-adoption",
        ) as conn,
    ):
        summary_row = cast(
            tuple[int, int, int] | None,
            conn.execute(summary_sql, (hours, _ST_COMMAND_RE, _RAW_QUALITY_RE)).fetchone(),
        )
        top_st_rows = cast(
            list[tuple[str, int]],
            conn.execute(
                top_st_sql,
                (hours, _ST_COMMAND_RE, _ST_SURFACE_RE, _ST_SURFACE_RE, limit),
            ).fetchall(),
        )
        top_st = [{"surface": surface, "count": count} for surface, count in top_st_rows]

    shell_events, st_commands, raw_quality = summary_row or (0, 0, 0)
    st_rate = (st_commands / shell_events * 100.0) if shell_events else 0.0
    return {
        "window_hours": hours,
        "summary": {
            "shell_tool_events": shell_events,
            "st_commands": st_commands,
            "st_command_rate": st_rate,
            "raw_quality_commands": raw_quality,
        },
        "top_st_surfaces": top_st,
    }


def _format_adoption_compact(data: dict[str, Any]) -> None:
    summary = data.get("summary", {})
    hours = data.get("window_hours", 24)
    shell_events = int(summary.get("shell_tool_events") or 0)
    st_commands = int(summary.get("st_commands") or 0)
    st_rate = float(summary.get("st_command_rate") or 0.0)
    raw_quality = int(summary.get("raw_quality_commands") or 0)
    print(
        f"TOOLS_ADOPTION[{hours}h]:shell={shell_events} "
        f"st={st_commands} st_rate={st_rate:.1f}% raw_quality={raw_quality}"
    )
    top_st = data.get("top_st_surfaces", [])
    if top_st:
        print("  Top st surfaces:")
        for item in top_st[:10]:
            print(f"    {item.get('surface', '?')}  {item.get('count', 0)}")


def _fetch_audit_metrics(hours: int, limit: int, project: str | None = None) -> dict[str, Any]:
    """Find high-confidence tool-governance misses from Agent Hub telemetry."""
    import psycopg

    from .db import _db_url, _psql_project_lock

    raw_sql = """
        WITH tool_cmds AS (
            SELECT
                e.session_id,
                e.created_at,
                s.project_id,
                s.agent_slug,
                COALESCE(e.tool_input->>'cmd', e.tool_input->>'command') AS command
            FROM session_events e
            LEFT JOIN sessions s ON s.id = e.session_id
            WHERE e.created_at >= now() - (%s * interval '1 hour')
              AND e.tool_name IN ('Bash', 'bash', 'exec_command')
              AND COALESCE(e.tool_input->>'cmd', e.tool_input->>'command') IS NOT NULL
              AND (%s::text IS NULL OR s.project_id = %s)
        )
        SELECT
            %s::text AS finding_type,
            %s::text AS expected_surface,
            %s::text AS component,
            %s::text AS severity,
            COALESCE(project_id, 'unknown') AS project_id,
            COALESCE(agent_slug, 'unknown') AS agent_slug,
            count(*)::int AS count,
            (array_agg(left(command, 160) ORDER BY created_at DESC))[1:3] AS examples,
            (array_agg(session_id ORDER BY created_at DESC))[1:3] AS session_ids
        FROM tool_cmds
        WHERE command !~* %s AND command ~* %s
        GROUP BY project_id, agent_slug
        ORDER BY count DESC, project_id, agent_slug
        LIMIT %s;
    """
    missing_gate_sql = """
        WITH flags AS (
            SELECT
                e.session_id,
                max(s.project_id) AS project_id,
                max(s.agent_slug) AS agent_slug,
                max(s.status::text) AS status,
                max(e.created_at) AS latest_event,
                bool_or(e.tool_name IN (
                    'Edit', 'Write', 'MultiEdit', 'edit_file', 'write_file', 'apply_patch'
                )) AS wrote_files,
                bool_or(
                    COALESCE(e.tool_input->>'cmd', e.tool_input->>'command', '') ~* %s
                ) AS ran_st_check
            FROM session_events e
            LEFT JOIN sessions s ON s.id = e.session_id
            WHERE e.created_at >= now() - (%s * interval '1 hour')
              AND (%s::text IS NULL OR s.project_id = %s)
            GROUP BY e.session_id
        )
        SELECT
            'missing_quality_gate'::text AS finding_type,
            'st.check'::text AS expected_surface,
            'sf.quality'::text AS component,
            'medium'::text AS severity,
            COALESCE(project_id, 'unknown') AS project_id,
            COALESCE(agent_slug, 'unknown') AS agent_slug,
            count(*)::int AS count,
            (array_agg(session_id ORDER BY latest_event DESC))[1:3] AS examples,
            (array_agg(session_id ORDER BY latest_event DESC))[1:3] AS session_ids
        FROM flags
        WHERE wrote_files AND NOT ran_st_check AND status IN ('completed', 'failed')
        GROUP BY project_id, agent_slug
        ORDER BY count DESC, project_id, agent_slug
        LIMIT %s;
    """

    findings: list[dict[str, Any]] = []
    with (
        _psql_project_lock("agent-hub"),
        psycopg.connect(
            _db_url("agent-hub"),
            application_name="st-tools-audit",
        ) as conn,
    ):
        for rule in _RAW_AUDIT_RULES:
            rows = conn.execute(
                raw_sql,
                (
                    hours,
                    project,
                    project,
                    rule["finding_type"],
                    rule["expected_surface"],
                    rule["component"],
                    rule["severity"],
                    _ST_COMMAND_RE,
                    rule["pattern"],
                    limit,
                ),
            ).fetchall()
            findings.extend(_audit_rows_to_findings(rows))

        rows = conn.execute(
            missing_gate_sql,
            (_ST_CHECK_RE, hours, project, project, limit),
        ).fetchall()
        findings.extend(_audit_rows_to_findings(rows))

    severity_rank = {"high": 0, "medium": 1, "low": 2}
    findings.sort(key=lambda item: (severity_rank.get(item["severity"], 9), -item["count"]))
    findings = findings[:limit]
    by_type: dict[str, int] = {}
    for item in findings:
        by_type[item["finding_type"]] = by_type.get(item["finding_type"], 0) + item["count"]
    return {
        "window_hours": hours,
        "project": project,
        "summary": {
            "finding_groups": len(findings),
            "events": sum(item["count"] for item in findings),
            "by_type": [{"finding_type": key, "count": count} for key, count in by_type.items()],
        },
        "findings": findings,
    }


def _audit_rows_to_findings(rows: list[tuple[Any, ...]]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for (
        finding_type,
        expected_surface,
        component,
        severity,
        project_id,
        agent_slug,
        count,
        examples,
        session_ids,
    ) in rows:
        findings.append(
            {
                "finding_type": str(finding_type),
                "expected_surface": str(expected_surface),
                "component": str(component),
                "severity": str(severity),
                "project_id": str(project_id),
                "agent_slug": str(agent_slug),
                "count": int(count),
                "examples": [str(item) for item in examples or []],
                "session_ids": [str(item) for item in session_ids or []],
            }
        )
    return findings


def _format_audit_compact(data: dict[str, Any]) -> None:
    summary = data.get("summary", {})
    hours = data.get("window_hours", 24)
    groups = int(summary.get("finding_groups") or 0)
    events = int(summary.get("events") or 0)
    print(f"TOOLS_AUDIT[{hours}h]:findings={groups} events={events}")
    findings = data.get("findings", [])
    if not findings:
        print("  No high-confidence tool-governance findings.")
        return
    for item in findings:
        print(
            f"  {item.get('severity', '?')}|{item.get('finding_type', '?')}"
            f"|expected={item.get('expected_surface', '?')}|count={item.get('count', 0)}"
            f"|project={item.get('project_id', '?')}|agent={item.get('agent_slug', '?')}"
        )
        for example in item.get("examples", [])[:2]:
            print(f"    ex: {example}")


def _emit_feedback_for_audit(data: dict[str, Any]) -> None:
    from .feedback_commands import report_impl

    hours = int(data.get("window_hours") or 24)
    for item in data.get("findings", []):
        examples = "; ".join(str(example) for example in item.get("examples", [])[:2])
        description = (
            f"{item.get('count', 0)} event(s) in {hours}h. "
            f"Expected surface: {item.get('expected_surface', '?')}. "
            f"Examples: {examples or 'none captured'}"
        )
        project_id = str(item.get("project_id") or data.get("project") or "summitflow")
        if project_id == "unknown":
            project_id = str(data.get("project") or "summitflow")
        agent_slug = str(item.get("agent_slug") or "")
        report_impl(
            str(item.get("component") or "xc.tool_registry"),
            f"Tool governance: {str(item.get('finding_type', 'missed_tool')).replace('_', ' ')}",
            feedback_type="friction",
            severity=str(item.get("severity") or "medium"),
            description=description,
            project_id=project_id,
            session_id=(item.get("session_ids") or [None])[0],
            agent_slug=agent_slug if agent_slug != "unknown" else None,
            vote_if_duplicate=True,
        )


def _manifest_density_costs(task: str | None) -> list[dict[str, Any]]:
    from ..main import app as root_app

    specs = collect_usage_specs(root_app)
    costs: list[dict[str, Any]] = []
    for density in VALID_MANIFEST_DENSITIES:
        density_task = task if density == "task" else None
        selected = select_specs_for_density(specs, density=density, task_type=density_task)
        rendered = render_inject(selected)
        costs.append(
            {
                "density": density,
                "task": density_task,
                "surfaces": len(selected),
                "chars": len(rendered),
                "tokens_approx": _rough_tokens(rendered),
            }
        )
    return costs


def _fetch_cost_metrics(hours: int, limit: int, task: str | None = "verification") -> dict[str, Any]:
    """Summarize context and persisted tool/request token cost hotspots."""
    import psycopg

    from .db import _db_url, _psql_project_lock

    request_sql = """
        SELECT
            COALESCE(tool_name, endpoint, 'unknown') AS tool_name,
            COALESCE(tool_type::text, 'unknown') AS tool_type,
            count(*)::int AS requests,
            COALESCE(sum(tokens_in), 0)::int AS tokens_in,
            COALESCE(sum(tokens_out), 0)::int AS tokens_out,
            COALESCE(avg(latency_ms), 0)::float AS avg_latency_ms,
            COALESCE(
                count(*) FILTER (WHERE status_code BETWEEN 200 AND 399) * 100.0
                / NULLIF(count(*), 0),
                0
            )::float AS success_rate
        FROM request_logs
        WHERE created_at >= now() - (%s * interval '1 hour')
        GROUP BY 1, 2
        ORDER BY (COALESCE(sum(tokens_in), 0) + COALESCE(sum(tokens_out), 0)) DESC,
                 count(*) DESC,
                 tool_name
        LIMIT %s;
    """
    output_sql = """
        SELECT
            COALESCE(tool_name, 'unknown') AS tool_name,
            count(*)::int AS events,
            COALESCE(sum(tokens), 0)::int AS stored_tokens,
            COALESCE(sum(length(COALESCE(tool_output::text, content, ''))), 0)::int AS output_chars,
            COALESCE(avg(duration_ms), 0)::float AS avg_duration_ms
        FROM session_events
        WHERE created_at >= now() - (%s * interval '1 hour')
          AND tool_name IS NOT NULL
        GROUP BY 1
        ORDER BY output_chars DESC, events DESC, tool_name
        LIMIT %s;
    """
    request_rows: list[tuple[Any, ...]]
    output_rows: list[tuple[Any, ...]]
    with (
        _psql_project_lock("agent-hub"),
        psycopg.connect(
            _db_url("agent-hub"),
            application_name="st-tools-cost",
        ) as conn,
    ):
        request_rows = conn.execute(request_sql, (hours, limit)).fetchall()
        output_rows = conn.execute(output_sql, (hours, limit)).fetchall()

    request_hotspots = [
        {
            "tool_name": str(tool_name),
            "tool_type": str(tool_type),
            "requests": int(requests),
            "tokens_in": int(tokens_in),
            "tokens_out": int(tokens_out),
            "avg_latency_ms": float(avg_latency_ms),
            "success_rate": float(success_rate),
        }
        for (
            tool_name,
            tool_type,
            requests,
            tokens_in,
            tokens_out,
            avg_latency_ms,
            success_rate,
        ) in request_rows
    ]
    output_hotspots = [
        {
            "tool_name": str(tool_name),
            "events": int(events),
            "stored_tokens": int(stored_tokens),
            "output_chars": int(output_chars),
            "output_tokens_approx": max(0, round(int(output_chars) / 4)),
            "avg_duration_ms": float(avg_duration_ms),
        }
        for tool_name, events, stored_tokens, output_chars, avg_duration_ms in output_rows
    ]
    return {
        "window_hours": hours,
        "manifest_costs": _manifest_density_costs(task),
        "request_hotspots": request_hotspots,
        "tool_output_hotspots": output_hotspots,
    }


def _format_cost_compact(data: dict[str, Any]) -> None:
    hours = data.get("window_hours", 24)
    costs = {item["density"]: item for item in data.get("manifest_costs", [])}
    core = costs.get("core", {})
    task = costs.get("task", {})
    full = costs.get("full", {})
    saved = int(full.get("tokens_approx") or 0) - int(core.get("tokens_approx") or 0)
    task_name = task.get("task") or "-"
    print(
        f"TOOLS_COST[{hours}h]:manifest_core~{core.get('tokens_approx', 0)}t "
        f"task({task_name})~{task.get('tokens_approx', 0)}t "
        f"full~{full.get('tokens_approx', 0)}t saved_core_vs_full~{saved}t"
    )
    request_hotspots = data.get("request_hotspots", [])
    if request_hotspots:
        print("  Request token hotspots:")
        for item in request_hotspots[:10]:
            print(
                f"    {item.get('tool_name', '?')}|{item.get('tool_type', '?')}"
                f" reqs={item.get('requests', 0)}"
                f" in={item.get('tokens_in', 0)} out={item.get('tokens_out', 0)}"
                f" success={float(item.get('success_rate') or 0):.1f}%"
            )
    output_hotspots = data.get("tool_output_hotspots", [])
    if output_hotspots:
        print("  Tool output hotspots:")
        for item in output_hotspots[:10]:
            print(
                f"    {item.get('tool_name', '?')} events={item.get('events', 0)}"
                f" out~{item.get('output_tokens_approx', 0)}t"
                f" chars={item.get('output_chars', 0)}"
            )


def _emit_feedback_for_cost(data: dict[str, Any]) -> None:
    from .feedback_commands import report_impl

    costs = {item["density"]: item for item in data.get("manifest_costs", [])}
    core_tokens = int(costs.get("core", {}).get("tokens_approx") or 0)
    full_tokens = int(costs.get("full", {}).get("tokens_approx") or 0)
    saved = full_tokens - core_tokens
    if saved < 500:
        return
    report_impl(
        "xc.tool_registry",
        "Tool governance: compact manifest saves prompt tokens",
        feedback_type="improvement",
        severity="medium",
        description=(
            f"Core density is ~{core_tokens} tokens versus full density ~{full_tokens}; "
            f"estimated saving is ~{saved} tokens per compact injection."
        ),
        project_id="summitflow",
        vote_if_duplicate=True,
    )


def _format_catalog_compact(tools: list[dict[str, Any]]) -> None:
    """Format operator tools in compact TOON style."""
    print(f"TOOLS_CATALOG[{len(tools)}]:source={tool_registry_path()}")
    for tool in tools:
        canonical = tool.get("canonical", "?")
        replaces = ",".join(str(item) for item in tool.get("replaces", []) if item)
        safety = tool.get("safety", "?")
        summary = str(tool.get("summary", "")).strip()
        print(f"  {canonical}|safety:{safety}|replaces:{replaces}|{summary}")


@app.command()
def catalog(ctx: typer.Context) -> None:
    """Show canonical st operator tools from the shared registry."""
    tools = list_operator_tools()
    if ctx.obj.is_compact:
        _format_catalog_compact(tools)
    else:
        output_json({"source": str(tool_registry_path()), "tools": tools})


@app.command()
@usage(
    surface="st.tools.status",
    cmd="st tools status",
    when="inspect Agent Hub API/CLI usage metrics and top command names",
    task_types=("verification", "devops"),
)
def status(
    ctx: typer.Context,
    hours: Annotated[int, typer.Option("--hours", "-h", help="Hours to look back")] = 24,
    limit: Annotated[int, typer.Option("--limit", "-l", help="Max endpoints to show")] = 10,
) -> None:
    """Show tool/API usage metrics.

    Displays aggregated metrics from request_logs:
    - Total requests, success rate, average latency
    - Breakdown by tool type (api/cli/sdk)
    - Top tools by request count
    - Top endpoints by request count

    Examples:
        st tools status
        st tools status --hours 1
        st tools status --limit 20
    """
    result = _api_request(
        ACCESS_CONTROL_METRICS_PATH,
        params={"hours": hours, "limit": limit},
    )

    if ctx.obj.is_compact:
        _format_status_compact(result)
    else:
        output_json(result)


@app.command()
@usage(
    surface="st.tools.adoption",
    cmd="st tools adoption",
    when="audit whether recent agent shell commands use st wrappers instead of raw quality tools",
    precautions=("read-only Agent Hub session_events summary",),
    task_types=("verification", "devops"),
)
def adoption(
    ctx: typer.Context,
    hours: Annotated[int, typer.Option("--hours", "-h", help="Hours to look back")] = 24,
    limit: Annotated[int, typer.Option("--limit", "-l", help="Max st surfaces to show")] = 10,
) -> None:
    """Show agent st-wrapper adoption from persisted session_events."""
    result = _fetch_adoption_metrics(hours, limit)
    if ctx.obj.is_compact:
        _format_adoption_compact(result)
    else:
        output_json(result)


@app.command()
@usage(
    surface="st.tools.audit",
    cmd="st tools audit",
    when="surface high-confidence missed st usage from persisted Agent Hub session telemetry",
    precautions=("deterministic rules only; use --emit-feedback to file deduped feedback items",),
    task_types=("verification", "devops", "prompt-tuning"),
)
def audit(
    ctx: typer.Context,
    hours: Annotated[int, typer.Option("--hours", "-h", help="Hours to look back")] = 24,
    limit: Annotated[int, typer.Option("--limit", "-l", help="Max finding groups to show")] = 10,
    project: Annotated[
        str | None,
        typer.Option("--project", "-P", help="Limit findings to one Agent Hub project_id"),
    ] = None,
    emit_feedback: Annotated[
        bool,
        typer.Option("--emit-feedback", help="Create/vote feedback items for surfaced findings"),
    ] = False,
) -> None:
    """Audit recent agent sessions for high-confidence missed st tool usage."""
    result = _fetch_audit_metrics(hours, limit, project)
    if ctx.obj.is_compact:
        _format_audit_compact(result)
        if emit_feedback:
            _emit_feedback_for_audit(result)
    else:
        output_json(result)


@app.command()
@usage(
    surface="st.tools.cost",
    cmd="st tools cost",
    when="inspect context/tool-output/request token cost hotspots for st tool governance",
    precautions=("uses existing Agent Hub request_logs and session_events; estimates text tokens cheaply",),
    task_types=("verification", "devops", "prompt-tuning"),
)
def cost(
    ctx: typer.Context,
    hours: Annotated[int, typer.Option("--hours", "-h", help="Hours to look back")] = 24,
    limit: Annotated[int, typer.Option("--limit", "-l", help="Max hotspots to show")] = 10,
    task: Annotated[
        str | None,
        typer.Option("--task", help="Task type used for task-density manifest cost"),
    ] = "verification",
    emit_feedback: Annotated[
        bool,
        typer.Option("--emit-feedback", help="Create/vote feedback for actionable cost findings"),
    ] = False,
) -> None:
    """Show tool-governance token/cost hotspots from existing telemetry."""
    result = _fetch_cost_metrics(hours, limit, task)
    if ctx.obj.is_compact:
        _format_cost_compact(result)
        if emit_feedback:
            _emit_feedback_for_cost(result)
    else:
        output_json(result)


def _emit_manifest_markdown(payload: dict[str, Any]) -> None:
    for tool in payload["tools"]:
        print(f"### `{tool['surface']}`")
        if tool.get("cmd"):
            print(f"- **cmd**: `{tool['cmd']}`")
        if tool.get("when"):
            print(f"- **when**: {tool['when']}")
        if tool.get("why"):
            print(f"- **why**: {tool['why']}")
        if tool.get("precautions"):
            print("- **precautions**:")
            for item in tool["precautions"]:
                print(f"  - {item}")
        if tool.get("examples"):
            print("- **examples**:")
            for item in tool["examples"]:
                print(f"  - `{item}`")
        print()


def _emit_manifest_yaml(payload: dict[str, Any]) -> None:
    import yaml

    print(yaml.safe_dump(payload, default_flow_style=False, sort_keys=False).strip())


@app.command()
def manifest(
    ctx: typer.Context,
    surface: Annotated[
        str | None, typer.Option("--surface", help="Filter to one surface (e.g., st.service.rebuild)")
    ] = None,
    task: Annotated[
        str | None, typer.Option("--task", help="Filter to surfaces declaring this task_type")
    ] = None,
    agent: Annotated[
        str | None, typer.Option("--agent", help="Filter to surfaces declaring this agent_slug")
    ] = None,
    profile: Annotated[
        str | None, typer.Option("--profile", help="Filter to surfaces declaring this consumer_profile")
    ] = None,
    density: Annotated[
        str, typer.Option("--density", help="core | task | full")
    ] = "full",
    fmt: Annotated[
        str, typer.Option("--format", help="inject | yaml | json | markdown")
    ] = "inject",
) -> None:
    """Emit the registered tool-usage manifest for injection into agentic surfaces.

    Source of truth is the `@usage(...)` decorator on each Typer command.
    Default `inject` is the token-optimal grouped form for context injection.
    Examples:
        st tools manifest --task devops                    # inject form (default)
        st tools manifest --density core                   # compact generic context
        st tools manifest --task frontend --density task    # compact task context
        st tools manifest --surface st.service.rebuild --format yaml
        st tools manifest --profile claude-code --format json
    """
    from ..main import app as root_app

    if density not in VALID_MANIFEST_DENSITIES:
        expected = "|".join(VALID_MANIFEST_DENSITIES)
        output_error(f"Unknown --density {density!r}; expected {expected}")
        raise typer.Exit(1)

    all_specs = collect_usage_specs(root_app)
    if surface is not None:
        specs = filter_specs(
            all_specs,
            surface=surface,
            task_type=task,
            agent_slug=agent,
            consumer_profile=profile,
        )
    else:
        specs = filter_specs(all_specs, agent_slug=agent, consumer_profile=profile)
        if density == "full":
            specs = filter_specs(specs, task_type=task)
        else:
            specs = select_specs_for_density(specs, density=density, task_type=task)

    if fmt == "inject":
        print(render_inject(specs))
        return
    payload: dict[str, Any] = {
        "manifest_version": 1,
        "density": density,
        "tools": [spec.to_dict() for spec in specs],
    }
    if fmt == "json":
        output_json(payload)
    elif fmt == "markdown":
        _emit_manifest_markdown(payload)
    elif fmt == "yaml":
        _emit_manifest_yaml(payload)
    else:
        output_error(f"Unknown --format {fmt!r}; expected inject|yaml|json|markdown")
        raise typer.Exit(1)


@app.callback(invoke_without_command=True)
def tools_default(ctx: typer.Context) -> None:
    """Show operator catalog by default."""
    if ctx.obj is None:
        ctx.obj = OutputContext()
    if ctx.invoked_subcommand is None:
        catalog(ctx)
