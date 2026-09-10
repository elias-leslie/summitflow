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
