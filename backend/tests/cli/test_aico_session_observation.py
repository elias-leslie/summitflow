"""Monitor observations require local native evidence and the read-only owner."""

from __future__ import annotations

import http.client
import json
import os
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from cli.lib import aico_session_observation as observation

THREAD = "019f62d8-881c-7393-8c19-ae9b2b21e570"
WIDGET = "0123abcd"
LOGICAL = "logical-aico-session"
RECEIPT = {
    "owner": "aico", "widgetId": WIDGET, "sessionId": LOGICAL,
    "generation": "a" * 64, "tmuxSessionId": "$17", "paneId": "%21",
}


@pytest.fixture
def local_owner(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    session = {
        "id": THREAD, "host": os.uname().nodename, "tmux_pane_id": None,
        "external_identity": {
            "harness": "codex", "launcher": "aico", "runtime_session_id": THREAD,
            "agent_path": "/root", "aico_widget_id": WIDGET, "aico_session_id": LOGICAL,
        },
    }
    info = SimpleNamespace(
        session_id=THREAD, native_session_id="distinct-runtime-alias", is_open=True,
        ownership_ambiguous=False, identity_error=None, parent_session_id=None,
        agent_path="/root", process_owner=SimpleNamespace(
            harness="codex", aico_widget_id=WIDGET, aico_session_id=LOGICAL,
        ),
    )
    path = Path(f"/local/rollout-{THREAD}.jsonl")
    library = MagicMock()
    library.discover_open_transcripts.return_value = SimpleNamespace(paths={path})
    library.read_transcript_info.return_value = info
    query = MagicMock(return_value=deepcopy(RECEIPT))
    monkeypatch.setattr(observation, "_owner_socket", lambda: "/local/control.sock")
    monkeypatch.setattr(observation, "transcript_library", lambda: library)
    monkeypatch.setattr(observation, "_query_owner", query)
    return SimpleNamespace(session=session, info=info, library=library, query=query)


def test_exact_fresh_root_projects_owner_without_mutating_session(local_owner):
    original = deepcopy(local_owner.session)
    result = observation.observe_aico_owners([local_owner.session])[0]
    assert result["tmux_pane_id"] == "%21"
    assert result["aico_owner_observation"] == RECEIPT
    assert local_owner.session == original
    local_owner.query.assert_called_once_with("/local/control.sock", WIDGET)


@pytest.mark.parametrize("field,value", [
    ("id", THREAD[:8]), ("id", THREAD.upper()), ("id", "requestId"),
    ("host", "remote-host"), ("host", None), ("parent_session_id", "parent"),
    ("external_identity", None),
])
def test_unqualified_session_never_queries_owner(local_owner, field, value):
    local_owner.session[field] = value
    assert observation.observe_aico_owners([local_owner.session])[0]["aico_owner_observation"] is None
    local_owner.query.assert_not_called()
    local_owner.library.discover_open_transcripts.assert_not_called()


@pytest.mark.parametrize("field,value", [
    ("runtime_session_id", "other-thread"), ("agent_path", "/root/child"),
    ("harness", "claude"), ("launcher", "direct"),
    ("aico_widget_id", "deadbeef"), ("aico_session_id", "other-logical"),
])
def test_conflicting_saved_identity_never_queries_owner(local_owner, field, value):
    local_owner.session["external_identity"][field] = value
    result = observation.observe_aico_owners([local_owner.session])[0]
    assert result["aico_owner_observation"] is None
    local_owner.query.assert_not_called()


@pytest.mark.parametrize("field,value", [
    ("is_open", False), ("ownership_ambiguous", True), ("identity_error", "conflict"),
    ("parent_session_id", "parent"), ("agent_path", "/root/child"),
    ("process_owner", None), ("session_id", "other-thread"),
])
def test_stale_ambiguous_or_child_native_evidence_never_queries_owner(local_owner, field, value):
    setattr(local_owner.info, field, value)
    assert observation.observe_aico_owners([local_owner.session])[0]["aico_owner_observation"] is None
    local_owner.query.assert_not_called()


def test_ambiguous_native_matches_never_queries_owner(local_owner):
    local_owner.library.discover_open_transcripts.return_value.paths.add(
        Path(f"/other/rollout-{THREAD}.jsonl")
    )
    assert observation.observe_aico_owners([local_owner.session])[0]["aico_owner_observation"] is None
    local_owner.query.assert_not_called()


def test_absent_live_transcript_does_not_use_saved_owner(local_owner):
    local_owner.library.discover_open_transcripts.return_value.paths = set()
    assert observation.observe_aico_owners([local_owner.session])[0]["aico_owner_observation"] is None
    local_owner.query.assert_not_called()


@pytest.mark.parametrize("receipt", [
    None, [], "malformed", {**RECEIPT, "owner": "other"},
    {**RECEIPT, "widgetId": "deadbeef"}, {**RECEIPT, "sessionId": "other"},
    {**RECEIPT, "generation": None}, {**RECEIPT, "generation": "short"},
    {**RECEIPT, "tmuxSessionId": "name"}, {**RECEIPT, "paneId": 21},
    {**RECEIPT, "paneId": "%21\n"}, {},
])
def test_invalid_owner_response_preserves_existing_pane(local_owner, receipt):
    local_owner.session["tmux_pane_id"] = "%existing"
    local_owner.query.return_value = receipt
    result = observation.observe_aico_owners([local_owner.session])[0]
    assert result["tmux_pane_id"] == "%existing"
    assert result["aico_owner_observation"] is None


@pytest.mark.parametrize("error", [TimeoutError(), OSError(), ValueError(), http.client.HTTPException()])
def test_owner_failure_keeps_monitor_available(local_owner, error):
    local_owner.query.side_effect = error
    assert observation.observe_aico_owners([local_owner.session])[0]["aico_owner_observation"] is None


def test_absent_socket_keeps_monitor_available(local_owner, monkeypatch):
    def absent():
        raise FileNotFoundError
    monkeypatch.setattr(observation, "_owner_socket", absent)
    assert observation.observe_aico_owners([local_owner.session])[0]["aico_owner_observation"] is None
    local_owner.query.assert_not_called()


def test_mixed_session_identities_do_not_suppress_valid_observation(local_owner):
    result = observation.observe_aico_owners([{"id": "invalid"}, local_owner.session])
    assert result[0]["aico_owner_observation"] is None
    assert result[1]["aico_owner_observation"] == RECEIPT


@pytest.mark.parametrize("status,body,expected", [
    (200, json.dumps(RECEIPT).encode(), RECEIPT), (404, b"{}", None),
    (503, b"{}", None), (200, b"x" * 4097, None),
])
def test_transport_only_gets_exact_widget_and_closes(monkeypatch, status, body, expected):
    connection = MagicMock()
    response = connection.getresponse.return_value
    response.status = status
    response.read.return_value = body
    monkeypatch.setattr(observation, "_OwnerConnection", lambda path: connection)
    assert observation._query_owner("/local/control.sock", WIDGET) == expected
    connection.request.assert_called_once_with("GET", f"/v1/sessions/{WIDGET}")
    connection.close.assert_called_once()


def test_malformed_json_closes_connection(monkeypatch):
    connection = MagicMock()
    connection.getresponse.return_value.status = 200
    connection.getresponse.return_value.read.return_value = b"not json"
    monkeypatch.setattr(observation, "_OwnerConnection", lambda path: connection)
    with pytest.raises(ValueError):
        observation._query_owner("/local/control.sock", WIDGET)
    connection.close.assert_called_once()


def test_overview_projects_owner(local_owner):
    from cli.commands.sessions_monitor import list_monitor_sessions
    client = MagicMock()
    client.list_sessions.return_value = [local_owner.session]
    result = list_monitor_sessions(client, status_filter="active", limit=20, agent_slug=None, project_id=None)
    assert result[0]["tmux_pane_id"] == "%21"


def test_single_monitor_json_projects_owner(local_owner, monkeypatch):
    from typer.testing import CliRunner

    from cli.commands import sessions
    from cli.main import app

    client = MagicMock()
    client.get_session.return_value = local_owner.session
    monkeypatch.setattr(sessions, "STClient", lambda **kwargs: client)
    monkeypatch.setattr(sessions, "_resolve_session_id", lambda *args, **kwargs: THREAD)
    result = CliRunner().invoke(app, ["sessions", "monitor", THREAD, "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["aico_owner_observation"] == RECEIPT
