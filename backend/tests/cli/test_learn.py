import hashlib
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
import typer
from typer.testing import CliRunner

from cli.commands import learn


def test_learning_client_uses_project_api_and_agent_attribution(monkeypatch, tmp_path: Path):
    client = MagicMock()
    client.__enter__.return_value = client
    client.post.return_value = {"status": "ok"}
    monkeypatch.setattr(learn, "ProjectApiClient", lambda url, **_kwargs: client)
    monkeypatch.setattr(learn, "resolve_api_url", lambda api: MagicMock(url="http://localhost:8018"))
    monkeypatch.setattr(learn, "output_json", lambda value: None)
    action = tmp_path / "action.json"
    action.write_text('{"operation":"request","actor":"human"}')
    result = CliRunner().invoke(learn.app, ["lab", "--path", "path-starter", "--lesson", "trust-2", "--file", str(action)])
    assert result.exit_code == 0
    client.post.assert_called_once_with("/api/paths/path-starter/lessons/trust-2/lab", json_body={"operation": "request", "actor": "agent"})


def test_invalid_json_is_an_input_error(tmp_path: Path):
    action = tmp_path / "bad.json"
    action.write_text("[]")
    result = CliRunner().invoke(learn.app, ["profile", "--file", str(action)])
    assert result.exit_code == 3


def test_roadmap_and_gateway_mutations_stamp_agent(monkeypatch, tmp_path: Path):
    sent = []
    monkeypatch.setattr(learn, 'request', lambda *args: sent.append(args))
    body = tmp_path / 'body.json'
    body.write_text('{"revision":4,"actor":"human"}')
    runner = CliRunner()
    assert runner.invoke(learn.app, ['roadmap', '--file', str(body)]).exit_code == 0
    assert sent[-1] == ('/api/roadmap', {'revision': 4, 'actor': 'agent'}, 'PUT')
    assert runner.invoke(learn.app, ['agent-lab', '--path', 'path/one', '--lesson', 'a b', '--file', str(body)]).exit_code == 0
    assert sent[-1][0] == '/api/paths/path%2Fone/lessons/a%20b/agent-lab'
    assert sent[-1][1]['actor'] == 'agent'


def test_authoring_commands_use_shared_api_and_validate_selection(monkeypatch, tmp_path: Path):
    sent = []
    monkeypatch.setattr(learn, 'request', lambda *args: sent.append(args))
    runner = CliRunner()
    assert runner.invoke(learn.app, ['authoring']).exit_code == 0
    assert sent[-1] == ('/api/authoring',)
    assert runner.invoke(learn.app, ['draft']).exit_code == 2
    assert runner.invoke(learn.app, ['draft', '--id', 'draft-one']).exit_code == 0
    assert sent[-1] == ('/api/content/drafts/draft-one', None)
    assert runner.invoke(learn.app, ['publish', 'draft-one']).exit_code == 0
    assert sent[-1] == ('/api/content/drafts/draft-one/publish', {})
    assert runner.invoke(learn.app, ['work', 'content-review', '--record', 'draft-one']).exit_code == 0
    assert sent[-1][1]['kind'] == 'content-review' and sent[-1][1]['record_id'] == 'draft-one'
    assert sent[-1][1]['actor'] == 'agent'


def test_native_conversation_and_challenge_are_not_second_state_stores(monkeypatch, tmp_path: Path):
    sent = []
    monkeypatch.setattr(learn, 'request', lambda *args: sent.append(args))
    runner = CliRunner()
    assert runner.invoke(learn.app, ['conversation', '--before', 'exchange/one']).exit_code == 0
    assert sent[-1] == ('/api/conversation?before=exchange%2Fone', None)
    body = tmp_path / 'exchange.json'
    body.write_text('{"message":"Actual learner message","answer":"Actual tutor reply"}')
    assert runner.invoke(learn.app, ['conversation', '--file', str(body)]).exit_code == 0
    assert sent[-1] == ('/api/conversation', {'message': 'Actual learner message', 'answer': 'Actual tutor reply'})
    assert runner.invoke(learn.app, ['challenge', '--path', 'p', '--lesson', 'l']).exit_code == 0
    assert sent[-1] == ('/api/paths/p/lessons/l/challenge',)


