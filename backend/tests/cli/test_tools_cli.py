"""Tests for st tools CLI auth and routing."""

from __future__ import annotations

from typing import cast
from unittest.mock import MagicMock, patch

import httpx
import pytest
from typer.testing import CliRunner

from cli.commands.tools import (
    _api_request,
    _build_internal_headers,
    _format_adoption_compact,
    _format_audit_compact,
    _format_cost_compact,
    _format_status_compact,
    app,
)

runner = CliRunner()


def test_cost_query_measures_real_payloads_not_json_null(test_db_url: str) -> None:
    import psycopg
    from psycopg import sql

    from cli.commands.tools import _cost_queries

    # Shadow the source relation with read-only fixtures; never write a table.
    fixtures = sql.SQL("""
        WITH payloads(session_id, tool_name, tool_output, content, tokens, duration_ms, created_at) AS (
          VALUES
            ('sess-1', 'missing', 'null'::jsonb, NULL::text, NULL::int, 1.0, now()),
            ('sess-1', 'missing', NULL::jsonb, NULL::text, NULL::int, 1.0, now()),
            ('sess-1', 'mixed', 'null'::jsonb, 'abcd', NULL::int, 1.0, now()),
            ('sess-1', 'mixed', NULL::jsonb, NULL::text, 7, 1.0, now()),
            ('sess-1', 'empty', NULL::jsonb, '', 0, 1.0, now()),
            ('sess-2', 'literal', '\"null\"'::jsonb, NULL::text, NULL::int, 1.0, now())
        ), session_events AS (
            SELECT payloads.*, row_number() OVER ()::text AS id, 'tool_result'::text AS event_type,
                   NULL::text AS call_id, NULL::jsonb AS tool_input, NULL::text AS source_event_id,
                   NULL::timestamptz AS source_timestamp
            FROM payloads
        )
    """)
    _, query = _cost_queries(24, 10)
    with psycopg.connect(test_db_url) as connection:
        rows = {row[0]: row[1:8] for row in connection.execute(fixtures + query, (24, None, None, 10)).fetchall()}
    assert rows["missing"] == (2, None, None, 1.0, 0, 0, 2)
    assert rows["mixed"] == (2, 7, 4, 1.0, 1, 1, 0)
    assert rows["empty"] == (1, 0, 0, 1.0, 1, 1, 0)
    assert rows["literal"] == (1, None, 4, 1.0, 1, 0, 0)
    with psycopg.connect(test_db_url) as connection:
        scoped = {row[0] for row in connection.execute(fixtures + query, (24, "sess-1", "sess-1", 10)).fetchall()}
    assert "literal" not in scoped


def test_native_usage_query_separates_response_and_cumulative_evidence(test_db_url: str) -> None:
    import psycopg
    from psycopg import sql

    from cli.commands.tools import _native_usage_query

    fixtures = sql.SQL("""
        WITH payloads(session_id, event_type, usage, source_timestamp, created_at) AS (
          VALUES
            ('sess-1', 'usage', '{"scope":"response","source":"native","input_tokens":10,"output_tokens":0,"cached_input_tokens":4,"cache_write_tokens":2}'::json, now(), now()),
            ('sess-1', 'usage', '{"scope":"response","source":"native","input_tokens":5}'::json, now(), now()),
            ('sess-1', 'usage_counter', '{"scope":"thread","source":"counter","input_tokens":100}'::json, now(), now()),
            ('sess-2', 'usage', '{"scope":"response","source":"native","input_tokens":999}'::json, now(), now()),
            ('sess-1', 'usage', '{"scope":"response","source":"native","input_tokens":999}'::json, now() - interval '2 days', now())
        ), session_events AS (
            SELECT payloads.*, 'codex-model'::text AS model_used FROM payloads
        )
    """)
    with psycopg.connect(test_db_url) as connection:
        rows = connection.execute(fixtures + _native_usage_query(), (24, "sess-1", "sess-1")).fetchall()
    response = next(row for row in rows if row[0] == "response")
    counter = next(row for row in rows if row[0] == "thread")
    assert response[2] == 2
    assert response[3:8] == (15, 0, 4, 2, None)
    assert response[8:13] == (2, 1, 1, 1, 0)
    assert response[13:] == ("codex-model", 4, 1)
    assert counter[2] == 1
    assert counter[3:8] == (None,) * 5
    assert counter[8:13] == (0,) * 5


