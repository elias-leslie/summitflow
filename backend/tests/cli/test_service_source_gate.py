"""Deploy through a pinned source mirror and the per-user deploy gate."""

from __future__ import annotations

import socket
import subprocess
import threading
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

import pytest

from app.utils import nightshift_stack
from cli.lib import service_deploy_client, service_ops


@pytest.fixture
def project(tmp_path: Path) -> service_ops.ProjectServices:
    return service_ops.ProjectServices(
        project_id="example", root=tmp_path / "checkout", backend_service="backend.service",
        frontend_service="frontend.service", default_workers=(), optional_workers=(),
        backend_port=8001, frontend_port=3001, backend_dir=tmp_path / "backend",
        frontend_dir=tmp_path / "frontend", health_endpoint="/health",
    )


def _git(*args: str, cwd: Path) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def test_source_repo_is_checked_out_at_the_pinned_commit(project, tmp_path, monkeypatch):
    monkeypatch.setenv("SUMMITFLOW_SERVICE_STATE_ROOT", str(tmp_path / "state"))
    work = tmp_path / "work"
    work.mkdir()
    _git("init", "-q", "-b", "main", cwd=work)
    _git("config", "user.email", "t@example.test", cwd=work)
    _git("config", "user.name", "t", cwd=work)
    (work / "file").write_text("one")
    _git("add", ".", cwd=work)
    _git("commit", "-qm", "one", cwd=work)
    first = _git("rev-parse", "HEAD", cwd=work)
    (work / "file").write_text("two")
    _git("commit", "-qam", "two", cwd=work)
    mirror = tmp_path / "mirror.git"
    _git("clone", "-q", "--bare", str(work), str(mirror), cwd=tmp_path)

    pinned = service_ops.use_source_repo(project, mirror, first)

    assert pinned.git_root == pinned.source_repo != project.root
    assert pinned.source_sha == first
    assert (pinned.git_root / "file").read_text() == "one"
    # Running again (a later deploy) reuses the clone and moves it to the new pin.
    second = _git("rev-parse", "HEAD", cwd=work)
    again = service_ops.use_source_repo(project, mirror, second)
    assert (again.git_root / "file").read_text() == "two"
    assert project.git_root == project.root


@pytest.mark.parametrize("sha", ["main", "ABCDEF" * 7, "a" * 39])
def test_source_repo_rejects_anything_but_a_full_sha(project, tmp_path, sha):
    with pytest.raises(service_ops.ServiceError, match="40-character"):
        service_ops.use_source_repo(project, tmp_path, sha)


def test_credstore_units_swap_home_secrets_for_the_root_owned_dir(project):
    svc = replace(project, runtime_user="svc")
    unit = (
        "[Service]\n"
        "EnvironmentFile=-%h/.env.local\n"
        "EnvironmentFile=%h/.env.local\n"
        "EnvironmentFile=%h/.config/credstore/example/extra\n"
    )

    out = service_ops.credstore_units(unit, svc)

    assert "%h" not in out
    assert "EnvironmentFile=-/etc/credstore.svc/example/env\n" in out
    assert "EnvironmentFile=/etc/credstore.svc/example/env\n" in out
    assert "EnvironmentFile=/etc/credstore.svc/example/extra\n" in out


def test_gate_client_sends_one_json_line_and_returns_the_exit_line(tmp_path, monkeypatch):
    monkeypatch.setattr(service_deploy_client, "SOCKET_DIR", tmp_path)
    seen: list[bytes] = []
    server = socket.socket(socket.AF_UNIX)
    server.bind(str(tmp_path / "svc.sock"))
    server.listen(1)

    def serve() -> None:
        conn, _ = server.accept()
        with conn:
            seen.append(conn.makefile("rb").readline())
            conn.sendall(b"building\n[gate] exit 3\n")

    thread = threading.Thread(target=serve)
    thread.start()
    try:
        assert service_deploy_client.send("svc", "example", "a" * 40, "deploy") == 3
    finally:
        thread.join(5)
        server.close()

    assert seen == [b'{"project": "example", "sha": "' + b"a" * 40 + b'", "verb": "deploy"}\n']


def test_gate_client_refuses_unknown_verbs():
    with pytest.raises(ValueError):
        service_deploy_client.send("svc", "example", "a" * 40, "destroy")


def test_gate_is_used_only_for_another_runtime_user(monkeypatch):
    monkeypatch.setattr(service_deploy_client.getpass, "getuser", lambda: "svc")
    assert service_deploy_client.delegated_user("svc") == ""
    assert service_deploy_client.delegated_user("") == ""
    assert service_deploy_client.delegated_user("broker") == "broker"


def _nightshift_says(monkeypatch, stdout: str, pending: str = "[]") -> Mock:
    def run(args, _timeout):
        done = subprocess.CompletedProcess(args, 0, pending if args[0] == "pending" else stdout, "")
        return done

    mock = Mock(side_effect=run)
    monkeypatch.setattr(nightshift_stack, "_run", mock)
    return mock


def test_stack_request_applied(monkeypatch):
    mock = _nightshift_says(monkeypatch, '{"outcome": "applied"}')

    result = nightshift_stack.request_stack("restart")

    assert result.success and not result.pending
    sent = mock.call_args_list[0].args[0]
    assert sent[:3] == ["request", "unit.restart", "unit=summitflow-stack.service"]


def test_stack_request_waiting_for_a_tap_returns_the_approve_link(monkeypatch):
    _nightshift_says(
        monkeypatch, '{"outcome": "pending"}',
        '[{"title": "Restart summitflow-stack.service", "url": "https://example.test/n/1"}]',
    )

    result = nightshift_stack.request_stack("stop")

    assert result.success and result.pending
    assert result.approve_url == "https://example.test/n/1"
    assert "https://example.test/n/1" in result.message


def test_stack_request_refused_is_a_failure(monkeypatch):
    _nightshift_says(monkeypatch, '{"outcome": "refused", "error": "not allowed"}')

    result = nightshift_stack.request_stack("start")

    assert not result.success and not result.pending
    assert "not allowed" in result.message


def test_backup_dump_uses_docker_only_before_the_stack_unit_exists(tmp_path, monkeypatch):
    from app.tasks import backup_native_infra as infra

    seen: list[list[str]] = []

    def stream(command, destination, **_kwargs):
        seen.append(command)
        destination.write_text("dump")
        return 0, b""

    monkeypatch.setattr(infra, "_run_plain_stream", stream)
    monkeypatch.delenv("POSTGRES_CONTAINER", raising=False)
    monkeypatch.setattr(infra, "_find_compose_container", lambda _service: "stack-postgres-1")
    infra._dump_infra_database(tmp_path / "a.sql")
    monkeypatch.setattr(infra, "_find_compose_container", lambda _service: None)
    infra._dump_infra_database(tmp_path / "b.sql")

    assert seen[0][:3] == ["docker", "exec", "stack-postgres-1"]
    assert seen[1][0] == "pg_dumpall" and "-h" in seen[1]


def test_compose_container_lookup_is_skipped_once_the_stack_unit_exists(monkeypatch):
    from app.tasks import backup_native_infra as infra

    monkeypatch.setattr(infra.nightshift_stack, "stack_installed", lambda: True)

    assert infra._find_compose_container("postgres") is None