def test_pwn_provider_and_session_commands_use_the_learning_api(monkeypatch):
    sent = []
    monkeypatch.setattr(learn, 'request', lambda *args: sent.append(args))
    runner = CliRunner()
    assert runner.invoke(learn.app, ['pwn', 'sync', '--username', 'kasadis', '--dojo', 'welcome']).exit_code == 0
    assert sent[-1][0] == '/api/training/providers/pwn-college/sync'
    assert sent[-1][1]['username'] == 'kasadis'
    assert sent[-1][1]['dojo_ids'] == ['welcome']
    assert runner.invoke(learn.app, ['pwn', 'activities', '--dojo', 'welcome', '--unsolved']).exit_code == 0
    assert '/api/training/activities?' in sent[-1][0]
    assert 'dojo=welcome' in sent[-1][0] and 'solved=false' in sent[-1][0]


def test_session_start_without_shell_binds_native_harness(monkeypatch):
    calls = []
    study = {'id': 'study-session:one', 'revision': 1, 'data': {}, 'transcript': {'last_sequence': -1}}

    def fake(path, body=None, method='POST'):
        calls.append((path, body, method))
        return study

    monkeypatch.setattr(learn, 'require_data', fake)
    monkeypatch.setattr(learn, 'output_json', lambda value: None)
    result = CliRunner().invoke(
        learn.app,
        [
            'session',
            'start',
            '--activity',
            'pwn-college:welcome:welcome:terminal',
            '--harness',
            'codex',
            '--no-open',
            '--no-sync',
        ],
    )
    assert result.exit_code == 0
    assert len(calls) == 1
    assert calls[0][0] == '/api/training/sessions'
    assert calls[0][1]['activity_id'] == 'pwn-college:welcome:welcome:terminal'
    assert calls[0][1]['harness'] == 'codex'
    assert calls[0][1]['actor'] == 'agent'
    assert calls[0][2] == 'POST'


def test_native_learning_operator_is_bound_to_a_term_session(monkeypatch):
    monkeypatch.setenv("A_TERM_SESSION_ID", "a-term-session-one")
    monkeypatch.setenv("CODEX_THREAD_ID", "codex-thread-one")

    assert learn._native_session_id() == "a-term-session-one"
    suffix = hashlib.sha256(b"a-term-session-one").hexdigest()[:12]
    assert learn._native_harness("") == f"codex-{suffix}"


def test_session_continue_uses_atomic_admission_route(monkeypatch):
    calls = []
    study = {
        "id": "study-session:one",
        "revision": 1,
        "data": {"status": "active", "participants": [], "operator_harness": "codex"},
        "transcript": {"last_sequence": -1},
        "admission": "created",
    }

    def fake(path, body=None, method="POST"):
        calls.append((path, body, method))
        return study

    monkeypatch.setattr(learn, "require_data", fake)
    monkeypatch.setattr(learn, "output_json", lambda value: None)
    result = CliRunner().invoke(
        learn.app,
        [
            "session",
            "continue",
            "--activity",
            "pwn-college:welcome:welcome:terminal",
            "--no-open",
            "--no-sync",
        ],
    )

    assert result.exit_code == 0
    assert calls[0][0] == "/api/training/sessions/continue"
    assert calls[0][1]["activity_id"] == "pwn-college:welcome:welcome:terminal"


def test_explicit_handoff_uses_optimistic_revision(monkeypatch):
    sent = []
    monkeypatch.setattr(learn, 'request', lambda *args: sent.append(args))
    monkeypatch.setattr(learn, 'TranscriptSpool', FakeSpool)
    result = CliRunner().invoke(
        learn.app,
        [
            'session',
            'handoff',
            'study-session:one',
            '--from',
            'codex',
            '--to',
            'claude',
            '--expected-revision',
            '4',
        ],
    )
    assert result.exit_code == 0
    assert sent[-1][0] == '/api/training/sessions/study-session%3Aone/handoff'
    assert sent[-1][1]['expected_revision'] == 4
    assert sent[-1][1]['from_harness'] == 'codex'
    assert sent[-1][1]['to_harness'] == 'claude'


