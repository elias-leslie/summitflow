"""Result accounting regressions exercise the actual read-only cost query."""

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest
from psycopg import sql
from psycopg.types.json import Json
from typer.testing import CliRunner

from cli.commands.tools import _cost_queries, app
from cli.commands.tools_cost import cost_advisory, render_cost_advisory, result_diagnostics_query


def test_cost_attributes_unnamed_result_to_named_call(test_db_url: str) -> None:
    fixtures = sql.SQL("""
        WITH session_events(id, session_id, event_type, call_id, tool_name,
                            tool_output, content, tokens, duration_ms,
                            source_timestamp, created_at, tool_input, source_event_id) AS (
            VALUES
              ('use', 'sess-1', 'tool_use', 'call-1', 'exec_command',
               NULL::json, NULL::text, NULL::int, NULL::int,
               now(), now(), '{"cmd":"read source"}'::json, 'use-1'),
              ('result', 'sess-1', 'tool_result', 'call-1', NULL,
               '{"call_id":"call-1","output":"abcd"}'::json, 'abcd', NULL, 1,
               now(), now(), NULL, 'result-1')
        )
    """)
    _, query = _cost_queries(24, 10)
    with psycopg.connect(test_db_url) as connection:
        rows = connection.execute(fixtures + query, (24, None, None, 10)).fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "exec_command"
    assert rows[0][1] == 1
    assert rows[0][3] == 4, "cost must measure the result, not the named use row"


def _fixtures(events: list[dict[str, Any]], sessions: list[tuple[str, str | None, str | None]] | None = None) -> sql.Composed:
    now = datetime.now(UTC)
    rows = []
    for index, event in enumerate(events):
        values = [
            event.get("id", str(index)), event.get("session_id", "sess-1"),
            event.get("event_type", "tool_result"), event.get("call_id"), event.get("tool_name"),
            Json(event.get("tool_output")), event.get("content"), event.get("tokens"), event.get("duration_ms"),
            event.get("source_timestamp", now), event.get("created_at", now), Json(event.get("tool_input")),
            event.get("source_event_id", f"source-{index}"),
        ]
        rows.append(sql.SQL("({})").format(sql.SQL(",").join(map(sql.Literal, values))))
    session_rows = [sql.SQL("({})").format(sql.SQL(",").join(map(sql.Literal, item)))
                    for item in sessions or [("sess-1", "worker", "task-1")]]
    return sql.SQL("""
        WITH fixture_events(id, session_id, event_type, call_id, tool_name, tool_output,
                            content, tokens, duration_ms, source_timestamp, created_at,
                            tool_input, source_event_id) AS (VALUES {events}),
        session_events AS (
            SELECT id::text, session_id::text, event_type::text, call_id::text, tool_name::text,
                   tool_output::json, content::text, tokens::int, duration_ms::int,
                   source_timestamp::timestamptz, created_at::timestamptz,
                   tool_input::json, source_event_id::text FROM fixture_events
        ), sessions(id, agent_slug, external_id) AS (VALUES {sessions})
    """).format(events=sql.SQL(",").join(rows), sessions=sql.SQL(",").join(session_rows))


def _diagnostics(test_db_url: str, events: list[dict[str, Any]], sessions: list[tuple[str, str | None, str | None]] | None = None) -> dict[str, Any]:
    with psycopg.connect(test_db_url) as connection:
        row = connection.execute(_fixtures(events, sessions) + result_diagnostics_query(), (24, None, None)).fetchone()
    assert row is not None
    return {"result_diagnostics": row[0]}


def _retrievals(count: int, *, command: str = "cat source.py", output: str = "x" * 20000, session_id: str = "sess-1") -> list[dict[str, Any]]:
    events = []
    for index in range(count):
        call_id = f"call-{index}"
        events.extend([
            {"event_type": "tool_use", "call_id": call_id, "tool_name": "Bash", "tool_input": {"cmd": command}, "session_id": session_id},
            {"call_id": call_id, "content": output, "session_id": session_id},
        ])
    return events