def test_cost_output_reports_missing_and_partial_coverage(capsys: pytest.CaptureFixture[str]) -> None:
    _format_cost_compact({"tool_output_hotspots": [
        {"tool_name": "missing", "events": 2, "output_chars": None, "output_tokens_approx": None, "output_samples": 0, "stored_tokens": None, "stored_tokens_samples": 0, "unmeasured_events": 2},
        {"tool_name": "mixed", "events": 2, "output_chars": 4, "output_tokens_approx": 1, "output_samples": 1, "stored_tokens": 7, "stored_tokens_samples": 1, "unmeasured_events": 0},
        {"tool_name": "empty", "events": 1, "output_chars": 0, "output_tokens_approx": 0, "output_samples": 1, "stored_tokens": 0, "stored_tokens_samples": 1, "unmeasured_events": 0},
    ]})
    output = capsys.readouterr().out
    assert "out=unknown" in output and "chars=unknown" in output
    assert "measured=0/2" in output and "missing=2" in output
    assert "measured=1/2" in output and "stored=7[1/2 measured]" in output
    assert "out~0t chars=0" in output


def test_cost_output_labels_native_coverage_and_counters(capsys: pytest.CaptureFixture[str]) -> None:
    _format_cost_compact({"native_usage": [
        {"scope": "response", "source": "codex", "events": 2,
         "input_tokens": 15, "output_tokens": 0, "cached_input_tokens": None,
         "cache_write_input_tokens": None, "reasoning_output_tokens": None,
         "input_tokens_samples": 2, "output_tokens_samples": 1,
         "cached_input_tokens_samples": 0, "cache_write_input_tokens_samples": 0,
         "reasoning_output_tokens_samples": 0},
        {"scope": "thread", "source": "counter", "events": 3},
    ]})
    output = capsys.readouterr().out
    assert "native per-response" in output
    assert "in=15" in output and "out=0[1/2 measured]" in output
    assert "cached=unknown" in output
    assert "cumulative counters: thread/counter observations=3" in output
    assert "billed cost unknown" in output


def test_cost_distinguishes_unmeasured_tokens_from_measured_zero() -> None:
    from contextlib import nullcontext
    connection = MagicMock()
    connection.execute.side_effect = [
        MagicMock(fetchall=lambda: [("unmeasured", "cli", 2, None, 0, 12.0, 100.0, 0, 2)]),
        MagicMock(fetchall=lambda: []),
        MagicMock(fetchall=lambda: []),
        MagicMock(fetchone=lambda: ({},)),
    ]
    with (
        patch("psycopg.connect", return_value=nullcontext(connection)),
        patch("cli.commands.db._db_url", return_value="postgresql:///test"),
        patch("cli.commands.db._psql_project_lock", return_value=nullcontext()),
        patch("cli.commands.tools._manifest_density_costs", return_value=[]),
    ):
        result = runner.invoke(app, ["cost"])
    assert result.exit_code == 0, result.output
    assert "in=unknown out=0" in result.output