def test_improvement_promotion_creates_manual_task_and_writes_receipt(monkeypatch):
    calls = []
    selected = []
    candidate: dict[str, Any] = {
        'id': 'improvement:one',
        'revision': 3,
        'data': {
            'title': 'Improve session expiry handling',
            'observation': 'Remote expiry needs a visible recovery step.',
            'proposed_change': 'Show remote state before resume.',
            'target_project': 'learn-o-tron',
            'session_id': 'study-session:one',
            'status': 'accepted',
        },
    }

    def fake_request(path, body=None, method='POST'):
        calls.append((path, body, method))
        if path == '/api/training/improvements':
            return {'items': [candidate]}
        return {'id': candidate['id'], 'revision': 4, 'data': {**candidate['data'], 'status': 'promoted'}}

    task_client = MagicMock()
    task_client.create_task.return_value = {'id': 'task-promoted', 'title': candidate['data']['title']}
    monkeypatch.setattr(learn, 'require_data', fake_request)
    monkeypatch.setattr(learn, 'STClient', lambda: task_client)
    monkeypatch.setattr(learn, 'set_project_override', selected.append)
    monkeypatch.setattr(learn, 'output_json', lambda value: None)
    result = CliRunner().invoke(learn.app, ['improvements', 'promote', candidate['id']])
    assert result.exit_code == 0
    assert selected == ['learn-o-tron']
    created = task_client.create_task.call_args.args[0]
    assert created['execution_mode'] == 'manual_only'
    assert created['external_request_key'] == candidate['id']
    assert calls[-1][1]['status'] == 'promoted'
    assert calls[-1][1]['summitflow_task_id'] == 'task-promoted'


class FakeSpool:
    def __init__(self, *_args, **_kwargs):
        self.closed = False

    def append(self, _text):
        return []

    def drain(self, _upload):
        return True

    def close(self):
        self.closed = True


class PendingFakeSpool(FakeSpool):
    def drain(self, _upload):
        return False


class BusyFakeSpool:
    def __init__(self, *_args, **_kwargs):
        raise learn.TranscriptSpoolBusy("Another local terminal already owns this study session")


def study(activity: str = "terminal") -> dict[str, Any]:
    return {
        "id": "study-session:one",
        "revision": 1,
        "data": {
            "activity": {
                "upstream_path": f"/dojo/welcome/welcome/{activity}",
            },
            "remote_state": "unknown",
            "status": "paused",
            "operator_harness": "codex",
        },
        "transcript": {"last_sequence": -1},
    }


