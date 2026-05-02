from __future__ import annotations

from pathlib import Path

import pytest

from app.services import db_workbench


def test_status_uses_same_origin_proxy_url(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUMMITFLOW_PGWEB_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("PGWEB_BIN", str(tmp_path / "missing-pgweb"))

    status = db_workbench.status_workbench("summitflow")

    assert status.running is False
    assert status.installed is False
    assert status.proxy_url == "/api/projects/summitflow/db-workbench/proxy/"
    assert status.direct_url is None


def test_project_db_url_reads_canonical_env_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    env_file = home / "summitflow" / "docker" / "compose" / ".env"
    env_file.parent.mkdir(parents=True)
    env_file.write_text("AGENT_HUB_DB_URL=postgresql://agent:pw@localhost/agent_hub\n")
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.delenv("AGENT_HUB_DB_URL", raising=False)

    assert (
        db_workbench.project_db_url("agent-hub")
        == "postgresql://agent:pw@localhost/agent_hub"
    )


def test_shared_project_uses_host_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("A_TERM_DB_URL", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://summitflow_app:pw@localhost/summitflow")
    monkeypatch.setattr(
        db_workbench,
        "get_project_identity",
        lambda project_id: (
            {"database": {"shared_with": "summitflow"}}
            if project_id == "a-term"
            else {}
        ),
    )

    assert (
        db_workbench.project_db_url("a-term")
        == "postgresql://summitflow_app:pw@localhost/summitflow"
    )


def test_global_project_uses_admin_url_at_postgres_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "DATABASE_ADMIN_URL",
        "postgresql://admin:pw@localhost:5432/summitflow?sslmode=disable",
    )

    assert (
        db_workbench.project_db_url("__global__")
        == "postgresql://admin:pw@localhost:5432/postgres?sslmode=disable"
    )


def test_global_project_can_build_admin_url_from_postgres_password(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.delenv("DATABASE_ADMIN_URL", raising=False)
    monkeypatch.setenv("POSTGRES_PASSWORD", "pw/with special")

    assert (
        db_workbench.project_db_url("__global__")
        == "postgresql://admin:pw%2Fwith%20special@localhost:5432/postgres"
    )


def test_unknown_project_reports_unconfigured(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SUMMITFLOW_PGWEB_STATE_DIR", str(tmp_path))
    monkeypatch.delenv("NO_DB_PROJECT_DB_URL", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(db_workbench, "get_project_identity", lambda _project_id: None)

    status = db_workbench.status_workbench("no-db-project")

    assert status.configured is False


def test_start_reports_missing_pgweb_after_db_url_resolution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SUMMITFLOW_PGWEB_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("PGWEB_BIN", str(tmp_path / "missing-pgweb"))
    monkeypatch.setenv("DATABASE_URL", "postgresql://summitflow_app@localhost/summitflow")

    with pytest.raises(db_workbench.DbWorkbenchError, match="pgweb binary not found"):
        db_workbench.start_workbench("summitflow")
