"""Deploy through a pinned source mirror and the per-user deploy gate."""

from __future__ import annotations

import json
import socket
import subprocess
import threading
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.utils import nightshift_stack
from cli.lib import service_deploy_client, service_ops, service_owner_artifact


@pytest.fixture
def project(tmp_path: Path) -> service_ops.ProjectServices:
    return service_ops.ProjectServices(
        project_id="example", root=tmp_path / "checkout", backend_service="backend.service",
        frontend_service="frontend.service", default_workers=(), optional_workers=(),
        backend_port=8001, frontend_port=3001, backend_dir=tmp_path / "backend",
        frontend_dir=tmp_path / "frontend", health_endpoint="/health",
        runtime_user="svc",
    )


def _git(*args: str, cwd: Path) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def _identity(project):
    return {"project": {"id": project.project_id}, "runtime": {
        "runtime_user": project.runtime_user, "backend_port": project.backend_port,
        "frontend_port": project.frontend_port, "backend_dir": "api", "frontend_dir": "web",
        "health_endpoint": "/ready", "backend_extras": ["runtime"], "infra": [],
    }, "services": {"backend": project.backend_service, "frontend": project.frontend_service,
                    "default_workers": list(project.default_workers), "optional_workers": list(project.optional_workers)}}


def _source_repo(tmp_path, identity):
    work = tmp_path / "work"
    work.mkdir()
    _git("init", "-q", "-b", "main", cwd=work)
    _git("config", "user.email", "t@example.test", cwd=work)
    _git("config", "user.name", "t", cwd=work)
    (work / "project.identity.json").write_text(json.dumps(identity))
    _git("add", ".", cwd=work)
    _git("commit", "-qm", "identity", cwd=work)
    return work, _git("rev-parse", "HEAD", cwd=work)


def test_source_repo_is_checked_out_at_the_pinned_commit(project, tmp_path, monkeypatch):
    monkeypatch.setenv("SUMMITFLOW_SERVICE_STATE_ROOT", str(tmp_path / "state"))
    work = tmp_path / "work"
    work.mkdir()
    _git("init", "-q", "-b", "main", cwd=work)
    _git("config", "user.email", "t@example.test", cwd=work)
    _git("config", "user.name", "t", cwd=work)
    (work / "project.identity.json").write_text(json.dumps(_identity(project)))
    (work / "file").write_text("one")
    _git("add", ".", cwd=work)
    _git("commit", "-qm", "one", cwd=work)
    first = _git("rev-parse", "HEAD", cwd=work)
    (work / "file").write_text("two")
    later_identity = _identity(project)
    later_identity["runtime"]["health_endpoint"] = "/later"
    (work / "project.identity.json").write_text(json.dumps(later_identity))
    _git("commit", "-qam", "two", cwd=work)
    mirror = tmp_path / "mirror.git"
    _git("clone", "-q", "--bare", str(work), str(mirror), cwd=tmp_path)

    pinned = service_ops.use_source_repo(project, mirror, first)

    assert pinned.git_root == pinned.source_repo != project.root
    assert pinned.source_sha == first
    assert (pinned.git_root / "file").read_text() == "one"
    assert pinned.backend_dir == project.root / "api"
    assert pinned.frontend_dir == project.root / "web"
    assert pinned.health_endpoint == "/ready"
    assert pinned.backend_extras == ("runtime",)
    assert pinned.infra == ()
    # Running again (a later deploy) reuses the clone and moves it to the new pin.
    second = _git("rev-parse", "HEAD", cwd=work)
    again = service_ops.use_source_repo(project, mirror, second)
    assert (again.git_root / "file").read_text() == "two"
    assert again.health_endpoint == "/later"
    assert project.git_root == project.root