def test_cost_deduplicates_authoritative_results_and_excludes_backfilled_history(test_db_url: str) -> None:
    old = datetime.now(UTC) - timedelta(days=3)
    events = [
        {"event_type": "tool_use", "call_id": "call", "tool_name": "Bash", "source_timestamp": old},
        {"call_id": "call", "tool_output": {"call_id": "call"}, "content": "café", "source_event_id": "native-result"},
        {"call_id": "call", "content": "provisional", "source_event_id": "native-command:call:result", "source_timestamp": datetime.now(UTC) + timedelta(seconds=1)},
        {"call_id": "history", "tool_name": "old", "content": "backfilled", "source_timestamp": old},
        {"call_id": "history", "session_id": "child", "tool_name": "old", "content": "inherited", "source_timestamp": old},
        {"call_id": "call", "session_id": "other", "tool_name": "other", "content": "other"},
        {"tool_name": "metadata", "tool_output": {"call_id": "metadata"}},
    ]
    with psycopg.connect(test_db_url) as connection:
        rows = connection.execute(_fixtures(events) + _cost_queries(24, 10)[1], (24, "sess-1", "sess-1", 10)).fetchall()
    measured = next(row for row in rows if row[0] == "Bash")
    assert measured[1:4] == (1, None, 4)
    assert measured[9:13] == (5, 5, 5, 5), "UTF-8 bytes and percentiles exclude duplicated metadata"
    assert {row[0] for row in rows} == {"Bash", "metadata"}
    assert next(row for row in rows if row[0] == "metadata")[5] == 0


def test_cost_measures_stdout_stderr_empty_and_legacy_results(test_db_url: str) -> None:
    data = _diagnostics(test_db_url, [
        {"tool_name": "shell", "call_id": "one", "tool_output": {"stdout": "café", "stderr": "!", "exit_code": 0}},
        {"tool_name": "empty", "tool_output": {"output": "", "truncated": False}, "source_timestamp": None},
        {"tool_name": "opaque", "tool_output": {"call_id": "three", "opaque_blocks": 1}},
    ])
    summary = data["result_diagnostics"]["summary"]
    assert summary["results"] == 3
    assert summary["measured_results"] == 2
    assert summary["output_bytes"] == 6
    assert (summary["p50_bytes"], summary["p95_bytes"], summary["max_bytes"]) == (0, 6, 6)
    assert summary["truncation_samples"] == 1
    assert summary["source_timestamp_results"] == 2


def test_cost_keeps_nested_wrapper_provenance_out_of_delivered_totals(test_db_url: str) -> None:
    output = "x" * 40000
    events = [
        {"event_type": "tool_use", "call_id": "wrapper", "tool_name": "functions.exec", "tool_input": {"raw": "read source"}},
        {"call_id": "wrapper", "content": output},
        {"event_type": "tool_use", "call_id": "nested", "tool_name": "Bash", "tool_input": {"command": "cat source.py", "wrapper_candidate_call_id": "wrapper", "wrapper_correlation": "nested_command_digest"}},
        {"call_id": "nested", "tool_output": {"stdout": output, "truncated": True}},
    ]
    data = _diagnostics(test_db_url, events)
    diagnostics = data["result_diagnostics"]
    assert diagnostics["observed_results"] == 2
    assert diagnostics["wrapper_results"] == diagnostics["nested_results"] == diagnostics["nested_results_excluded"] == 1
    assert diagnostics["summary"]["results"] == 1
    assert diagnostics["summary"]["output_bytes"] == 40000
    assert diagnostics["summary"]["truncated_results"] == 0
    assert cost_advisory(data)["status"] == "ok"
    events[2]["tool_input"]["wrapper_correlation"] = "single_open_exec"
    uncertain = _diagnostics(test_db_url, events)["result_diagnostics"]
    assert uncertain["nested_results_excluded"] == 0
    assert uncertain["summary"]["results"] == 2


