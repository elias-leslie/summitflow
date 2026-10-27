"""Project database URL resolution."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services import project_databases


@pytest.fixture
def env_local(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / ".env.local"
    monkeypatch.setattr(project_databases, "_ENV_LOCAL", path)
    for name in ("DATABASE_URL", "AGENT_HUB_DB_URL"):
        monkeypatch.delenv(name, raising=False)
    return path


def test_summitflow_uses_database_url(env_local: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://sf")
    assert project_databases.get_db_url_for_project("summitflow") == "postgresql://sf"


def test_other_projects_use_naming_convention(env_local: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_HUB_DB_URL", "postgresql://ah")
    assert project_databases.get_db_url_for_project("agent-hub") == "postgresql://ah"


def test_env_local_fills_missing_process_environment(env_local: Path) -> None:
    env_local.write_text("AGENT_HUB_DB_URL=postgresql://from-file\n")
    assert project_databases.get_db_url_for_project("agent-hub") == "postgresql://from-file"


def test_missing_url_returns_none(env_local: Path) -> None:
    assert project_databases.get_db_url_for_project("agent-hub") is None
