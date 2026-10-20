"""Portable artifact import and owner activation operate on disposable releases."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import zipfile
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


def test_unlocked_python_refused_before_release_mutation(runtime):
    (runtime.root / "pyproject.toml").write_text("[project]")
    with pytest.raises(ValueError, match=r"pyproject\.toml and uv\.lock"):
        artifact.portable(runtime)
    assert not releases._project_state("example").exists()


def test_locked_python_backend_needs_no_node_frontend(runtime):
    (runtime.root / "package.json").unlink()
    (runtime.root / "pyproject.toml").write_text('[project]\nname="example"\nversion="1"\n')
    (runtime.root / "uv.lock").write_text("version = 1\n")
    artifact.portable(runtime)


def test_python_outside_configured_backend_refused(runtime):
    (runtime.root / "pyproject.toml").write_text("[project]")
    (runtime.root / "uv.lock").write_text("version = 1\n")
    with pytest.raises(ValueError, match="configured backend"):
        artifact.portable(replace(runtime, backend_dir=runtime.root / "backend"))


@pytest.mark.parametrize("external", [False, True])
def test_python_prefix_links_rebased_without_changing_binary_bytes(tmp_path, external):
    prefix = tmp_path / "original"
    prefix.mkdir()
    executable = prefix / "python"
    executable.write_bytes(b"unchanged Python ELF bytes")
    link = prefix / "python3"
    link.symlink_to(tmp_path / "outside" if external else executable)
    (prefix / "python-alias").symlink_to(link)
    bundle = tmp_path / "bundle"
    shutil.copytree(prefix, bundle, symlinks=True)
    if external:
        with pytest.raises(ValueError, match="external symlink"):
            artifact._internal_links(bundle, original=prefix)
    else:
        artifact._internal_links(bundle, original=prefix)
        assert os.readlink(bundle / "python3") == "python"
        assert (bundle / "python3").read_bytes() == executable.read_bytes()
        assert (bundle / "python-alias").read_bytes() == executable.read_bytes()


@pytest.fixture
def fake_python_prefix(tmp_path, monkeypatch):
    prefix = tmp_path / "interpreter"
    (prefix / "bin").mkdir(parents=True)
    version = f"python{sys.version_info.major}.{sys.version_info.minor}"
    (prefix / "bin" / version).write_bytes(b"\x7fELFtest interpreter")
    (prefix / "lib" / version / "encodings").mkdir(parents=True)
    (prefix / "lib" / version / "encodings/__init__.py").write_text("")
    (prefix / "lib" / f"lib{version}.so.1.0").write_bytes(b"unchanged shared library")
    monkeypatch.setattr(artifact.sys, "base_prefix", str(prefix))
    return prefix


@pytest.mark.parametrize("failed_phase", ["venv", "sync", "smoke", "smoke_exception", "editable"])
def test_python_build_failures_preserve_disposable_source(runtime, fake_python_prefix, monkeypatch, failed_phase):
    (runtime.root / "pyproject.toml").write_text('[project]\nname="example"\nversion="1"\n')
    (runtime.root / "uv.lock").write_text("version = 1\n")
    version = f"python{sys.version_info.major}.{sys.version_info.minor}"
    calls = []
    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        if argv[:2] == ["uv", "venv"]:
            if failed_phase == "venv":
                return 7
            bin_dir = runtime.root / ".venv/bin"
            bin_dir.mkdir(parents=True)
            (bin_dir / "python").symlink_to(runtime.root / ".python/bin" / version)
            return 0
        if argv[:2] == ["uv", "sync"]:
            assert {"--locked", "--no-editable", "--link-mode", "copy"} <= set(argv)
            assert kwargs["env"]["UV_PROJECT_ENVIRONMENT"] == str(runtime.root / ".venv")
            if failed_phase == "editable":
                dist = runtime.root / ".venv/lib" / version / "site-packages/example.dist-info"
                dist.mkdir(parents=True)
                (dist / "direct_url.json").write_text('{"dir_info":{"editable":true}}')
            return 8 if failed_phase == "sync" else 0
        assert kwargs["env"] == {"HOME": str(kwargs["cwd"]), "PATH": os.defpath, "LANG": "C.UTF-8"}
        assert not runtime.root.exists()
        if failed_phase == "smoke_exception":
            raise OSError("smoke interrupted")
        return 9
    monkeypatch.setattr(service_ops, "run", run)
    if failed_phase == "editable":
        with pytest.raises(ValueError, match="editable install"):
            artifact._prepare_python(runtime)
    elif failed_phase == "smoke_exception":
        with pytest.raises(OSError, match="smoke interrupted"):
            artifact._prepare_python(runtime)
    else:
        assert artifact._prepare_python(runtime) == {"venv": 7, "sync": 8, "smoke": 9}[failed_phase]
    assert runtime.root.is_dir()
    assert all(kwargs["_heavy"] for _, kwargs in calls)


@pytest.mark.timeout(120)
def test_locked_python_artifact_relocates_console_and_import_without_build_cache(runtime, tmp_path, monkeypatch):
    if not shutil.which("uv"):
        pytest.skip("uv is unavailable")
    # A real wheel and lock exercise uv's console launcher and non-editable
    # installation without network access or a dependency on cached packages.
    wheel = tmp_path / "relocation_probe-1.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("relocation_probe.py", 'def main():\n    print("relocated console works")\n')
        archive.writestr("relocation_probe-1.0.dist-info/METADATA", "Metadata-Version: 2.1\nName: relocation-probe\nVersion: 1.0\n")
        archive.writestr("relocation_probe-1.0.dist-info/WHEEL", "Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: true\nTag: py3-none-any\n")
        archive.writestr("relocation_probe-1.0.dist-info/entry_points.txt", "[console_scripts]\nartifact-probe = relocation_probe:main\n")
        archive.writestr("relocation_probe-1.0.dist-info/RECORD", "")
    prepared = import_exported(exported(runtime, tmp_path, build="d" * 32))
    built = service_ops.project_at_source(runtime, prepared.source_root)
    (built.root / "pyproject.toml").write_text(
        '[project]\nname="portable-example"\nversion="1.0"\n'
        f'requires-python=">={sys.version_info.major}.{sys.version_info.minor}"\n'
        f'dependencies=["relocation-probe @ {wheel.as_uri()}"]\n[tool.uv]\npackage=false\n')
    cache = tmp_path / "build-cache"
    monkeypatch.setenv("UV_CACHE_DIR", str(cache))
    assert service_ops.run(["uv", "lock", "--offline", "--python", sys.executable],
                           cwd=built.root, quiet_success=True, _heavy=True) == 0
    tracked = tracked_sources(built.root)
    monkeypatch.setattr(service_ops, "load_project", lambda _: built)
    monkeypatch.setattr(service_ops, "prepare_accepted_release", lambda _: (prepared, built))
    monkeypatch.setattr(artifact.acceptance, "_source_tree_entries", lambda *args: tracked)
    monkeypatch.setattr(service_ops, "build_frontend", Mock(return_value=0))
    descriptor = artifact.prepare("example", sha="a" * 40, build_id="b" * 32, tool_revision="tool")
    release = import_exported(descriptor, tracked=tracked)
    shutil.rmtree(built.root)
    shutil.rmtree(cache)
    wheel.unlink()
    home = tmp_path / "empty-home"
    home.mkdir()
    env = {"HOME": str(home), "PATH": os.defpath, "LANG": "C.UTF-8"}
    console = subprocess.run([str(release.source_root / ".venv/bin/artifact-probe")],
                             cwd=home, env=env, capture_output=True, text=True, check=True)
    assert console.stdout.strip() == "relocated console works"
    result = subprocess.run([str(release.source_root / ".venv/bin/python"), "-I", "-c",
        "import json, pathlib, relocation_probe, ssl, sqlite3, sys; "
        "print(json.dumps([sys.base_prefix, relocation_probe.__file__]))"],
        cwd=home, env=env, capture_output=True, text=True, check=True)
    prefix, module = json.loads(result.stdout)
    assert prefix == str(release.source_root / ".python")
    assert module.startswith(str(release.source_root / ".venv/"))
    assert not os.path.isabs(os.readlink(release.source_root / ".venv/bin/python"))
    assert releases._read_receipt(release)["source"]["coverage"] == "full"


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
    assert all(call.kwargs.get("project") is not None for call in restarts.call_args_list)
    assert restarts.call_args.kwargs["project"].root == old.source_root


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
    run = artifact.safe_subprocess.run

    def mapped_acl(argv, **kwargs):
        # Isolated acceptance maps only the current UID. Keep production's
        # distinct-owner check, then exercise real ACLs with that mapped UID.
        assert argv[1:3] == ["--modify", f"u:{owner_uid}:r-x,d:u:{owner_uid}:r-x"]
        argv = [*argv[:2], f"u:{agent_uid}:r-x,d:u:{agent_uid}:r-x", *argv[3:]]
        return run(argv, **kwargs)

    monkeypatch.setattr(artifact.safe_subprocess, "run", mapped_acl)
    return agent_uid


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
