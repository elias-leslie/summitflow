"""Tools command - View operator catalog and Agent Hub usage metrics."""

from __future__ import annotations

import os
from typing import Annotated, Any, cast

import httpx
import typer
from psycopg import sql

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

from .tools_dependencies import app as dependencies_app  # noqa: E402

app.add_typer(dependencies_app, name="dependencies")


@app.command("extensions")
@usage(
    surface="st.tools.extensions",
    cmd="st tools extensions [--check]",
    when="inspect trusted extension registrations or diagnose owner installation",
    precautions=("Default is passive metadata only; --check queries the ST project registry and checks executable files without running extensions. Prerequisites present does not prove runtime health.",),
)
def extensions(
    check: Annotated[bool, typer.Option("--check", help="Check registered project and executable prerequisites without running owner code.")] = False,
) -> None:
    """Show localized extension diagnostics as JSON; discovery never executes owners."""
    from ..extensions import extension_diagnostics
    from ..main import app as root_app

    output_json(extension_diagnostics(cast(Any, root_app)._st_extensions, check=check))

DEFAULT_LOOKBACK_HOURS = 24
DEFAULT_LIMIT = 10
DEFAULT_COST_TASK = "verification"
DEFAULT_FEEDBACK_PROJECT = "summitflow"
DEFAULT_MANIFEST_VERSION = 1
INJECT_FORMAT = "inject"
JSON_FORMAT = "json"
MARKDOWN_FORMAT = "markdown"
YAML_FORMAT = "yaml"

_ST_COMMAND_RE = r"(^|&&\s*|;\s*)st(\s|$)"
_ST_SURFACE_RE = r"(^|&&\s*|;\s*)st\s+(?:(?:-P|--project)\s+\S+\s+)?([a-z][a-z0-9-]*)"
_ST_CHECK_RE = r"(^|&&\s*|;\s*)st\s+(?:(?:-P|--project)\s+\S+\s+)?check\b"
_RAW_QUALITY_RE = (
    r"(^|&&\s*|;\s*)"
    r"(pytest|python[0-9.]*\s+-m\s+pytest|ruff|mypy|ty|npx\s+biome|biome|"
    r"npx\s+tsc|tsc|vitest|pnpm\s+(exec\s+)?vitest)\b"
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


def _format_status_compact(data: dict[str, Any], *, hours: int = 24) -> None:
    """Format tool status in TOON style."""
    summary = data.get("summary", {})
    by_endpoint = data.get("by_endpoint", [])
    by_tool_type = data.get("by_tool_type", [])
    by_tool_name = data.get("by_tool_name", [])

    total = summary.get("total_requests", 0)
    success_rate = summary.get("success_rate", 100.0)
    avg_latency = summary.get("avg_latency_ms", 0)

    print(f"TOOLS[{hours}h]:http_requests={total} http_success={success_rate:.1f}% latency={avg_latency:.0f}ms")

    if by_tool_type:
        parts = [f"{t['tool_type']}={t['count']}" for t in by_tool_type]
        print(f"  By type: {' '.join(parts)}")

    if by_tool_name:
        print("  Top tools (HTTP outcome):")
        for tool in by_tool_name[:5]:
            name = str(tool.get("tool_name") or "?")[:40]
            count = tool.get("count", 0)
            rate = tool.get("success_rate", 100.0)
            latency = tool.get("avg_latency_ms", 0)
            print(f"    {name}  {count} reqs  http_success={rate:.1f}%  {latency:.0f}ms")

    if by_endpoint:
        print("  Top endpoints (HTTP outcome):")
        for ep in by_endpoint[:5]:
            endpoint = ep.get("endpoint", "?")[:40]
            count = ep.get("count", 0)
            rate = ep.get("success_rate", 100.0)
            latency = ep.get("avg_latency_ms", 0)
            print(f"    {endpoint}  {count} reqs  http_success={rate:.1f}%  {latency:.0f}ms")


def _fetch_adoption_metrics(hours: int, limit: int, session: str | None = None) -> dict[str, Any]:
    """Summarize agent shell-tool events from Agent Hub session_events."""
    import psycopg

    from .db import _db_url, _psql_project_lock

    summary_sql = """
        WITH tool_cmds AS (
            SELECT COALESCE(tool_input->>'cmd', tool_input->>'command') AS command
            FROM session_events
            WHERE created_at >= now() - (%s * interval '1 hour')
              AND (%s::text IS NULL OR session_id = %s)
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
              AND (%s::text IS NULL OR session_id = %s)
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
    native_hints_sql = """
        SELECT
            count(*) FILTER (WHERE tool_input->'native_tool_hints' ? 'web__run')::int,
            count(*) FILTER (WHERE tool_input->'native_tool_hints' ? 'mcp__cua_repl.js')::int
        FROM session_events
        WHERE created_at >= now() - (%s * interval '1 hour')
          AND (%s::text IS NULL OR session_id = %s);
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
            conn.execute(summary_sql, (hours, session, session, _ST_COMMAND_RE, _RAW_QUALITY_RE)).fetchone(),
        )
        top_st_rows = cast(
            list[tuple[str, int]],
            conn.execute(
                top_st_sql,
                (hours, session, session, _ST_COMMAND_RE, _ST_SURFACE_RE, _ST_SURFACE_RE, limit),
            ).fetchall(),
        )
        top_st = [{"surface": surface, "count": count} for surface, count in top_st_rows]
        native_hints = conn.execute(native_hints_sql, (hours, session, session)).fetchone()

    shell_events, st_commands, raw_quality = summary_row or (0, 0, 0)
    st_rate = (st_commands / shell_events * 100.0) if shell_events else None
    return {
        "window_hours": hours,
        "session": session,
        "summary": {
            "shell_tool_events": shell_events,
            "st_commands": st_commands,
            "st_command_rate": st_rate,
            "raw_quality_commands": raw_quality,
            "native_web_hints": int(native_hints[0]) if native_hints else 0,
            "native_browser_hints": int(native_hints[1]) if native_hints else 0,
        },
        "top_st_surfaces": top_st,
    }


