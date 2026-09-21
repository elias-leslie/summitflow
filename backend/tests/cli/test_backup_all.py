"""CLI contracts for all-source backup orchestration."""

from __future__ import annotations

from typer.testing import CliRunner

runner = CliRunner()


class SourceAPI:
    def __init__(self) -> None:
        self.created: list[str] = []

    def list_sources(self) -> list[dict[str, object]]:
        return [
            {"id": "enabled-project", "enabled": True},
            {"id": "retired-project", "enabled": False},
        ]

    def create_source_backup(
        self,
        source_id: str,
        *,
        note: str | None = None,
        keep_local: bool = False,
    ) -> dict[str, str]:
        del note, keep_local
        self.created.append(source_id)
        return {"task_id": f"task-{source_id}"}


def test_backup_all_queues_only_enabled_sources(monkeypatch) -> None:
    from cli.commands import backup
    from cli.main import app

    source_api = SourceAPI()
    monkeypatch.setattr(backup, "_get_source_api", lambda: source_api)

    result = runner.invoke(app, ["backup", "all"])

    assert result.exit_code == 0, result.output
    assert source_api.created == ["enabled-project"]
    assert "QUEUED enabled-project|task-enabled-project" in result.output
    assert "retired-project" not in result.output
    assert "BACKUP_ALL queued:1" in result.output


def test_explicit_create_remains_available_for_disabled_source(monkeypatch) -> None:
    from cli.commands import backup
    from cli.main import app

    source_api = SourceAPI()
    monkeypatch.setattr(backup, "_get_source_api", lambda: source_api)

    result = runner.invoke(
        app,
        ["backup", "create", "--source", "retired-project"],
    )

    assert result.exit_code == 0, result.output
    assert source_api.created == ["retired-project"]
    assert "task-retired-project" in result.output
