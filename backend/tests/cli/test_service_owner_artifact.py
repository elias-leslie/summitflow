"""Portable artifact import and owner activation operate on disposable releases."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tarfile
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from cli.lib import service_ops
from cli.lib import service_owner_artifact as artifact
from cli.lib import service_owner_runtime as owner
from cli.lib import service_release as releases


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("SUMMITFLOW_SERVICE_STATE_ROOT", str(tmp_path / "private"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setattr(artifact, "exchange_root", lambda: tmp_path / "exchange")
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    (checkout / "package.json").write_text('{"type":"module"}')
    units = owner._units_dir()
    units.mkdir(parents=True)
    (units / "example.service").write_text("original")
    return service_ops.ProjectServices("example", checkout, "example.service", "", (), (), 0, 0,
                                       checkout, checkout, "/health", runtime_user="owner", infra=())


def exported(runtime, tmp_path, *, build="b" * 32, sha="a" * 40):
    root = tmp_path / build / "source"
    root.mkdir(parents=True)
    (root / "package.json").write_text('{"type":"module"}')
    (root / "index.js").write_text('console.log("accepted portable output")')
    destination = artifact.exchange_root() / "example" / build
    destination.mkdir(parents=True)
    archive = destination / "runtime.tar"
    with tarfile.open(archive, "w") as archive_file:
        archive_file.add(root, arcname="source")
    return {"schema": 1, "project": "example", "build_id": build, "tool_revision": "tool",
            "source": {"acceptance_id": "f" * 64, "source_commit": sha,
                       "source_tree": "c" * 40, "coverage": "full"},
            "built_phases": ["backend_dependencies", "frontend_build"],
            "archive_size": archive.stat().st_size, "archive_sha256": artifact.digest(archive)}


def tracked_sources(root):
    return {path.relative_to(root).as_posix(): ("100755" if path.stat().st_mode & 0o111 else "100644",
            hashlib.sha1(f"blob {path.stat().st_size}\0".encode() + path.read_bytes()).hexdigest())
            for path in root.rglob("*") if path.is_file() and ".venv" not in path.parts}


def import_exported(descriptor, tracked=None):
    if tracked is None:
        # Tests retain the canonical original bytes outside the transfer archive.
        tracked = tracked_sources(artifact.exchange_root().parent / descriptor["build_id"] / "source")

    return artifact.import_artifact(descriptor, project_id="example", sha=descriptor["source"]["source_commit"],
                                    build_id=descriptor["build_id"], tool_revision="tool", tracked=tracked)


def test_disposable_node_artifact_round_trip(runtime, tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is unavailable")
    release = import_exported(exported(runtime, tmp_path))
    result = subprocess.run([node, str(release.source_root / "index.js")], capture_output=True, text=True, check=True)
    assert result.stdout.strip() == "accepted portable output"
    assert releases._read_receipt(release)["source"]["coverage"] == "full"
    assert owner._pointer("example", "current") is None


@pytest.mark.parametrize("corruption", ["digest", "source", "coverage"])
def test_bad_identity_rejected_without_activation(runtime, tmp_path, monkeypatch, corruption):
    descriptor = exported(runtime, tmp_path)
    if corruption == "digest":
        descriptor["archive_sha256"] = "0" * 64
    elif corruption == "source":
        descriptor["source"]["source_commit"] = "d" * 40
    else:
        descriptor["source"]["coverage"] = "task"
    restart = Mock()
    monkeypatch.setattr(service_ops, "restart_service", restart)
    with pytest.raises((ValueError, releases.ReleaseError)):
        artifact.import_artifact(descriptor, project_id="example", sha="a" * 40,
                                 build_id=descriptor["build_id"], tool_revision="tool", tracked={})
    restart.assert_not_called()
    assert owner._pointer("example", "current") is None


def test_python_refused_before_release_mutation(runtime):
    (runtime.root / "pyproject.toml").write_text("[project]")
    with pytest.raises(ValueError, match="Python environment relocation"):
        artifact.portable(runtime)
    assert not releases._project_state("example").exists()


@pytest.mark.parametrize("fails", [False, True])
def test_activation_and_verified_previous_runtime_restore(runtime, tmp_path, monkeypatch, fails):
    old = import_exported(exported(runtime, tmp_path, build="d" * 32, sha="e" * 40))
    releases.complete_release(old, service_references=set())
    descriptor = exported(runtime, tmp_path)
    config = {"tool_revision": "tool", "tool_argv": ["/trusted/st"], "projects": {"example": {"units": ["example.service"]}}}
    monkeypatch.setattr(owner, "_identity", lambda _: (1000, config))
    monkeypatch.setattr(service_ops, "load_project", lambda _: runtime)
    monkeypatch.setattr(owner.service_deploy_client, "main_sha", lambda *args, **kwargs: "a" * 40)
    monkeypatch.setattr(owner.uuid, "uuid4", lambda: SimpleNamespace(hex="b" * 32))
    def agent_call(argv, **kwargs):
        assert argv[0] == "/trusted/st"
        if "checkout-job" in argv:
            payload = json.loads(kwargs["input"])
            proof = {"source": descriptor["source"], "tracked": tracked_sources(tmp_path / descriptor["build_id"] / "source")}
            return SimpleNamespace(returncode=0, stdout=json.dumps(proof if payload["operation"] == "validate" else {"cleaned": True}))
        return SimpleNamespace(returncode=0, stdout=json.dumps(descriptor))
    monkeypatch.setattr(owner, "run_as_agent", agent_call)
    for name in ("sync_backend", "build_frontend", "run_release_install"):
        monkeypatch.setattr(service_ops, name, Mock(side_effect=AssertionError("owner must never build")))
    monkeypatch.setattr(service_ops, "run_migrations", lambda _: 0)
    monkeypatch.setattr(service_ops, "sync_seeds", lambda _: 0)
    monkeypatch.setattr(service_ops, "run", lambda _: 0)
    def sync(project):
        (owner._units_dir() / "example.service").write_text(str(project.root))
        return 0
    monkeypatch.setattr(service_ops, "sync_systemd_units", sync)
    restarts = Mock(return_value=0)
    monkeypatch.setattr(service_ops, "restart_service", restarts)
    health = Mock(side_effect=lambda project: int(fails and project.root != old.source_root))
    monkeypatch.setattr(service_ops, "verify_health", health)
    request = {"schema": 1, "request_id": "request", "action": "owner.deploy", "expected_uid": 1000,
               "tool_revision": "tool", "params": {"project": "example", "sha": "a" * 40, "operation": "deploy"}}
    request["before"] = owner.handle("precheck", request)["before"]
    if fails:
        with pytest.raises(ValueError, match="health or seeds"):
            owner.handle("apply", request)
        assert owner._pointer("example", "current") == old.build_id
        assert (owner._units_dir() / "example.service").read_text() == "original"
        assert health.call_args.args[0].root == old.source_root
        assert restarts.call_count == 2
    else:
        assert owner.handle("apply", request)["ok"] is True
        assert owner._pointer("example", "current") == descriptor["build_id"]
        receipt = releases._project_state("example") / "receipts" / f'{descriptor["build_id"]}.json'
        assert releases.validate_deployment_receipt(receipt)["state"] == "succeeded"
        assert owner.handle("verify", request)["ok"] is True
        assert owner.handle("rollback", request)["result"]["restored"] is True
        assert owner._pointer("example", "current") == old.build_id


def test_rollback_preserves_later_pointer(runtime, tmp_path, monkeypatch):
    old = import_exported(exported(runtime, tmp_path, build="d" * 32))
    releases.complete_release(old, service_references=set())
    frozen = {"current": None, "previous": None, "units": {"example.service": "stale"}, "optional": []}
    restart = Mock()
    monkeypatch.setattr(service_ops, "restart_service", restart)
    assert owner._restore(runtime, frozen, "b" * 32) is False
    assert owner._pointer("example", "current") == old.build_id
    assert (owner._units_dir() / "example.service").read_text() == "original"
    restart.assert_not_called()


def test_node_test_only_python_environment_is_not_a_runtime(runtime):
    (runtime.root / "pyproject.toml").write_text('[project]\ndependencies=[]\n[tool.uv]\npackage=false\n')
    (runtime.root / ".venv").mkdir()
    artifact.portable(runtime)


def test_agent_prepare_exports_built_output_without_python_test_environment(runtime, tmp_path, monkeypatch):
    descriptor = exported(runtime, tmp_path, build="d" * 32)
    prepared = import_exported(descriptor)
    built = service_ops.project_at_source(runtime, prepared.source_root)
    (built.root / ".venv").mkdir()
    (built.root / ".env.example").write_text("EXAMPLE=sample")
    (built.root / "pyproject.toml").write_text('[project]\ndependencies=[]\n[tool.uv]\npackage=false\n')
    monkeypatch.setattr(service_ops, "load_project", lambda _: runtime)
    monkeypatch.setattr(service_ops, "prepare_accepted_release", lambda _: (prepared, built))
    monkeypatch.setattr(artifact.acceptance, "_source_tree_entries", lambda *args: tracked_sources(built.root))
    dependencies = Mock(return_value=0)
    monkeypatch.setattr(service_ops, "sync_backend", dependencies)
    def build(project):
        (project.root / "index.js").write_text('console.log("agent-built output")')
        return 0
    monkeypatch.setattr(service_ops, "build_frontend", build)
    result = artifact.prepare("example", sha="a" * 40, build_id="b" * 32, tool_revision="tool")
    dependencies.assert_called_once_with(built)
    release = import_exported(result, tracked=tracked_sources(built.root))
    assert "agent-built output" in (release.source_root / "index.js").read_text()
    assert not (release.source_root / ".venv").exists()
    assert (release.source_root / ".env.example").is_file()


@pytest.mark.parametrize("relative", ["scripts/run.sh", "scripts/systemd/example.service"])
def test_rehashed_archive_cannot_replace_accepted_runner_or_unit(runtime, tmp_path, monkeypatch, relative):
    descriptor = exported(runtime, tmp_path)
    original = tmp_path / descriptor["build_id"] / "source"
    tracked_file = original / relative
    tracked_file.parent.mkdir(parents=True, exist_ok=True)
    tracked_file.write_text("accepted tracked runtime bytes")
    tracked = tracked_sources(original)
    tracked_file.write_text("substituted runtime bytes")
    archive = artifact.exchange_root() / "example" / descriptor["build_id"] / "runtime.tar"
    with tarfile.open(archive, "w") as transfer:
        transfer.add(original, arcname="source")
    descriptor.update(archive_size=archive.stat().st_size, archive_sha256=artifact.digest(archive))
    restart = Mock()
    monkeypatch.setattr(service_ops, "restart_service", restart)
    with pytest.raises(ValueError, match="differs from accepted commit"):
        import_exported(descriptor, tracked=tracked)
    restart.assert_not_called()
    assert owner._pointer("example", "current") is None


def test_self_reported_full_proof_requires_canonical_acceptance(runtime, tmp_path, monkeypatch):
    descriptor = exported(runtime, tmp_path)
    proof_dir = tmp_path / "canonical-proof"
    proof_dir.mkdir()
    (proof_dir / f'{descriptor["source"]["acceptance_id"]}.json').write_text(json.dumps({
        "coverage": "full", "state": "success", "acceptance_id": descriptor["source"]["acceptance_id"]}))
    monkeypatch.setattr(service_ops, "load_project", lambda _: runtime)
    monkeypatch.setattr(artifact.acceptance, "acceptance_artifact_directory", lambda _: proof_dir)
    with pytest.raises(artifact.acceptance.AcceptanceError, match="integrity check failed"):
        artifact.run_job({"project": "example", "operation": "validate", "descriptor": descriptor})


@pytest.mark.parametrize("accepted", [False, True])
def test_cleanup_removes_only_agent_transfer_and_prepared_staging(runtime, tmp_path, monkeypatch, accepted):
    descriptor = exported(runtime, tmp_path)
    staged = import_exported(descriptor)
    descriptor["agent_build_id"] = staged.build_id
    if accepted:
        releases.complete_release(staged, service_references=None)
    monkeypatch.setattr(service_ops, "load_project", lambda _: runtime)
    assert artifact.run_job({"project": "example", "operation": "cleanup", "descriptor": descriptor}) == {"cleaned": True}
    assert staged.source_root.exists() is accepted
    assert not (artifact.exchange_root() / "example" / descriptor["build_id"]).exists()
    if accepted:
        assert owner._pointer("example", "current") == staged.build_id



@pytest.mark.parametrize("kind", ["timer", "socket"])
@pytest.mark.parametrize("later_edit", [False, True])
def test_rollback_restores_activated_companion_and_preserves_later_edits(runtime, tmp_path, monkeypatch, kind, later_edit):
    old = import_exported(exported(runtime, tmp_path, build="d" * 32))
    releases.complete_release(old, service_references=None)
    project = replace(runtime, default_workers=(f"example-worker.{kind}",))
    companion = owner._units_dir() / "example-worker.service"
    companion.write_text("previous companion")
    frozen = {"current": old.build_id, "previous": None,
              "units": owner._unit_contents(project), "optional": []}
    assert "example-worker.service" in frozen["units"]
    companion.write_text("deployed companion")
    (owner._units_dir() / "example.service").write_text("deployed backend")
    frozen["applied_units"] = owner._unit_contents(project)
    monkeypatch.setattr(service_ops, "run", Mock(return_value=0))
    restart = Mock(return_value=0)
    monkeypatch.setattr(service_ops, "restart_service", restart)
    health = Mock(return_value=0)
    monkeypatch.setattr(service_ops, "verify_health", health)
    if later_edit:
        companion.write_text("later owner edit")
        with pytest.raises(ValueError, match="preserving later edits"):
            owner._restore(project, frozen, "b" * 32, allow_uncommitted=True)
        assert companion.read_text() == "later owner edit"
        assert (owner._units_dir() / "example.service").read_text() == "deployed backend"
        restart.assert_not_called()
    else:
        assert owner._restore(project, frozen, "b" * 32, allow_uncommitted=True) is True
        assert companion.read_text() == "previous companion"
        assert (owner._units_dir() / "example.service").read_text() == "original"
        assert health.call_args.args[0].root == old.source_root



@pytest.fixture
def owner_store(runtime, monkeypatch):
    from app.services import tether

    agent_uid = os.getuid()
    owner_uid = agent_uid + 1
    monkeypatch.setattr(tether, "_agent_uid", lambda: agent_uid)
    monkeypatch.setattr(owner, "_trusted_json", lambda _: {
        "owner_uid": owner_uid, "projects": {"example": {"units": ["example.service"]}}})
    return owner_uid


def test_owner_store_inherits_read_access_under_umask_077(owner_store):
    if not shutil.which("setfacl") or not shutil.which("getfacl"):
        pytest.skip("ACL host tools are unavailable")
    previous_umask = os.umask(0o077)
    try:
        artifact.initialize_owner_store("example")
        build = artifact.exchange_root() / "example" / ("a" * 32)
        build.mkdir()
        archive = build / "runtime.tar"
        archive.write_bytes(b"disposable artifact")
    finally:
        os.umask(previous_umask)
    for path, expected in ((artifact.exchange_root(), "r-x"), (build.parent, "r-x"),
                           (build, "r-x"), (archive, "r--")):
        acl = subprocess.run(["getfacl", "--omit-header", "--numeric", str(path)],
                             capture_output=True, text=True, check=True).stdout
        entry = next(line for line in acl.splitlines() if line.startswith(f"user:{owner_store}:"))
        assert "w" not in entry
        assert (f"effective:{expected}" in entry or entry == f"user:{owner_store}:{expected}")
        assert "other::---" in acl
        assert "group::---" in acl


def test_owner_store_does_not_run_for_owner_callers(runtime, monkeypatch):
    from app.services import tether

    monkeypatch.setattr(tether, "_agent_uid", lambda: os.getuid() + 1)
    monkeypatch.setattr(owner, "_trusted_json", Mock(side_effect=AssertionError("owner caller must skip storage initialization")))
    artifact.initialize_owner_store("example")
    assert not artifact.exchange_root().exists()


@pytest.mark.parametrize("location", ["root", "project"])
@pytest.mark.parametrize("target_kind", ["directory", "file"])
def test_owner_store_refuses_symlink_directories(owner_store, tmp_path, location, target_kind):
    target = tmp_path / "unrelated"
    if target_kind == "directory":
        target.mkdir()
    else:
        target.write_text("unrelated data")
    path = artifact.exchange_root()
    if location == "project":
        path.mkdir()
        path = path / "example"
    path.symlink_to(target, target_is_directory=True)
    with pytest.raises(ValueError, match="without symlinks"):
        artifact.initialize_owner_store("example")
    if target_kind == "directory":
        assert not list(target.iterdir())
    else:
        assert target.read_text() == "unrelated data"


def test_owner_store_refuses_foreign_owned_directory(owner_store, monkeypatch):
    from types import SimpleNamespace

    root = artifact.exchange_root()
    root.mkdir()
    original_lstat = type(root).lstat
    monkeypatch.setattr(type(root), "lstat", lambda path: (
        SimpleNamespace(st_mode=0o40700, st_uid=os.getuid() + 2) if path == root else original_lstat(path)))
    with pytest.raises(ValueError, match="agent-owned directory"):
        artifact.initialize_owner_store("example")


def test_owner_store_refuses_unregistered_project_before_creating_dirs(owner_store):
    with pytest.raises(ValueError, match="not registered"):
        artifact.initialize_owner_store("unregistered")
    assert not artifact.exchange_root().exists()
