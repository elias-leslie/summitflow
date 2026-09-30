"""Public local inspection reads native provenance and never constructs an API client."""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from typer.testing import CliRunner

from cli.commands import sessions_native_inspection as inspection
from cli.main import app


def _info(path, *, thread="child-thread", open=True, observed=None):
    return SimpleNamespace(
        session_id=thread, native_session_id="root-runtime", parent_session_id="parent-thread",
        agent_path="/root/child", agent_nickname="worker", cwd=Path("/owned"), path=path,
        model="configured-value-must-not-be-delivery", is_open=open, ownership_ambiguous=False,
        identity_error=None, size=42, model_evidence={"requested_model": "requested-route", "requested_reasoning_effort": "high", "observed_model": observed, "source_generation": "native-generation", "source_line": 2, "source_timestamp": "2026-09-30T17:00:00Z"},
        model_scan={"offset": 42},
    )


def test_inspect_current_is_local_and_delivery_stays_unknown(tmp_path):
    info = _info(tmp_path / "child.jsonl")
    library = SimpleNamespace(resolve_current_transcript=lambda: info)
    with patch.object(inspection, "transcript_library", return_value=library), patch("cli.commands.sessions.STClient") as api:
        result = CliRunner().invoke(app, ["sessions", "inspect", "current", "--json"])
    assert result.exit_code == 0
    receipt = json.loads(result.output)
    assert receipt["schema_version"] == "native-session-inspection.v1"
    assert receipt["thread_id"] == "child-thread"
    assert receipt["transcript_runtime_session_id"] == "root-runtime"
    assert receipt["parent_thread_id"] == "parent-thread"
    assert receipt["requested_model"] == "requested-route" and receipt["observed_model"] is None
    api.assert_not_called()


def test_inspect_exact_child_checks_own_header_and_preserves_closed_health(tmp_path):
    path = tmp_path / "rollout-child-thread.jsonl"
    path.write_text("fixture")
    info = _info(path, open=False)
    library = SimpleNamespace(TRANSCRIPTS_ROOT=tmp_path, discover_open_transcripts=lambda: SimpleNamespace(paths=frozenset()), read_transcript_info=lambda *args, **kwargs: info)
    with patch.object(inspection, "transcript_library", return_value=library), patch("cli.commands.sessions.STClient") as api:
        result = CliRunner().invoke(app, ["sessions", "inspect", "child-thread", "--json"])
    assert result.exit_code == 0 and json.loads(result.output)["is_open"] is False
    api.assert_not_called()
    info.session_id = "copied-parent"
    with patch.object(inspection, "transcript_library", return_value=library):
        rejected = CliRunner().invoke(app, ["sessions", "inspect", "child-thread", "--json"])
    assert rejected.exit_code == 1


def test_inspect_current_rejects_unverified_environment_without_api():
    def resolve():
        raise ValueError("Current native identity requires validated caller provenance.")
    with patch.object(inspection, "transcript_library", return_value=SimpleNamespace(resolve_current_transcript=resolve)), patch("cli.commands.sessions.STClient") as api:
        result = CliRunner().invoke(app, ["sessions", "inspect", "current", "--json"])
    assert result.exit_code == 1
    api.assert_not_called()