def test_repeated_single_nested_retrieval_is_counted_once_per_wrapper(test_db_url: str) -> None:
    events = []
    for index in range(2):
        wrapper, nested = f"wrapper-{index}", f"nested-{index}"
        events.extend([
            {"event_type": "tool_use", "call_id": wrapper, "tool_name": "exec", "tool_input": {"raw": "known wrapper"}},
            {"call_id": wrapper, "content": "x" * 40000},
            {"event_type": "tool_use", "call_id": nested, "tool_name": "Bash", "tool_input": {"command": "st tools manifest --density full", "wrapper_candidate_call_id": wrapper, "wrapper_correlation": "nested_command_digest"}},
            {"call_id": nested, "content": "x" * 40000},
        ])
    data = _diagnostics(test_db_url, events)
    diagnostics = data["result_diagnostics"]
    assert diagnostics["summary"]["results"] == 2
    assert diagnostics["summary"]["output_bytes"] == 80000
    assert diagnostics["nested_results_excluded"] == 2
    assert diagnostics["repeated_retrievals"][0]["retrievals"] == 2
    assert "--surface <surface>" in render_cost_advisory(data)


def test_result_identity_is_scoped_to_its_session_and_payload_call_id(test_db_url: str) -> None:
    events = [
        {"event_type": "tool_use", "session_id": "sess-1", "call_id": "same", "tool_name": "first"},
        {"session_id": "sess-1", "tool_output": {"call_id": "same", "output": "one"}},
        {"event_type": "tool_use", "session_id": "sess-2", "call_id": "same", "tool_name": "second"},
        {"session_id": "sess-2", "tool_output": {"tool_use_id": "same", "content": "second"}},
    ]
    with psycopg.connect(test_db_url) as connection:
        rows = connection.execute(_fixtures(events) + _cost_queries(24, 10)[1], (24, None, None, 10)).fetchall()
    assert {row[0]: row[3] for row in rows} == {"first": 3, "second": 6}


@pytest.mark.parametrize("count,truncated,status", [(20, 2, "advisory"), (20, 1, "ok"), (19, 2, "ok")])
def test_cost_advisory_truncation_threshold(test_db_url: str, count: int, truncated: int, status: str) -> None:
    events = [{"call_id": f"call-{index}", "content": "retained", "tool_output": {"output_truncated": index < truncated}}
              for index in range(count)]
    data = _diagnostics(test_db_url, events)
    assert cost_advisory(data)["status"] == status


def test_cost_advisory_identifies_unchanged_retrievals_in_same_role_task(test_db_url: str) -> None:
    data = _diagnostics(test_db_url, _retrievals(3))
    repeated = data["result_diagnostics"]["repeated_retrievals"]
    assert repeated[0]["retrievals"] == 3
    assert repeated[0]["duplicate_bytes"] == 40000
    assert repeated[0]["input_digest"] and repeated[0]["output_digest"]
    assert "reuse saved output" in render_cost_advisory(data)
    # Two useful reads or a changed result do not meet the unchanged threshold.
    assert cost_advisory(_diagnostics(test_db_url, _retrievals(2)))["status"] == "ok"
    changed = _retrievals(3)
    changed[-1]["content"] += "changed"
    assert cost_advisory(_diagnostics(test_db_url, changed))["status"] == "ok"


@pytest.mark.parametrize("other_scope", [("worker", "task-2"), ("reviewer", "task-1"), ("worker", None), ("worker", "user-1")])
def test_cost_does_not_infer_same_role_task_repeats(test_db_url: str, other_scope: tuple[str, str | None]) -> None:
    events = _retrievals(2) + _retrievals(1, session_id="sess-2")
    sessions: list[tuple[str, str | None, str | None]] = [("sess-1", "worker", "task-1"), ("sess-2", *other_scope)]
    assert cost_advisory(_diagnostics(test_db_url, events, sessions))["status"] == "ok"
    missing = [("sess-1", None, None)]
    assert cost_advisory(_diagnostics(test_db_url, _retrievals(3), missing))["status"] == "ok"
    arbitrary: list[tuple[str, str | None, str | None]] = [("sess-1", "worker", "user-1")]
    assert _diagnostics(test_db_url, _retrievals(3), arbitrary)["result_diagnostics"]["role_task_results"] == 0


@pytest.mark.parametrize("command,route", [("st tools manifest --density full", "--surface <surface>"), ("st --no-compact context task-1", "st export <task> --output <file>")])
def test_cost_advisory_suggests_existing_compact_or_file_route(test_db_url: str, command: str, route: str) -> None:
    data = _diagnostics(test_db_url, _retrievals(2, command=command, output="x" * 32768))
    assert cost_advisory(data)["status"] == "advisory"
    assert route in render_cost_advisory(data)


