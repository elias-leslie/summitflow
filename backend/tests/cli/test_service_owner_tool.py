"""Agent-built ST capsules carry their interpreter and frozen dependency bytes."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from cli.lib import service_owner_tool as tool

SHA = "a" * 40
SOURCE = {"source_commit": SHA, "source_tree": "b" * 40,
          "acceptance_id": "c" * 64, "coverage": "full"}


@pytest.fixture
def build(tmp_path, monkeypatch):
    source = tmp_path / "accepted"
    backend = source / "backend"
    backend.mkdir(parents=True)
    project = SimpleNamespace(git_root=tmp_path / "repo")
    workspace_root = tmp_path / "workspaces"
    project.root = workspace_root / "projects/summitflow"
    project.root.mkdir(parents=True)
    monkeypatch.setattr(tool, "get_workspaces_root", lambda: workspace_root)
    monkeypatch.setattr(tool.os, "getuid", lambda: 1000)
    monkeypatch.setattr(tool.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(tool, "_agent_uid", lambda: 1000)
    prefix = tmp_path / "python-prefix"
    (prefix / "bin").mkdir(parents=True)
    (prefix / "bin/python3.13").write_bytes(b"\x7fELFfixture")
    monkeypatch.setattr(tool, "_python_prefix", lambda: prefix)
    monkeypatch.setattr(tool.service_ops, "load_project", lambda name: project)
    validate = Mock(return_value=SOURCE)
    materialize = Mock(return_value=SimpleNamespace(source_root=source))
    monkeypatch.setattr(tool.acceptance, "validate_acceptance_receipt", validate)
    monkeypatch.setattr(tool.releases, "prepare_release", materialize)

    def sync(argv, **kwargs):
        assert argv == ["uv", "sync", "--frozen", "--no-editable", "--link-mode", "copy",
                        "--python", str(prefix / "bin/python3.13")]
        assert kwargs["env"]["UV_PROJECT_ENVIRONMENT"] == str(backend / ".venv")
        assert kwargs["env"]["UV_PYTHON_DOWNLOADS"] == "never"
        site = backend / ".venv/lib/python3.13/site-packages"
        site.mkdir(parents=True)
        (site / "dependency.py").write_text("VALUE = 'frozen'\n")
        return SimpleNamespace(returncode=0)

    work = SimpleNamespace(run=Mock(side_effect=sync))
    @contextmanager
    def admitted(*args, **kwargs):
        yield work
    monkeypatch.setattr(tool, "heavy_work", admitted)
    smoke = Mock()
    monkeypatch.setattr(tool, "_smoke", smoke)
    return SimpleNamespace(source=source, prefix=prefix, validate=validate, materialize=materialize,
                           work=work, smoke=smoke, output=tmp_path / "output", receipt=tmp_path / "receipt.json",
                           workspace_root=workspace_root)


def prepare(build):
    return tool.prepare(sha=SHA, destination=build.output, receipt=build.receipt)


def test_frozen_capsule_manifest_and_payload(build, tmp_path):
    manifest = prepare(build)
    build.validate.assert_called_once_with(build.source.parent / "repo", build.receipt, sha=SHA)
    assert build.materialize.call_args.args == ("summitflow", build.source.parent / "repo", SOURCE)
    assert set(manifest) == {"schema", "source_sha", "source_tree", "acceptance_id", "archive_sha256",
                             "archive_size", "python_relpath", "launcher_relpath"}
    assert manifest["source_sha"] == SHA
    assert manifest["source_tree"] == SOURCE["source_tree"]
    assert manifest["acceptance_id"] == SOURCE["acceptance_id"]
    archive_path = build.output / "capsule.tar"
    assert manifest["archive_sha256"] == hashlib.sha256(archive_path.read_bytes()).hexdigest()
    assert manifest["archive_size"] == archive_path.stat().st_size
    assert json.loads((build.output / "manifest.json").read_text()) == manifest
    relocated = tmp_path / "installed"
    with tarfile.open(archive_path) as archive:
        archive.extractall(relocated, filter="data")
    assert (relocated / tool.PYTHON_RELPATH).read_bytes() == b"\x7fELFfixture"
    assert (relocated / "site-packages/dependency.py").is_file()
    assert json.loads((relocated / "runtime.json").read_text()) == {"workspace_root": str(build.workspace_root)}
    assert not (relocated / "source/backend/.venv").exists()
    assert tool.tool_argv(relocated) == [str(relocated / "python/bin/python3.13"), "-I", "-S",
                                        str(relocated / "launch.py")]
    # Scratch release, venv, copied interpreter, and smoke HOME are removed.
    assert not build.smoke.call_args.args[0].exists()


@pytest.mark.parametrize("identity", [0, 2000])
def test_owner_or_root_cannot_build(build, monkeypatch, identity):
    monkeypatch.setattr(tool.os, "getuid", lambda: identity)
    with pytest.raises(ValueError, match="configured agent"):
        prepare(build)
    build.validate.assert_not_called()
    assert not build.output.exists()


def test_wrong_or_task_acceptance_refused_before_build(build):
    build.validate.side_effect = tool.acceptance.AcceptanceError("wrong exact SHA")
    with pytest.raises(tool.acceptance.AcceptanceError, match="wrong exact SHA"):
        prepare(build)
    build.materialize.assert_not_called()
    build.work.run.assert_not_called()
    build.validate.side_effect = None
    build.validate.return_value = {**SOURCE, "coverage": "task"}
    with pytest.raises(tool.releases.ReleaseError, match="full acceptance"):
        prepare(build)
    build.materialize.assert_not_called()


def test_dependency_failure_and_existing_output_preserved(build):
    build.work.run.side_effect = None
    build.work.run.return_value = SimpleNamespace(returncode=1, stderr="frozen lock unavailable")
    with pytest.raises(ValueError, match="Frozen owner tool dependency preparation failed"):
        prepare(build)
    assert not build.output.exists()
    build.output.mkdir()
    marker = build.output / "preserve"
    marker.write_text("existing output")
    with pytest.raises(ValueError, match="already exists"):
        prepare(build)
    assert marker.read_text() == "existing output"


def test_failed_relocation_probe_leaves_no_output(build):
    build.smoke.side_effect = ValueError("Relocated owner tool smoke failed")
    with pytest.raises(ValueError, match="smoke failed"):
        prepare(build)
    assert not build.output.exists()
    assert not list(build.output.parent.glob(".owner-tool-*"))


def test_abbreviated_sha_cannot_select_tool_source(build):
    with pytest.raises(ValueError, match="full lowercase commit SHA"):
        tool.prepare(sha=SHA[:12], destination=build.output, receipt=build.receipt)
    build.validate.assert_not_called()


@pytest.mark.parametrize("root_kind", ["relative", "missing", "outside"])
def test_invalid_workspace_root_refused_before_build(build, monkeypatch, root_kind):
    root = {"relative": Path("relative"), "missing": build.output / "absent",
            "outside": build.source}[root_kind]
    monkeypatch.setattr(tool, "get_workspaces_root", lambda: root)
    with pytest.raises(ValueError, match="workspace root"):
        prepare(build)
    build.validate.assert_not_called()
    build.work.run.assert_not_called()


@pytest.mark.parametrize("kind", ["editable", "symlink", "absolute_internal_symlink"])
def test_nonportable_payload_is_refused(build, kind):
    original = build.work.run.side_effect
    def sync(argv, **kwargs):
        result = original(argv, **kwargs)
        site = build.source / "backend/.venv/lib/python3.13/site-packages"
        if kind == "editable":
            metadata = site / "dependency.dist-info"
            metadata.mkdir()
            (metadata / "direct_url.json").write_text('{"dir_info":{"editable":true}}')
        elif kind == "symlink":
            (site / "shared_cache.py").symlink_to("../../../../../outside")
        else:
            (build.prefix / "bin/python").symlink_to(build.prefix / "bin/python3.13")
        return result
    build.work.run.side_effect = sync
    with pytest.raises((ValueError, FileNotFoundError), match=r"editable|symlink|No such file"):
        prepare(build)
    assert not build.output.exists()


def test_regular_python_prefix_required(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "base_prefix", str(tmp_path))
    (tmp_path / "bin").mkdir()
    python = tmp_path / "bin/python3.13"
    python.write_text("#!/bin/sh\n")
    with pytest.raises(ValueError, match="regular ELF"):
        tool._python_prefix()
    python.unlink()
    python.symlink_to(sys.executable)
    with pytest.raises(ValueError, match="regular ELF"):
        tool._python_prefix()


def test_real_python_relocation_ignores_ambient_imports_and_preserves_home(tmp_path):
    """Use the real full Python distribution, then remove both input copies."""
    prefix = tool._python_prefix()
    source = tmp_path / "source-input"
    site = source / "backend/.venv/lib/python3.13/site-packages"
    site.mkdir(parents=True)
    (site / "capsule_dependency.py").write_text("VALUE = 'copied dependency'\n")
    cli = source / "backend/cli"
    cli.mkdir()
    (cli / "__init__.py").touch()
    (cli / "main.py").write_text(
        "import json,os,sys\nfrom pathlib import Path\nimport capsule_dependency\n"
        "def app():\n"
        "    assert all(Path(p).is_relative_to(Path(__file__).parents[3]) for p in sys.path)\n"
        "    print(json.dumps({'home':os.environ['HOME'],'dependency':capsule_dependency.VALUE,'isolated':sys.flags.isolated,'no_site':sys.flags.no_site}))\n"
    )
    initial = tmp_path / "initial"
    initial.mkdir()
    tool._copy_payload(source, prefix, initial)
    (initial / "runtime.json").write_text(json.dumps({"workspace_root": str(tmp_path)}))
    relocated = tmp_path / "relocated"
    initial.rename(relocated)
    shutil.rmtree(source)
    home = tmp_path / "caller-home"
    home.mkdir()
    env = dict(os.environ, HOME=str(home), PYTHONHOME="/missing-python", PYTHONPATH="/missing-deps")
    result = subprocess.run(tool.tool_argv(relocated), cwd=home, env=env, capture_output=True, text=True, check=True)
    assert json.loads(result.stdout) == {"home": str(home), "dependency": "copied dependency", "isolated": 1, "no_site": 1}
    assert not (relocated / tool.PYTHON_RELPATH).is_symlink()
    if (bwrap := shutil.which("bwrap")) and os.path.isdir("/srv/workspaces/cache"):
        # Same installed isolation capability used by native acceptance: all
        # host files read-only, shared uv/Python caches hidden, no network.
        command = [bwrap, "--die-with-parent", "--unshare-net", "--ro-bind", "/", "/",
                   "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/srv/workspaces/cache",
                   "--clearenv", "--setenv", "HOME", str(home), "--setenv", "PATH", os.defpath,
                   "--", *tool.tool_argv(relocated)]
        isolated = subprocess.run(command, cwd=home, capture_output=True, text=True, check=True)
        assert json.loads(isolated.stdout) == json.loads(result.stdout)


@pytest.mark.parametrize("caller_root", [None, "/incorrect-caller-workspaces"])
def test_pinned_workspace_data_drives_clean_environment_project_discovery(tmp_path, caller_root):
    """Import real CLI discovery after the adapter, with no caller configuration."""
    workspace = tmp_path / "configured-workspaces"
    project_root = workspace / "projects/capsule-discovery"
    project_root.mkdir(parents=True)
    (project_root / "project.identity.json").write_text(json.dumps({
        "project": {"id": "capsule-discovery"}, "runtime": {"runtime_user": "owner"}}))
    capsule = tmp_path / "capsule"
    (capsule / "source").mkdir(parents=True)
    backend = Path(__file__).resolve().parents[2]
    (capsule / "source/backend").symlink_to(backend, target_is_directory=True)
    (capsule / "site-packages").symlink_to(backend / ".venv/lib/python3.13/site-packages", target_is_directory=True)
    (capsule / "python").symlink_to(sys.base_prefix, target_is_directory=True)
    (capsule / "launch.py").write_text(tool.LAUNCHER)
    (capsule / "runtime.json").write_text(json.dumps({"workspace_root": str(workspace)}))
    home = tmp_path / "private-caller-home"
    home.mkdir()
    env = {"HOME": str(home), "PATH": os.defpath,
           "DATABASE_URL": "postgresql://127.0.0.1:1/summitflow_test"}
    if caller_root is not None:
        env["ST_WORKSPACES_ROOT"] = caller_root
    probe = (
        "import json,os,runpy,sys\n"
        "runpy.run_path(sys.argv[1], run_name='capsule_probe')\n"
        "from cli.lib.service_ops import load_project\n"
        "from cli.lib.workspace_paths import get_workspaces_root,workspaces_root_available\n"
        "assert workspaces_root_available()\n"
        "print(json.dumps({'project_root':str(load_project('capsule-discovery').root),"
        "'workspace_root':str(get_workspaces_root()),'home':os.environ['HOME']}))\n"
    )
    result = subprocess.run([sys.executable, "-I", "-S", "-c", probe, str(capsule / "launch.py")],
                            cwd=home, env=env, capture_output=True, text=True, check=True)
    assert json.loads(result.stdout) == {"project_root": str(project_root), "workspace_root": str(workspace),
                                         "home": str(home)}