@pytest.mark.parametrize(("section", "field", "value"), [
    ("project", "id", "other"), ("project", "id", ""),
    ("runtime", "runtime_user", "owner"), ("runtime", "runtime_user", "broker"),
    ("runtime", "runtime_user", ""), ("runtime", "backend_port", 9999),
    ("runtime", "runtime_user", []), ("runtime", "backend_port", True),
    ("runtime", "frontend_port", "3001"), ("runtime", "backend_dir", "../outside"),
    ("runtime", "frontend_dir", "/outside"), ("services", "backend", "foreign.service"),
    ("services", "frontend", "foreign.service"),
    ("services", "default_workers", ["foreign.service"]),
    ("services", "optional_workers", ["foreign.service"]),
])
def test_source_repo_rejects_identity_outside_the_admitted_request(project, tmp_path, monkeypatch,
                                                                 section, field, value):
    monkeypatch.setenv("SUMMITFLOW_SERVICE_STATE_ROOT", str(tmp_path / "state"))
    identity = _identity(project)
    identity[section][field] = value
    repo, sha = _source_repo(tmp_path, identity)
    with pytest.raises(service_ops.ServiceError, match="identity"):
        service_ops.use_source_repo(project, repo, sha)


def test_source_repo_requires_a_committed_identity(project, tmp_path, monkeypatch):
    monkeypatch.setenv("SUMMITFLOW_SERVICE_STATE_ROOT", str(tmp_path / "state"))
    repo, _ = _source_repo(tmp_path, _identity(project))
    _git("rm", "project.identity.json", cwd=repo)
    _git("commit", "-qm", "missing identity", cwd=repo)
    with pytest.raises(service_ops.ServiceError, match="identity"):
        service_ops.use_source_repo(project, repo, _git("rev-parse", "HEAD", cwd=repo))


@pytest.mark.parametrize("user", ["svc", "broker", "agent"])
def test_source_repo_preserves_each_admitted_service_user(project, tmp_path, monkeypatch, user):
    monkeypatch.setenv("SUMMITFLOW_SERVICE_STATE_ROOT", str(tmp_path / "state"))
    admitted = replace(project, runtime_user=user)
    repo, sha = _source_repo(tmp_path, _identity(admitted))
    assert service_ops.use_source_repo(admitted, repo, sha).runtime_user == user