class _DummyClient:
    """Minimal httpx.Client stand-in that captures request headers."""

    def __init__(self, response: httpx.Response) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    def __enter__(self) -> _DummyClient:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def get(
        self,
        url: str,
        *,
        params: dict[str, object] | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        self.calls.append({"url": url, "params": params, "headers": headers})
        return self.response


def _json_response(payload: dict[str, object]) -> httpx.Response:
    request = httpx.Request("GET", "http://agent-hub.test/api/access-control/metrics")
    return httpx.Response(200, json=payload, request=request)


def test_build_internal_headers_reads_env_secret() -> None:
    with patch.dict("os.environ", {"INTERNAL_SERVICE_SECRET": "secret-123"}, clear=True):
        assert _build_internal_headers() == {"X-Agent-Hub-Internal": "secret-123"}


def test_build_internal_headers_falls_back_to_env_local() -> None:
    with (
        patch.dict("os.environ", {}, clear=True),
        patch("st_sdk.credentials._read_env_local", return_value={"INTERNAL_SERVICE_SECRET": "local-456"}),
    ):
        assert _build_internal_headers() == {"X-Agent-Hub-Internal": "local-456"}


def test_tools_status_requires_internal_secret() -> None:
    with (
        patch.dict("os.environ", {}, clear=True),
        patch("st_sdk.credentials._read_env_local", return_value={}),
    ):
        result = runner.invoke(app, ["status"])

    assert result.exit_code == 1
    assert "Missing INTERNAL_SERVICE_SECRET" in result.output


def test_tools_default_shows_operator_catalog_without_internal_secret() -> None:
    with patch.dict("os.environ", {}, clear=True):
        result = runner.invoke(app, [])

    assert result.exit_code == 0
    assert "TOOLS_CATALOG[" in result.output
    assert "st claim" in result.output
    assert "st service" in result.output
    assert "st graph" in result.output
    assert "st browser" in result.output


def test_tools_catalog_json_includes_registry_source() -> None:
    result = runner.invoke(app, ["catalog"], obj=None)

    assert result.exit_code == 0
    assert "tool-registry.json" in result.output
    assert "st claim" in result.output
    assert "st graph" in result.output
    assert "st browser" in result.output


def test_api_request_uses_env_backed_internal_header() -> None:
    dummy_client = _DummyClient(
        _json_response(
            {
                "summary": {"total_requests": 1, "avg_latency_ms": 5.0, "success_rate": 100.0},
                "by_endpoint": [],
                "by_tool_type": [],
            }
        )
    )

    with (
        patch.dict("os.environ", {"INTERNAL_SERVICE_SECRET": "secret-123"}, clear=True),
        patch("cli.commands.tools.get_agent_hub_url", return_value="http://agent-hub.test"),
        patch("cli.commands.tools.httpx.Client", return_value=dummy_client),
    ):
        result = _api_request("/api/access-control/metrics", params={"hours": 24, "limit": 10})

    assert result["summary"]["total_requests"] == 1
    assert dummy_client.calls == [
        {
            "url": "http://agent-hub.test/api/access-control/metrics",
            "params": {"hours": 24, "limit": 10},
            "headers": {"X-Agent-Hub-Internal": "secret-123"},
        }
    ]


def test_status_compact_includes_top_tool_names(capsys: pytest.CaptureFixture[str]) -> None:
    _format_status_compact(
        {
            "summary": {"total_requests": 3, "avg_latency_ms": 12.0, "success_rate": 100.0},
            "by_tool_type": [{"tool_type": "cli", "count": 3}],
            "by_tool_name": [
                {
                    "tool_name": "st memory search",
                    "count": 2,
                    "success_rate": 100.0,
                    "avg_latency_ms": 9.0,
                }
            ],
            "by_endpoint": [],
        },
        hours=168,
    )

    out = capsys.readouterr().out
    assert "TOOLS[168h]" in out
    assert "Top tools (HTTP outcome):" in out
    assert "st memory search  2 reqs  http_success=100.0%  9ms" in out


def test_adoption_compact_summarizes_st_wrapper_use(capsys: pytest.CaptureFixture[str]) -> None:
    _format_adoption_compact(
        {
            "window_hours": 24,
            "summary": {
                "shell_tool_events": 10,
                "st_commands": 7,
                "st_command_rate": 70.0,
                "raw_quality_commands": 0,
                "native_web_hints": 3,
                "native_browser_hints": 2,
            },
            "top_st_surfaces": [{"surface": "st check", "count": 4}],
        }
    )

    out = capsys.readouterr().out
    assert "TOOLS_ADOPTION[24h]:shell_commands=10 st=7 st_rate=70.0% raw_quality=0" in out
    assert "st check  4" in out
    assert "Native tool hints: web=3 browser=2 (permitted; outside ST rate)" in out


def test_adoption_compact_shows_session_scope_and_missing_capture(capsys: pytest.CaptureFixture[str]) -> None:
    _format_adoption_compact({
        "window_hours": 24,
        "session": "session-1",
        "summary": {"shell_tool_events": 0, "st_commands": 0, "st_command_rate": None},
    })
    out = capsys.readouterr().out
    assert "st_rate=unknown" in out
    assert "capture completeness unknown" in out
    assert "Session filter: session-1" in out


def test_adoption_without_inspectable_shell_events_is_unknown(capsys: pytest.CaptureFixture[str]) -> None:
    _format_adoption_compact({
        "window_hours": 24,
        "summary": {
            "shell_tool_events": 0,
            "st_commands": 0,
            "st_command_rate": None,
            "raw_quality_commands": 0,
        },
        "top_st_surfaces": [],
    })

    out = capsys.readouterr().out
    assert "st_rate=unknown" in out
    assert "capture completeness unknown" in out


def test_audit_compact_surfaces_expected_tool_findings(capsys: pytest.CaptureFixture[str]) -> None:
    _format_audit_compact(
        {
            "window_hours": 24,
            "summary": {
                "finding_groups": 1, "events": 2,
                "native_web_hints": 3, "native_browser_hints": 2,
            },
            "findings": [
                {
                    "severity": "high",
                    "finding_type": "raw_quality_tool_bypass",
                    "expected_surface": "st.check",
                    "count": 2,
                    "project_id": "summitflow",
                    "agent_slug": "worker",
                    "examples": ["pytest backend/tests/foo.py"],
                }
            ],
        }
    )

    out = capsys.readouterr().out
    assert "TOOLS_AUDIT[24h]:findings=1 finding_events=2" in out
    assert "raw_quality_tool_bypass|expected=st.check|count=2" in out
    assert "Permitted native tool hints: web=3 browser=2" in out
    assert "ex: pytest backend/tests/foo.py" in out


def test_audit_rules_do_not_classify_git_inspection_as_waste() -> None:
    from cli.commands.tools import _RAW_AUDIT_RULES

    assert not any(rule["finding_type"] == "raw_vcs_tool_bypass" for rule in _RAW_AUDIT_RULES)


def test_audit_reports_findings_without_filing_anything(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "cli.commands.tools._fetch_audit_metrics",
        lambda hours, limit, project, session: {
            "window_hours": hours,
            "summary": {"finding_groups": 1, "events": 2, "inspected_shell_events": 5},
            "findings": [
                {
                    "finding_type": "raw_quality_tool_bypass",
                    "expected_surface": "st.check",
                    "severity": "high",
                    "count": 2,
                    "project_id": "summitflow",
                    "agent_slug": "worker",
                    "examples": ["pytest backend/tests/foo.py"],
                }
            ],
        },
    )

    result = runner.invoke(app, ["audit"])

    assert result.exit_code == 0
    assert "raw_quality_tool_bypass|expected=st.check|count=2" in result.output
    assert "feedback" not in result.output.casefold()


@pytest.mark.parametrize("command", ["audit", "cost"])
def test_tools_governance_commands_no_longer_accept_emit_feedback(command: str) -> None:
    result = runner.invoke(app, [command, "--emit-feedback"])

    assert result.exit_code != 0
    assert "No such option" in result.output


def test_cost_compact_shows_manifest_and_hotspots(capsys: pytest.CaptureFixture[str]) -> None:
    _format_cost_compact(
        {
            "window_hours": 24,
            "manifest_costs": [
                {"density": "core", "task": None, "tokens_approx": 100},
                {"density": "task", "task": "verification", "tokens_approx": 160},
                {"density": "full", "task": None, "tokens_approx": 400},
            ],
            "request_hotspots": [
                {
                    "tool_name": "sdk.complete",
                    "tool_type": "sdk",
                    "requests": 2,
                    "tokens_in": 300,
                    "tokens_out": 50,
                    "success_rate": 100.0,
                }
            ],
            "tool_output_hotspots": [
                {
                    "tool_name": "Bash",
                    "events": 4,
                    "output_tokens_approx": 120,
                    "output_chars": 480,
                }
            ],
        }
    )

    out = capsys.readouterr().out
    assert "manifest_core~100t task(verification)~160t full~400t" in out
    assert "sdk.complete|sdk reqs=2 in=300 out=50 http_success=100.0%" in out
    assert "Bash events=4 out~120t chars=480" in out


@pytest.mark.parametrize(
    ("command", "surface"),
    [
        ("st check --quick", "check"),
        ("cd x && st commit -m y", "commit"),
        ("FOO=1 BAR=x st search foo", "search"),
        ("timeout 600 st check", "check"),
        ("timeout -k 5 30s st db query", "db"),
        ("echo $(st pulse --gate)", "pulse"),
        ("ls\nst done x", "done"),
        ('["/bin/bash", "-lc", "st tools manifest --help"]', "tools"),
        ('["/bin/bash", "-lc", "cd a\\nst search q"]', "search"),
        ('["st", "claim", "x"]', "claim"),
        ('tools.exec_command({cmd:"st lease --list"})', "lease"),
        ("env A=1 st -P agent-hub db query", "db"),
        ("rg 'st check' docs", None),
        ("first-st thing", None),
        ("git status", None),
    ],
)
def test_st_command_patterns_cover_wrapped_shell_forms(test_db_url: str, command: str, surface: str | None) -> None:
    """Adoption counts st behind env/timeout/subshell/array/Codex exec wrappers (PostgreSQL ARE)."""
    import psycopg

    from cli.commands.tools import _ST_COMMAND_RE, _ST_SURFACE_RE

    with psycopg.connect(test_db_url) as connection:
        matched, found = cast(tuple[bool, str | None], connection.execute(
            "SELECT %s ~ %s, lower((regexp_match(%s, %s))[1])",
            (command, _ST_COMMAND_RE, command, _ST_SURFACE_RE),
        ).fetchone())
    assert matched is (surface is not None)
    assert found == surface


@pytest.mark.parametrize(
    ("pattern_name", "command", "expected"),
    [
        ("_RAW_QUALITY_RE", "pytest -q", True),
        ("_RAW_QUALITY_RE", "cd a && ruff check .", True),
        ("_RAW_QUALITY_RE", "pytest_helper.sh", False),
        ("_RAW_DB_RE", "psql -c 'select 1'", True),
        ("_RAW_SERVICE_RE", "systemctl restart x", True),
        ("_RAW_SERVICE_RE", "systemctl --user stop x", True),
        ("_RAW_SERVICE_RE", "docker compose up -d", True),
        ("_RAW_SERVICE_RE", "systemctl list-timers --all", False),
        ("_RAW_SERVICE_RE", "systemctl --user status x", False),
        ("_ST_CHECK_RE", "timeout 900 st check --quick", True),
        ("_ST_CHECK_RE", "st checkout", False),
    ],
)
def test_audit_patterns_use_postgres_word_boundaries(test_db_url: str, pattern_name: str, command: str, expected: bool) -> None:
    """PostgreSQL treats \\b as backspace; the audit patterns must still match real commands."""
    import psycopg

    from cli.commands import tools

    with psycopg.connect(test_db_url) as connection:
        row = connection.execute("SELECT %s ~* %s", (command, getattr(tools, pattern_name))).fetchone()
    assert row is not None and row[0] is expected


def test_compact_formatters_honor_requested_limit(capsys: pytest.CaptureFixture[str]) -> None:
    """Rows returned for -l/--limit are all printed, not re-truncated client-side."""
    from cli.commands.tools import _format_adoption_compact

    _format_status_compact({
        "summary": {"total_requests": 12},
        "by_tool_name": [{"tool_name": f"tool-{index}", "count": 1} for index in range(12)],
        "by_endpoint": [{"endpoint": f"/ep-{index}", "count": 1} for index in range(12)],
    })
    _format_adoption_compact({
        "window_hours": 24,
        "summary": {"shell_tool_events": 30, "st_commands": 30, "st_command_rate": 100.0},
        "top_st_surfaces": [{"surface": f"st s{index}", "count": 1} for index in range(30)],
    })
    out = capsys.readouterr().out
    assert "tool-11" in out
    assert "/ep-11" in out
    assert "st s29  1" in out
    assert "shell_commands=30" in out


def test_cost_compact_honors_requested_limit(capsys: pytest.CaptureFixture[str]) -> None:
    _format_cost_compact({
        "window_hours": 24,
        "manifest_costs": [{"density": "core", "task": None, "tokens_approx": 1}],
        "request_hotspots": [{"tool_name": f"req-{index}", "tool_type": "sdk", "requests": 1} for index in range(12)],
        "tool_output_hotspots": [{"tool_name": f"out-{index}", "events": 1} for index in range(12)],
    })
    out = capsys.readouterr().out
    assert "req-11|sdk" in out
    assert "out-11 events=1" in out