def _format_adoption_compact(data: dict[str, Any]) -> None:
    summary = data.get("summary", {})
    hours = data.get("window_hours", 24)
    shell_events = int(summary.get("shell_tool_events") or 0)
    st_commands = int(summary.get("st_commands") or 0)
    measured_rate = summary.get("st_command_rate")
    st_rate = f"{float(measured_rate):.1f}%" if measured_rate is not None else "unknown"
    raw_quality = int(summary.get("raw_quality_commands") or 0)
    print(
        f"TOOLS_ADOPTION[{hours}h]:shell={shell_events} "
        f"st={st_commands} st_rate={st_rate} raw_quality={raw_quality}"
    )
    if shell_events == 0:
        print("  No inspectable shell commands recorded; capture completeness unknown.")
    web_hints = int(summary.get("native_web_hints") or 0)
    browser_hints = int(summary.get("native_browser_hints") or 0)
    print(f"  Native tool hints: web={web_hints} browser={browser_hints} (permitted; outside ST rate)")
    if data.get("session"):
        print(f"  Session filter: {data['session']}")
    top_st = data.get("top_st_surfaces", [])
    if top_st:
        print("  Top st surfaces:")
        for item in top_st[:10]:
            print(f"    {item.get('surface', '?')}  {item.get('count', 0)}")


def _audit_queries(hours: int, project: str | None, limit: int, session: str | None = None) -> tuple[sql.SQL, sql.SQL, tuple[Any, ...], tuple[Any, ...]]:
    raw_sql = sql.SQL("""
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
              AND (%s::text IS NULL OR e.session_id = %s)
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
    """)
    missing_gate_sql = sql.SQL("""
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
              AND (%s::text IS NULL OR e.session_id = %s)
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
        WHERE wrote_files AND NOT ran_st_check AND status = 'completed'
          AND agent_slug IS NOT NULL AND agent_slug != 'unknown'
        GROUP BY project_id, agent_slug
        ORDER BY count DESC, project_id, agent_slug
        LIMIT %s;
    """)
    return (
        raw_sql,
        missing_gate_sql,
        (hours, project, project, session, session),
        (_ST_CHECK_RE, hours, project, project, session, session, limit),
    )