def test_identity_mismatch_stops_before_dependency_install(project, tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from cli.commands import service

    monkeypatch.setenv("SUMMITFLOW_SERVICE_STATE_ROOT", str(tmp_path / "state"))
    identity = _identity(project)
    identity["runtime"]["runtime_user"] = "owner"
    repo, sha = _source_repo(tmp_path, identity)
    monkeypatch.setattr(service, "_load", lambda _: project)
    dependencies = Mock()
    monkeypatch.setattr(service_ops, "install_clone_dependencies", dependencies)
    result = CliRunner().invoke(service.app, ["rebuild", "example", "--source-repo", str(repo), "--sha", sha])
    assert result.exit_code == 1
    assert "identity runtime user" in result.output
    dependencies.assert_not_called()


@pytest.mark.parametrize("drift", [False, True])
def test_local_acceptance_stays_bound_to_the_requested_sha(project, tmp_path, monkeypatch, drift):
    from cli.lib import acceptance_coordinator

    monkeypatch.setenv("SUMMITFLOW_SERVICE_STATE_ROOT", str(tmp_path / "state"))
    repo, sha = _source_repo(tmp_path, _identity(project))
    (repo / "later").touch()
    _git("add", ".", cwd=repo)
    _git("commit", "-qm", "later", cwd=repo)
    later = _git("rev-parse", "HEAD", cwd=repo)
    pinned = service_ops.use_source_repo(project, repo, sha)
    accept = Mock(return_value=SimpleNamespace(receipt={"full": True}))
    monkeypatch.setattr(acceptance_coordinator, "accept_source", accept)
    if drift:
        _git("checkout", "-q", "--detach", later, cwd=pinned.git_root)
        with pytest.raises(service_ops.ServiceError, match="requested commit"):
            service_ops._acceptance_candidate(pinned, None)
        accept.assert_not_called()
    else:
        assert service_ops._acceptance_candidate(pinned, None) == {"full": True}
        accept.assert_called_once_with(pinned.git_root, sha=sha, materialization="actual")


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


def test_owner_prepare_emits_only_descriptor_on_stdout(monkeypatch):
    import json

    from typer.testing import CliRunner

    from cli.commands import service
    from cli.lib import service_owner_runtime

    def prepare(project, **kwargs):
        print("dependency build output")
        return {"project": project, **kwargs}

    monkeypatch.setattr(service_owner_runtime, "prepare", prepare)
    result = CliRunner().invoke(service.app, ["owner-prepare", "example", "--sha", "a" * 40,
                                            "--build-id", "b" * 32, "--tool-revision", "c" * 40])
    assert result.exit_code == 0
    assert json.loads(result.stdout)["project"] == "example"
    assert "dependency build output" in result.stderr


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


def test_clone_dependencies_install_in_the_pinned_clone_not_the_checkout(project, tmp_path, monkeypatch):
    clone = tmp_path / "state" / "source"
    (clone / "backend").mkdir(parents=True)
    (clone / "frontend").mkdir()
    (clone / "frontend" / "package.json").write_text("{}")
    pinned = replace(project, root=tmp_path / "checkout", backend_dir=tmp_path / "checkout" / "backend",
                     frontend_dir=tmp_path / "checkout" / "frontend", source_repo=clone)
    seen = []
    monkeypatch.setattr(service_ops, "sync_backend", lambda p: seen.append(("backend", p.backend_dir)) or 0)
    monkeypatch.setattr(service_ops, "run", lambda command, cwd=None, **kw: seen.append((tuple(command), cwd)) or 0)

    assert service_ops.install_clone_dependencies(pinned) == 0
    assert seen == [("backend", clone / "backend"), (("pnpm", "install", "--frozen-lockfile"), clone / "frontend")]
    assert service_ops.install_clone_dependencies(project) == 0  # no pinned source: nothing to install
    monkeypatch.setattr(service_ops, "sync_backend", lambda p: 3)
    assert service_ops.install_clone_dependencies(pinned) == 3


@pytest.fixture
def owner_storage(monkeypatch):
    initialize = Mock()
    monkeypatch.setattr(service_owner_artifact, "initialize_owner_store", initialize)
    return initialize


def test_owner_route_uses_typed_nightshift_action_and_requires_completion(monkeypatch, owner_storage):
    monkeypatch.setattr(service_deploy_client.shutil, "which", lambda _: "/usr/bin/nightshift")
    run = Mock(return_value=subprocess.CompletedProcess([], 0, '{"outcome":"applied"}', ""))
    monkeypatch.setattr(service_deploy_client.safe_subprocess, "run", run)
    assert service_deploy_client.send("owner", "example", "a" * 40, "deploy") == 0
    owner_storage.assert_called_once_with("example")
    assert run.call_args.args[0][:6] == [
        "/usr/bin/nightshift", "request", "owner.deploy", "project=example", "sha=" + "a" * 40, "operation=deploy",
    ]
    run.return_value = subprocess.CompletedProcess([], 0, '{"outcome":"pending"}', "")
    assert service_deploy_client.send("owner", "example", "a" * 40, "deploy") == 1
    run.return_value = subprocess.CompletedProcess([], 1, '{"outcome":"applied"}', "")
    assert service_deploy_client.send("owner", "example", "a" * 40, "deploy") == 1


def test_owner_route_missing_never_uses_socket_or_caller_manager(monkeypatch):
    monkeypatch.setattr(service_deploy_client.shutil, "which", lambda _: None)
    monkeypatch.setattr(service_deploy_client.socket, "socket", Mock(side_effect=AssertionError("owner socket")))
    with pytest.raises(OSError, match="not installed"):
        service_deploy_client.send("owner", "example", "a" * 40, "deploy")
    monkeypatch.setattr(service_deploy_client.getpass, "getuser", lambda: "owner")
    assert service_deploy_client.delegated_user("owner") == "owner"


def test_owner_credentials_keep_existing_home_paths(project, tmp_path, monkeypatch):
    owner = replace(project, runtime_user="owner")
    unit = "[Service]\nEnvironmentFile=-%h/.env.local\nEnvironmentFile=%h/.config/credstore/example/env\n"
    assert service_ops.credstore_units(unit, owner) == unit
    monkeypatch.setattr(service_ops.Path, "home", lambda: tmp_path)
    assert service_ops.credstore_root(owner) == tmp_path / ".config/credstore"


def test_owner_source_override_cannot_bypass_nightshift(project, monkeypatch):
    from typer.testing import CliRunner

    from cli.commands import service
    monkeypatch.setattr(service, "_load", lambda _: replace(project, runtime_user="owner"))
    local = Mock(side_effect=AssertionError("local source deployment"))
    monkeypatch.setattr(service_ops, "use_source_repo", local)
    result = CliRunner().invoke(service.app, ["rebuild", "example", "--source-repo", "/tmp/source", "--sha", "a" * 40])
    assert result.exit_code == 1
    assert "Nightshift" in result.output
    local.assert_not_called()


def test_owner_status_does_not_require_checkout_git(project, monkeypatch):
    from typer.testing import CliRunner

    from cli.commands import service
    monkeypatch.setattr(service, "_load", lambda _: replace(project, runtime_user="owner"))
    monkeypatch.setattr(service_deploy_client, "main_sha", Mock(side_effect=AssertionError("unnecessary source lookup")))
    send = Mock(return_value=0)
    monkeypatch.setattr(service_deploy_client, "send", send)
    result = CliRunner().invoke(service.app, ["status", "example"])
    assert result.exit_code == 0
    send.assert_called_once_with("owner", "example", "", "status")


def test_owner_main_validation_always_uses_agent_job(monkeypatch):
    runner = Mock(return_value=subprocess.CompletedProcess([], 0, "a" * 40 + "\n", ""))
    monkeypatch.setattr(service_deploy_client, "run_as_agent", runner)
    monkeypatch.setattr(service_deploy_client, "run_source_git", Mock(side_effect=AssertionError("owner Git")))
    assert service_deploy_client.main_sha(Path("/checkout"), as_agent=True) == "a" * 40
    assert runner.call_args.args[0][-1] == "refs/heads/main^{commit}"


def test_owner_migration_uses_existing_home_credentials(project, tmp_path, monkeypatch):
    backend = tmp_path / "backend"
    (backend / ".venv/bin").mkdir(parents=True)
    (backend / "alembic.ini").touch()
    (backend / ".venv/bin/alembic").touch()
    monkeypatch.setattr(service_ops.Path, "home", lambda: tmp_path / "owner-home")
    migration = Mock(return_value={})
    monkeypatch.setattr(service_ops.migration_env, "migration_env", migration)
    monkeypatch.setattr(service_ops, "run", Mock(return_value=0))
    owner = replace(project, backend_dir=backend, runtime_user="owner")
    assert service_ops.run_migrations(owner) == 0
    assert migration.call_args.kwargs["credstore"] == tmp_path / "owner-home/.config/credstore/example/env"


@pytest.mark.parametrize(("verb", "action", "params"), [
    ("rollback", "owner.deploy", ["project=example", "sha=" + "a" * 40, "operation=rollback"]),
    ("status", "owner.status", ["project=example"]),
    ("stop", "owner.service", ["project=example", "operation=stop"]),
])
def test_owner_verb_mapping(monkeypatch, owner_storage, verb, action, params):
    monkeypatch.setattr(service_deploy_client.shutil, "which", lambda _: "/usr/bin/nightshift")
    run = Mock(return_value=subprocess.CompletedProcess([], 0, '{"outcome":"noop"}', ""))
    monkeypatch.setattr(service_deploy_client.safe_subprocess, "run", run)
    assert service_deploy_client.send("owner", "example", "a" * 40, verb) == 0
    owner_storage.assert_not_called()
    assert run.call_args.args[0][:3 + len(params)] == ["/usr/bin/nightshift", "request", action, *params]


@pytest.mark.parametrize(("outcome", "returncode", "expected"), [
    ("no-op", 0, 0),
    ("noop", 0, 0),
    ("no-op", 1, 1),
    ("pending", 0, 1),
])
def test_owner_action_response_accepts_completed_no_op(monkeypatch, outcome, returncode, expected):
    monkeypatch.setattr(service_deploy_client.shutil, "which", lambda _: "/usr/bin/nightshift")
    completed = subprocess.CompletedProcess([], returncode, '{"outcome":"' + outcome + '"}', "")
    monkeypatch.setattr(service_deploy_client.safe_subprocess, "run", Mock(return_value=completed))
    assert service_deploy_client.send("owner", "example", "", "status") == expected