def test_useful_large_source_read_alone_is_healthy(test_db_url: str) -> None:
    data = _diagnostics(test_db_url, _retrievals(1, output="useful source\n" * 50000))
    assert data["result_diagnostics"]["summary"]["max_bytes"] == 700000
    assert cost_advisory(data)["status"] == "ok"
    assert len(render_cost_advisory(data)) < 150


def test_source_discussion_of_truncation_is_not_truncation_telemetry(test_db_url: str) -> None:
    events = [{"call_id": str(index), "content": "This source explains output truncated errors and shows 100 tokens truncated as an example."}
              for index in range(20)]
    data = _diagnostics(test_db_url, events)
    assert data["result_diagnostics"]["summary"]["truncation_samples"] == 0
    assert cost_advisory(data)["status"] == "ok"


def test_known_native_truncation_marker_is_retained_as_evidence(test_db_url: str) -> None:
    data = _diagnostics(test_db_url, [{"content": "Warning: truncated output (original token count: 1234)\nretained"}])
    assert data["result_diagnostics"]["summary"]["truncated_results"] == 1


def test_null_payload_is_not_a_measurement(test_db_url: str) -> None:
    data = _diagnostics(test_db_url, [{"tool_output": {"output": None, "call_id": "missing"}}])
    assert data["result_diagnostics"]["summary"]["measured_results"] == 0
    assert cost_advisory(data)["status"] == "unknown"


def test_missing_measurements_are_unknown_and_never_block(test_db_url: str) -> None:
    data = _diagnostics(test_db_url, [{"tool_output": {"opaque_blocks": 1}}])
    assert cost_advisory(data)["status"] == "unknown"
    assert "work may continue" in render_cost_advisory(data)


def test_cost_advisory_output_is_bounded_and_retains_model_provenance() -> None:
    data = {"result_diagnostics": {"summary": {"results": 20, "measured_results": 20, "truncated_results": 2},
        "repeated_retrievals": [{"tool_name": "tool" * 100, "agent_role": "role" * 100,
            "task_identity": "task" * 100, "retrievals": 3, "duplicate_bytes": 40000}] * 3},
        "native_usage": [{"scope": "response", "model": "codex", "source": "native-rollout",
            "cached_input_tokens": 4, "uncached_input_tokens": 6, "uncached_input_tokens_samples": 1, "events": 2}]}
    output = render_cost_advisory(data)
    assert len(output.encode()) <= 1500
    assert "Model=codex source=native-rollout" in output
    assert "cached=4 uncached=6 paired=1/2" in output


def test_advisory_json_budget_includes_unicode_and_escaped_labels() -> None:
    data = {"result_diagnostics": {"summary": {"results": 20, "measured_results": 20, "truncated_results": 2},
        "repeated_retrievals": [{"tool_name": '"語' * 100, "agent_role": "語" * 100,
            "task_identity": "語" * 100, "retrievals": 3, "duplicate_bytes": 40000}] * 3},
        "native_usage": [{"scope": "response", "model": "語" * 50, "source": "source", "events": 2}]}
    rendered = render_cost_advisory(data)
    assert len(rendered.encode()) < 1500
    assert len(json.dumps({"advisory": rendered}, indent=2).encode()) < 1500
    assert "Truncation:" in rendered
    assert "uncached=unknown" in rendered


@pytest.mark.parametrize("flag", ["--advisory", "--gate"])
def test_cost_advisory_telemetry_failure_is_unknown_success(monkeypatch: pytest.MonkeyPatch, flag: str) -> None:
    def unavailable(*_args: Any) -> None:
        raise psycopg.OperationalError("sensitive database endpoint")
    monkeypatch.setattr("cli.commands.tools._fetch_cost_metrics", unavailable)
    result = CliRunner().invoke(app, ["cost", flag])
    assert result.exit_code == 0
    assert "TOOLS_COST:UNKNOWN" in result.output
    assert "sensitive" not in result.output


@pytest.mark.parametrize("arguments", [["--hours", "0"], ["--limit", "0"], ["--limit", "101"]])
def test_cost_rejects_invalid_window_and_limits(arguments: list[str]) -> None:
    result = CliRunner().invoke(app, ["cost", *arguments])
    assert result.exit_code == 2
