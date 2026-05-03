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


def test_spawn_pgweb_uses_posix_spawn_sets_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, bool, list[tuple[int, int, int]]]] = []

    def fake_posix_spawn(
        path: str,
        argv: list[str],
        env: dict[str, str],
        *,
        file_actions: list[tuple[int, int, int]],
        setsid: bool,
    ) -> int:
        calls.append((path, setsid, file_actions))
        return 1234

    monkeypatch.setattr(db_workbench.os, "posix_spawn", fake_posix_spawn)

    pid = db_workbench._spawn_pgweb(
        ["/usr/bin/pgweb", "--listen=9081"],
        {"PGWEB_DATABASE_URL": "postgresql://example/db"},
        tmp_path / "pgweb.log",
    )

    assert pid == 1234
    assert calls[0][0] == "/usr/bin/pgweb"
    assert calls[0][1] is True
    assert any(action[0] == db_workbench.os.POSIX_SPAWN_DUP2 for action in calls[0][2])


def test_spawn_pgweb_falls_back_when_setsid_is_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    setsid_values: list[bool] = []

    def fake_posix_spawn(
        _path: str,
        _argv: list[str],
        _env: dict[str, str],
        *,
        file_actions: list[tuple[int, int, int]],
        setsid: bool,
    ) -> int:
        assert file_actions
        setsid_values.append(setsid)
        if setsid:
            raise NotImplementedError("setsid unavailable")
        return 1234

    monkeypatch.setattr(db_workbench.os, "posix_spawn", fake_posix_spawn)

    pid = db_workbench._spawn_pgweb(
        ["/usr/bin/pgweb", "--listen=9081"],
        {"PGWEB_DATABASE_URL": "postgresql://example/db"},
        tmp_path / "pgweb.log",
    )

    assert pid == 1234
    assert setsid_values == [True, False]