def test_terminal_starts_selected_activity_when_remote_identity_differs(monkeypatch):
    current = study("terminal")
    actions = []
    ssh_calls = []
    monkeypatch.setattr(learn, "TranscriptSpool", FakeSpool)
    monkeypatch.setattr(learn, "_remote_activity_path", lambda: "/dojo/welcome/welcome/other")
    monkeypatch.setattr(
        learn,
        "_session_action",
        lambda value, action, harness, **fields: actions.append((action, harness, fields)) or value,
    )
    monkeypatch.setattr(
        learn,
        "_ssh",
        lambda arguments, **_kwargs: ssh_calls.append(arguments)
        or MagicMock(returncode=0),
    )
    monkeypatch.setattr(learn, "run_terminal", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(learn, "request_data", lambda *_args, **_kwargs: current)
    monkeypatch.setattr(learn, "output_json", lambda _value: None)
    learn._open_study_terminal(current, "codex")
    assert ["dojo", "start", "/welcome/welcome/terminal"] in ssh_calls
    assert [item[0] for item in actions[:2]] == ["remote_expired", "remote_started"]


def test_terminal_accepts_killed_start_process_when_requested_activity_is_running(monkeypatch):
    current = study("terminal")
    actions = []
    identities = iter(
        [
            "/dojo/welcome/welcome/other",
            "/dojo/welcome/welcome/terminal",
        ]
    )
    monkeypatch.setattr(learn, "TranscriptSpool", FakeSpool)
    monkeypatch.setattr(learn, "_remote_activity_path", lambda: next(identities))
    monkeypatch.setattr(
        learn,
        "_session_action",
        lambda value, action, harness, **fields: actions.append((action, harness, fields)) or value,
    )
    monkeypatch.setattr(learn, "_ssh", lambda *_args, **_kwargs: MagicMock(returncode=137))
    monkeypatch.setattr(learn, "run_terminal", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(learn, "request_data", lambda *_args, **_kwargs: current)
    monkeypatch.setattr(learn, "output_json", lambda _value: None)

    learn._open_study_terminal(current, "codex")

    assert [item[0] for item in actions[:2]] == ["remote_expired", "remote_started"]


def test_handoff_refuses_to_orphan_a_pending_transcript(monkeypatch):
    sent = []
    monkeypatch.setattr(learn, "TranscriptSpool", PendingFakeSpool)
    monkeypatch.setattr(learn, "request", lambda *args: sent.append(args))
    result = CliRunner().invoke(
        learn.app,
        [
            "session",
            "handoff",
            "study-session:one",
            "--from",
            "codex",
            "--to",
            "claude",
            "--expected-revision",
            "4",
        ],
    )
    assert result.exit_code == 1
    assert sent == []


@pytest.mark.parametrize(
    ("spool", "error"),
    [
        (BusyFakeSpool, "study_terminal_busy"),
        (PendingFakeSpool, "pending_transcript"),
    ],
)
def test_finish_requires_closed_terminal_and_uploaded_transcript(monkeypatch, spool, error):
    calls = []
    captured = []
    monkeypatch.setattr(learn, "TranscriptSpool", spool)
    monkeypatch.setattr(
        learn,
        "require_data",
        lambda path, *_args, **_kwargs: calls.append(path) or study(),
    )
    monkeypatch.setattr(learn, "output_json", captured.append)
    result = CliRunner().invoke(
        learn.app,
        ["session", "finish", "study-session:one", "--harness", "codex"],
    )
    assert result.exit_code == 1
    assert calls == ["/api/training/sessions/study-session%3Aone"]
    assert captured[-1]["error"] == error


def test_terminal_stops_when_heartbeat_observes_handoff(monkeypatch):
    current = study("terminal")
    current["data"].update(remote_state="running", status="active")
    fresh = {
        **current,
        "revision": 2,
        "data": {**current["data"], "status": "active", "operator_harness": "claude"},
    }
    responses = iter(
        [
            current,
            learn.LearnRequestError("learn_api_error", "Operator lease belongs to claude", 1, 409),
            fresh,
        ]
    )

    def request_data(*_args, **_kwargs):
        value = next(responses)
        if isinstance(value, Exception):
            raise value
        return value

    def run_terminal(_command, _save, heartbeat, **_kwargs):
        heartbeat()
        return 0

    monkeypatch.setattr(learn, "TranscriptSpool", FakeSpool)
    monkeypatch.setattr(learn, "_remote_activity_path", lambda: "/dojo/welcome/welcome/terminal")
    monkeypatch.setattr(learn, "request_data", request_data)
    monkeypatch.setattr(learn, "run_terminal", run_terminal)
    captured = []
    monkeypatch.setattr(learn, "output_json", captured.append)
    with pytest.raises(typer.Exit):
        learn._open_study_terminal(current, "codex")
    assert captured[-1]["error"] == "operator_lease_lost"


def test_terminal_stops_when_outage_prevents_lease_renewal(monkeypatch):
    current = study("terminal")
    current["data"].update(
        remote_state="running",
        status="active",
        operator_lease_until="2020-01-01T00:00:00+00:00",
    )

    def request_data(*_args, **_kwargs):
        raise learn.LearnRequestError("learn_unreachable", "temporarily unavailable", 2)

    def run_terminal(_command, _save, heartbeat, **_kwargs):
        heartbeat()
        return 0

    monkeypatch.setattr(learn, "TranscriptSpool", FakeSpool)
    monkeypatch.setattr(learn, "_remote_activity_path", lambda: "/dojo/welcome/welcome/terminal")
    monkeypatch.setattr(learn, "request_data", request_data)
    monkeypatch.setattr(learn, "run_terminal", run_terminal)
    captured = []
    monkeypatch.setattr(learn, "output_json", captured.append)
    with pytest.raises(typer.Exit):
        learn._open_study_terminal(current, "codex")
    assert captured[-1]["error"] == "operator_lease_lost"