def _fetch_audit_metrics(hours: int, limit: int, project: str | None = None, session: str | None = None) -> dict[str, Any]:
    """Find high-confidence tool-governance misses from Agent Hub telemetry."""
    import psycopg

    from .db import _db_url, _psql_project_lock

    raw_sql, missing_gate_sql, raw_base_params, missing_gate_params = _audit_queries(hours, project, limit, session)
    coverage_sql = """
        SELECT count(*)::int,
               count(*) FILTER (
                   WHERE e.tool_name IN ('Bash', 'bash', 'exec_command')
                     AND COALESCE(e.tool_input->>'cmd', e.tool_input->>'command') IS NOT NULL
               )::int,
               count(DISTINCT e.session_id)::int,
               count(*) FILTER (WHERE e.tool_input->'native_tool_hints' ? 'web__run')::int,
               count(*) FILTER (WHERE e.tool_input->'native_tool_hints' ? 'mcp__cua_repl.js')::int
        FROM session_events e
        LEFT JOIN sessions s ON s.id = e.session_id
        WHERE e.created_at >= now() - (%s * interval '1 hour')
          AND (%s::text IS NULL OR s.project_id = %s)
          AND (%s::text IS NULL OR e.session_id = %s)
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
                (*raw_base_params,
                 rule["finding_type"],
                 rule["expected_surface"],
                 rule["component"],
                 rule["severity"],
                 _ST_COMMAND_RE,
                 rule["pattern"],
                 limit),
            ).fetchall()
            findings.extend(_audit_rows_to_findings(rows))

        rows = conn.execute(missing_gate_sql, missing_gate_params).fetchall()
        findings.extend(_audit_rows_to_findings(rows))
        coverage = conn.execute(
            coverage_sql, (hours, project, project, session, session)
        ).fetchone()

    severity_rank = {"high": 0, "medium": 1, "low": 2}
    findings.sort(key=lambda item: (severity_rank.get(item["severity"], 9), -item["count"]))
    findings = findings[:limit]
    by_type: dict[str, int] = {}
    for item in findings:
        by_type[item["finding_type"]] = by_type.get(item["finding_type"], 0) + item["count"]
    return {
        "window_hours": hours,
        "project": project,
        "session": session,
        "summary": {
            "finding_groups": len(findings),
            "events": sum(item["count"] for item in findings),
            "observed_events": int(coverage[0]) if coverage else None,
            "inspected_shell_events": int(coverage[1]) if coverage else None,
            "observed_sessions": int(coverage[2]) if coverage else None,
            "native_web_hints": int(coverage[3]) if coverage else None,
            "native_browser_hints": int(coverage[4]) if coverage else None,
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
    inspected = summary.get("inspected_shell_events")
    inspected_text = str(inspected) if inspected is not None else "unknown"
    observed = summary.get("observed_events")
    observed_text = str(observed) if observed is not None else "unknown"
    print(f"TOOLS_AUDIT[{hours}h]:findings={groups} finding_events={events} inspected_shell={inspected_text} observed={observed_text}")
    if summary.get("native_web_hints") is not None or summary.get("native_browser_hints") is not None:
        print(
            "  Permitted native tool hints: "
            f"web={summary.get('native_web_hints') or 0} "
            f"browser={summary.get('native_browser_hints') or 0}"
        )
    if inspected == 0:
        print("  No inspectable shell commands recorded; capture completeness is unknown.")
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


def _find_exact_active_feedback(
    *,
    component_id: str,
    feedback_type: str,
    title: str,
) -> dict[str, Any] | None:
    from .feedback_api import feedback_request
    from .feedback_helpers import FEEDBACK_API_PATH, build_filter_params

    result = feedback_request(
        "GET",
        FEEDBACK_API_PATH,
        params=build_filter_params(
            "votes",
            200,
            component_id=component_id,
            feedback_type=feedback_type,
            status="active",
        ),
    )
    for item in result.get("items", []):
        if str(item.get("title") or "").casefold() == title.casefold():
            return cast(dict[str, Any], item)
    return None


def _report_or_vote_feedback(
    component_id: str,
    title: str,
    *,
    feedback_type: str,
    severity: str | None,
    description: str,
    project_id: str,
    session_id: str | None,
    agent_slug: str | None = None,
) -> None:
    from .feedback_api import feedback_request
    from .feedback_commands import report_impl
    from .feedback_formatters import output_feedback_deduped, output_feedback_existing
    from .feedback_helpers import ALREADY_VOTED_MSG, FEEDBACK_API_PATH, build_vote_body

    existing = _find_exact_active_feedback(
        component_id=component_id,
        feedback_type=feedback_type,
        title=title,
    )
    if existing:
        item_id = str(existing.get("id") or "")
        if session_id and item_id:
            vote = feedback_request(
                "POST",
                f"{FEEDBACK_API_PATH}/{item_id}/vote",
                json=build_vote_body(
                    session_id,
                    comment=description,
                    agent_slug=agent_slug,
                    model_used=None,
                ),
            )
            refreshed = feedback_request("GET", f"{FEEDBACK_API_PATH}/{item_id}")
            if vote.get("message") == ALREADY_VOTED_MSG:
                output_feedback_existing(refreshed)
            else:
                output_feedback_deduped(refreshed)
            return
        output_feedback_existing(existing)
        return

    report_impl(
        component_id,
        title,
        feedback_type=feedback_type,
        severity=severity,
        description=description,
        project_id=project_id,
        session_id=session_id,
        agent_slug=agent_slug,
        vote_if_duplicate=True,
    )


def _emit_feedback_for_audit(data: dict[str, Any]) -> None:
    hours = int(data.get("window_hours") or 24)
    grouped: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for item in data.get("findings", []):
        key = (
            str(item.get("component") or "xc.tool_registry"),
            str(item.get("finding_type") or "missed_tool"),
            str(item.get("expected_surface") or "?"),
            str(item.get("severity") or "medium"),
        )
        bucket = grouped.setdefault(
            key,
            {
                "count": 0,
                "projects": {},
                "examples": [],
                "session_id": None,
                "agent_slug": None,
            },
        )
        bucket["count"] += int(item.get("count") or 0)
        projects = cast(dict[str, int], bucket["projects"])
        project_id = str(item.get("project_id") or "unknown")
        projects[project_id] = projects.get(project_id, 0) + int(item.get("count") or 0)
        examples = cast(list[str], bucket["examples"])
        examples.extend(str(example) for example in item.get("examples", [])[:2])
        if bucket["session_id"] is None:
            bucket["session_id"] = (item.get("session_ids") or [None])[0]
        agent_slug = str(item.get("agent_slug") or "")
        if bucket["agent_slug"] is None and agent_slug and agent_slug != "unknown":
            bucket["agent_slug"] = agent_slug

    for (component, finding_type, expected_surface, severity), bucket in grouped.items():
        projects = cast(dict[str, int], bucket["projects"])
        examples = cast(list[str], bucket["examples"])
        project_summary = ", ".join(f"{project}:{count}" for project, count in sorted(projects.items()))
        example_summary = "; ".join(examples[:3])
        description = (
            f"{bucket.get('count', 0)} event(s) in {hours}h. "
            f"Expected surface: {expected_surface}. "
            f"Projects: {project_summary or 'none captured'}. "
            f"Examples: {example_summary or 'none captured'}"
        )
        _report_or_vote_feedback(
            component,
            f"Tool governance: {finding_type.replace('_', ' ')}",
            feedback_type="friction",
            severity=severity,
            description=description,
            project_id=str(data.get("project") or "summitflow"),
            session_id=cast(str | None, bucket.get("session_id")),
            agent_slug=cast(str | None, bucket.get("agent_slug")),
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


def _cost_queries(hours: int, limit: int) -> tuple[sql.SQL, sql.SQL]:
    request_sql = sql.SQL("""
        SELECT
            COALESCE(tool_name, endpoint, 'unknown') AS tool_name,
            COALESCE(tool_type::text, 'unknown') AS tool_type,
            count(*)::int AS requests,
            sum(tokens_in)::bigint AS tokens_in,
            sum(tokens_out)::bigint AS tokens_out,
            COALESCE(avg(latency_ms), 0)::float AS avg_latency_ms,
            COALESCE(
                count(*) FILTER (WHERE status_code BETWEEN 200 AND 399) * 100.0
                / NULLIF(count(*), 0),
                0
            )::float AS success_rate,
            count(tokens_in)::int AS tokens_in_samples,
            count(tokens_out)::int AS tokens_out_samples
        FROM request_logs
        WHERE created_at >= now() - (%s * interval '1 hour')
          AND (%s::text IS NULL OR session_id = %s)
        GROUP BY 1, 2
        ORDER BY (COALESCE(sum(tokens_in), 0) + COALESCE(sum(tokens_out), 0)) DESC,
                 count(*) DESC,
                 tool_name
        LIMIT %s;
    """)
    output_sql = sql.SQL("""
        SELECT
            COALESCE(tool_name, 'unknown') AS tool_name,
            count(*)::int AS events,
            sum(tokens)::bigint AS stored_tokens,
            sum(length(output_text))::int AS output_chars,
            COALESCE(avg(duration_ms), 0)::float AS avg_duration_ms,
            count(output_text)::int AS output_samples,
            count(tokens)::int AS stored_tokens_samples,
            count(*) FILTER (WHERE output_text IS NULL AND tokens IS NULL)::int AS unmeasured_events
        FROM (
            SELECT tool_name, tokens, duration_ms,
                COALESCE(NULLIF(tool_output::text, 'null'), content) AS output_text
            FROM session_events
            WHERE created_at >= now() - (%s * interval '1 hour')
              AND (%s::text IS NULL OR session_id = %s)
              AND tool_name IS NOT NULL
        ) AS measured_outputs
        GROUP BY 1
        ORDER BY output_chars DESC NULLS LAST, events DESC, tool_name
        LIMIT %s;
    """)
    return request_sql, output_sql


def _native_usage_query() -> sql.SQL:
    """Keep per-response usage separate from cumulative counter observations."""
    return sql.SQL("""
        SELECT
            usage->>'scope' AS scope,
            COALESCE(usage->>'source', 'unknown') AS source,
            count(*)::int AS events,
            sum((usage->>'input_tokens')::bigint) FILTER (WHERE event_type = 'usage') AS input_tokens,
            sum((usage->>'output_tokens')::bigint) FILTER (WHERE event_type = 'usage') AS output_tokens,
            sum((usage->>'cached_input_tokens')::bigint) FILTER (WHERE event_type = 'usage') AS cached_input_tokens,
            sum((usage->>'cache_write_input_tokens')::bigint) FILTER (WHERE event_type = 'usage') AS cache_write_input_tokens,
            sum((usage->>'reasoning_output_tokens')::bigint) FILTER (WHERE event_type = 'usage') AS reasoning_output_tokens,
            count(usage->>'input_tokens') FILTER (WHERE event_type = 'usage')::int AS input_samples,
            count(usage->>'output_tokens') FILTER (WHERE event_type = 'usage')::int AS output_samples,
            count(usage->>'cached_input_tokens') FILTER (WHERE event_type = 'usage')::int AS cached_samples,
            count(usage->>'cache_write_input_tokens') FILTER (WHERE event_type = 'usage')::int AS cache_write_samples,
            count(usage->>'reasoning_output_tokens') FILTER (WHERE event_type = 'usage')::int AS reasoning_samples
        FROM session_events
        WHERE event_type IN ('usage', 'usage_counter')
          AND usage IS NOT NULL
          AND COALESCE(source_timestamp, created_at) >= now() - (%s * interval '1 hour')
          AND (%s::text IS NULL OR session_id = %s)
        GROUP BY 1, 2
        ORDER BY (usage->>'scope' = 'response') DESC, events DESC, source;
    """)


def _fetch_cost_metrics(hours: int, limit: int, task: str | None = DEFAULT_COST_TASK, session: str | None = None) -> dict[str, Any]:
    """Summarize context and persisted tool/request token cost hotspots."""
    import psycopg

    from .db import _db_url, _psql_project_lock

    request_sql, output_sql = _cost_queries(hours, limit)
    request_rows: list[tuple[Any, ...]]
    output_rows: list[tuple[Any, ...]]
    native_rows: list[tuple[Any, ...]]
    with (
        _psql_project_lock("agent-hub"),
        psycopg.connect(
            _db_url("agent-hub"),
            application_name="st-tools-cost",
        ) as conn,
    ):
        request_rows = conn.execute(request_sql, (hours, session, session, limit)).fetchall()
        output_rows = conn.execute(output_sql, (hours, session, session, limit)).fetchall()
        native_rows = conn.execute(_native_usage_query(), (hours, session, session)).fetchall()

    request_hotspots = [
        {
            "tool_name": str(tool_name),
            "tool_type": str(tool_type),
            "requests": int(requests),
            "tokens_in": int(tokens_in) if tokens_in is not None else None,
            "tokens_out": int(tokens_out) if tokens_out is not None else None,
            "tokens_in_samples": int(tokens_in_samples),
            "tokens_out_samples": int(tokens_out_samples),
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
            tokens_in_samples,
            tokens_out_samples,
        ) in request_rows
    ]
    output_hotspots = [
        {
            "tool_name": str(tool_name),
            "events": int(events),
            "stored_tokens": int(stored_tokens) if stored_tokens is not None else None,
            "output_chars": int(output_chars) if output_chars is not None else None,
            "output_tokens_approx": max(0, round(int(output_chars) / 4)) if output_chars is not None else None,
            "avg_duration_ms": float(avg_duration_ms),
            "output_samples": int(output_samples),
            "stored_tokens_samples": int(stored_tokens_samples),
            "unmeasured_events": int(unmeasured_events),
        }
        for (
            tool_name, events, stored_tokens, output_chars, avg_duration_ms,
            output_samples, stored_tokens_samples, unmeasured_events,
        ) in output_rows
    ]
    native_usage = [
        {
            "scope": str(scope), "source": str(source), "events": int(events),
            "input_tokens": input_tokens, "output_tokens": output_tokens,
            "cached_input_tokens": cached_input_tokens,
            "cache_write_input_tokens": cache_write_input_tokens,
            "reasoning_output_tokens": reasoning_output_tokens,
            "input_tokens_samples": int(input_samples), "output_tokens_samples": int(output_samples),
            "cached_input_tokens_samples": int(cached_samples),
            "cache_write_input_tokens_samples": int(cache_write_samples),
            "reasoning_output_tokens_samples": int(reasoning_samples),
        }
        for (
            scope, source, events, input_tokens, output_tokens, cached_input_tokens,
            cache_write_input_tokens, reasoning_output_tokens, input_samples,
            output_samples, cached_samples, cache_write_samples, reasoning_samples,
        ) in native_rows
    ]
    return {
        "window_hours": hours,
        "session": session,
        "manifest_costs": _manifest_density_costs(task),
        "request_hotspots": request_hotspots,
        "tool_output_hotspots": output_hotspots,
        "native_usage": native_usage,
    }


def _token_measurement(item: dict[str, Any], field: str) -> str:
    value = item.get(field)
    if value is None:
        return "unknown"
    samples, requests = item.get(f"{field}_samples"), item.get("requests", item.get("events"))
    if samples is not None and requests is not None and samples < requests:
        return f"{value}[{samples}/{requests} measured]"
    return str(value)


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
    print("  Manifest figures estimate generated text; billed cost unknown.")
    if data.get("session"):
        print(f"  Session filter: {data['session']}")
    request_hotspots = data.get("request_hotspots", [])
    if request_hotspots:
        print("  HTTP request telemetry (task outcome unknown):")
        for item in request_hotspots[:10]:
            print(
                f"    {item.get('tool_name', '?')}|{item.get('tool_type', '?')}"
                f" reqs={item.get('requests', 0)}"
                f" in={_token_measurement(item, 'tokens_in')} out={_token_measurement(item, 'tokens_out')}"
                f" http_success={float(item.get('success_rate') or 0):.1f}%"
            )
    output_hotspots = data.get("tool_output_hotspots", [])
    if output_hotspots:
        print("  Tool output hotspots:")
        for item in output_hotspots[:10]:
            estimate = item.get("output_tokens_approx")
            output = "out=unknown" if estimate is None else f"out~{estimate}t"
            print(
                f"    {item.get('tool_name', '?')} events={item.get('events', 0)}"
                f" {output}"
                f" chars={_token_measurement(item, 'output_chars')}"
                f" measured={item.get('output_samples', 'unknown')}/{item.get('events', 0)}"
                f" stored={_token_measurement(item, 'stored_tokens')}"
                f" missing={item.get('unmeasured_events', 'unknown')}"
            )
    native_usage = data.get("native_usage", [])
    if native_usage:
        print("  Native usage (source timestamps; field coverage shown):")
        for item in native_usage:
            scope = item.get("scope", "unknown")
            source = item.get("source", "unknown")
            if scope != "response":
                print(f"    cumulative counters: {scope}/{source} observations={item.get('events', 0)}; totals excluded")
                continue
            print(
                f"    native per-response {source} responses={item.get('events', 0)}"
                f" in={_token_measurement(item, 'input_tokens')}"
                f" out={_token_measurement(item, 'output_tokens')}"
                f" cached={_token_measurement(item, 'cached_input_tokens')}"
                f" cache_write={_token_measurement(item, 'cache_write_input_tokens')}"
                f" reasoning={_token_measurement(item, 'reasoning_output_tokens')}"
            )
    else:
        print("  Native usage: unavailable in this window; missing data is not zero.")


def _emit_feedback_for_cost(data: dict[str, Any]) -> None:
    """Retain CLI compatibility without inferring waste from aggregate telemetry."""
    print("  No feedback emitted: request HTTP status and aggregate output do not establish task waste.")


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
    task_types=("tool-governance", "prompt-tuning",),
    on_demand="tool telemetry",
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
        _format_status_compact(result, hours=hours)
    else:
        output_json(result)


@app.command()
@usage(
    surface="st.tools.adoption",
    cmd="st tools adoption",
    when="audit whether recent agent shell commands use st wrappers instead of raw quality tools",
    precautions=("read-only Agent Hub session_events summary",),
    task_types=("tool-governance", "prompt-tuning",),
    on_demand="tool telemetry",
)
def adoption(
    ctx: typer.Context,
    hours: Annotated[int, typer.Option("--hours", "-h", help="Hours to look back")] = 24,
    limit: Annotated[int, typer.Option("--limit", "-l", help="Max st surfaces to show")] = 10,
    session: Annotated[str | None, typer.Option("--session", help="Limit to one Agent Hub session ID")] = None,
) -> None:
    """Show agent st-wrapper adoption from persisted session_events."""
    result = _fetch_adoption_metrics(hours, limit, session)
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
    task_types=("tool-governance", "prompt-tuning",),
    on_demand="tool telemetry",
)
def audit(
    ctx: typer.Context,
    hours: Annotated[int, typer.Option("--hours", "-h", help="Hours to look back")] = 24,
    limit: Annotated[int, typer.Option("--limit", "-l", help="Max finding groups to show")] = 10,
    project: Annotated[
        str | None,
        typer.Option("--project", "-P", help="Limit findings to one Agent Hub project_id"),
    ] = None,
    session: Annotated[
        str | None,
        typer.Option("--session", help="Limit findings to one Agent Hub session ID"),
    ] = None,
    emit_feedback: Annotated[
        bool,
        typer.Option("--emit-feedback", help="Create/vote feedback items for surfaced findings"),
    ] = False,
) -> None:
    """Audit recent agent sessions for high-confidence missed st tool usage."""
    result = _fetch_audit_metrics(hours, limit, project, session)
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
    task_types=("tool-governance", "prompt-tuning",),
    on_demand="tool telemetry",
)
def cost(
    ctx: typer.Context,
    hours: Annotated[int, typer.Option("--hours", "-h", help="Hours to look back")] = 24,
    limit: Annotated[int, typer.Option("--limit", "-l", help="Max hotspots to show")] = 10,
    task: Annotated[
        str | None,
        typer.Option("--task", help="Task type used for task-density manifest cost"),
    ] = "verification",
    session: Annotated[
        str | None,
        typer.Option("--session", help="Limit recorded requests and events to one session ID"),
    ] = None,
    emit_feedback: Annotated[
        bool,
        typer.Option("--emit-feedback", help="Explain why aggregate-cost feedback is disabled"),
    ] = False,
) -> None:
    """Show tool-governance token/cost hotspots from existing telemetry."""
    result = _fetch_cost_metrics(hours, limit, task, session)
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


def _load_scores_file(scores_file: str | None) -> dict[str, float] | None:
    """Load a {usage_key: score} map for adaptive density. Fail-soft to None.

    A missing/unreadable/malformed file never errors the manifest — adaptive then
    falls back to floor + task surfaces only.
    """
    if not scores_file:
        return None
    try:
        import json
        import sys

        if scores_file == "-":
            raw = sys.stdin.read()
        else:
            with open(scores_file, encoding="utf-8") as handle:
                raw = handle.read()
        data = json.loads(raw)
        if not isinstance(data, dict):
            return None
        out: dict[str, float] = {}
        for key, value in data.items():
            try:
                out[str(key)] = float(value)
            except (TypeError, ValueError):
                continue
        return out or None
    except Exception:
        return None


def _manifest_specs(
    root_app: typer.Typer,
    *,
    surface: str | None,
    task: str | None,
    agent: str | None,
    profile: str | None,
    density: str,
    scores: dict[str, float] | None = None,
) -> list[Any]:
    all_specs = collect_usage_specs(root_app)
    if surface is not None:
        return filter_specs(
            all_specs,
            surface=surface,
            task_type=task,
            agent_slug=agent,
            consumer_profile=profile,
        )
    specs = filter_specs(all_specs, agent_slug=agent, consumer_profile=profile)
    if density == "full":
        return filter_specs(specs, task_type=task)
    return select_specs_for_density(specs, density=density, task_type=task, scores=scores)


def _emit_manifest_payload(
    specs: list[Any],
    *,
    density: str,
    fmt: str,
) -> None:
    if fmt == INJECT_FORMAT:
        print(render_inject(specs))
        return
    payload: dict[str, Any] = {
        "manifest_version": DEFAULT_MANIFEST_VERSION,
        "density": density,
        "tools": [spec.to_dict() for spec in specs],
    }
    if fmt == JSON_FORMAT:
        output_json(payload)
    elif fmt == MARKDOWN_FORMAT:
        _emit_manifest_markdown(payload)
    elif fmt == YAML_FORMAT:
        _emit_manifest_yaml(payload)
    else:
        output_error(f"Unknown --format {fmt!r}; expected {INJECT_FORMAT}|{YAML_FORMAT}|{JSON_FORMAT}|{MARKDOWN_FORMAT}")
        raise typer.Exit(1)


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
        str | None, typer.Option("--density", help="core | task | full | adaptive; default core (task with --task)")
    ] = None,
    fmt: Annotated[
        str, typer.Option("--format", help="inject | yaml | json | markdown")
    ] = INJECT_FORMAT,
    scores_file: Annotated[
        str | None,
        typer.Option(
            "--scores-file",
            help="JSON {usage_key: 0-100 score} for --density adaptive ('-' for stdin)",
        ),
    ] = None,
) -> None:
    """Emit the registered tool-usage manifest for injection into agentic surfaces.

    Source of truth is the `@usage(...)` decorator on each Typer command.
    Default output is a compact `core` discovery slice in the grouped inject form.
    An explicit --task defaults to task density; --density full exports everything.
    Examples:
        st tools manifest                                 # compact generic context
        st tools manifest --task devops                    # task-specific context
        st tools manifest --density full                   # complete export
        st tools manifest --task frontend --density task    # compact task context
        st tools manifest --density adaptive --scores-file scores.json
        st tools manifest --surface st.service.rebuild --format yaml
        st tools manifest --profile claude-code --format json
    """
    from ..main import app as root_app

    density = density or ("task" if task else "core")

    if density not in VALID_MANIFEST_DENSITIES:
        expected = "|".join(VALID_MANIFEST_DENSITIES)
        output_error(f"Unknown --density {density!r}; expected {expected}")
        raise typer.Exit(1)

    scores = _load_scores_file(scores_file)

    known_surfaces = [spec.surface for spec in collect_usage_specs(root_app)] if surface else []
    if surface and surface not in known_surfaces:
        matches = [name for name in known_surfaces if name.endswith(f".{surface}")]
        if len(matches) == 1:
            surface = matches[0]
        elif len(matches) > 1:
            output_error(f"Ambiguous --surface {surface!r}; choose one of: {', '.join(matches)}")
            raise typer.Exit(1)

    specs = _manifest_specs(
        root_app,
        surface=surface,
        task=task,
        agent=agent,
        profile=profile,
        density=density,
        scores=scores,
    )
    if surface is not None and not specs:
        from difflib import get_close_matches

        nearby = get_close_matches(surface, known_surfaces, n=3)
        hint = f" Did you mean: {', '.join(nearby)}?" if nearby else ""
        output_error(
            f"Unknown or filtered --surface {surface!r}.{hint} "
            "Use st tools manifest --density full to list registered surfaces."
        )
        raise typer.Exit(1)
    _emit_manifest_payload(specs, density=density, fmt=fmt)


@app.callback(invoke_without_command=True)
def tools_default(ctx: typer.Context) -> None:
    """Show operator catalog by default."""
    if ctx.obj is None:
        ctx.obj = OutputContext()
    if ctx.invoked_subcommand is None:
        catalog(ctx)
