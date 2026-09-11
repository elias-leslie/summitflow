from pathlib import Path
from unittest.mock import MagicMock

from typer.testing import CliRunner

from cli.commands import learn


def test_learning_client_uses_project_api_and_agent_attribution(monkeypatch, tmp_path: Path):
    client = MagicMock()
    client.__enter__.return_value = client
    client.post.return_value = {"status": "ok"}
    monkeypatch.setattr(learn, "ProjectApiClient", lambda url: client)
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
