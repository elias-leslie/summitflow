"""Bugout stays an owner executable; ST supplies trusted passive discovery."""

from __future__ import annotations

import json
import socket
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cli.extensions import dispatch_extension, load_extensions
from cli.lib.usage import collect_usage_specs, render_inject, select_specs_for_density

ROOT = Path(__file__).resolve().parents[3]
CAPABILITY_LINE = (
    "- st bugout recon --help — bounded manifest-driven recon: "
    "validate, run, status, events, control"
)


def bugout_record():
    return next(row for row in load_extensions(set()).records
                if row.binding and row.binding.id == "bugout.recon")


def test_binding_keeps_owner_metadata_and_exact_checkout_entrypoint():
    record = bugout_record()
    binding = record.binding
    assert binding is not None and record.status == "unverified"
    assert (binding.owner, binding.namespace) == ("bugout", "bugout")
    assert binding.owner_manifest == "operators/recon/st-extension.json"
    assert binding.manifest == "extensions/bugout-recon.json"
    assert binding.executable == "operators/recon/bugout"
    assert binding.execution_source == "checkout"
    assert binding.arguments == binding.environment == []
    assert binding.owner_help
    assert binding.grant.enabled
    assert set(binding.grant.effects) == {"read-local", "write-local", "network", "process"}


@pytest.mark.parametrize("route", [(), ("recon",), ("recon", "validate"), ("recon", "run"),
                                   ("recon", "status"), ("recon", "events"), ("recon", "control")])
def test_actual_help_from_an_unrelated_project_is_passive(tmp_path, monkeypatch, route):
    from cli.main import app

    def forbidden(*args, **kwargs):
        pytest.fail("Bugout help attempted owner execution, network or project resolution")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr("cli.config.get_project_root_path", forbidden)
    monkeypatch.setattr("cli.extensions.extension_context", forbidden)
    result = CliRunner().invoke(app, ["-P", "unrelated-project", "bugout", *route, "--help"])
    assert result.exit_code == 0, result.output
    assert "Usage: st bugout recon" in result.output
    if len(route) > 1:
        assert f"Usage: st bugout {' '.join(route)}" in result.output


@pytest.mark.parametrize("density", ["core", "adaptive", "task"])
def test_unrelated_capabilities_omit_bugout_guidance(monkeypatch, density):
    from cli.main import app

    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: pytest.fail("discovery executed owner"))
    specs = select_specs_for_density(collect_usage_specs(app), density=density, task_type="backend", scores={})
    rendered = render_inject(specs)
    assert "st bugout " not in rendered
    assert "bounded manifest-driven recon" not in rendered


@pytest.mark.parametrize("density", ["adaptive", "task", "full"])
def test_neri_capabilities_include_one_compact_actionable_line(monkeypatch, density):
    from cli.main import app

    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: pytest.fail("discovery executed owner"))
    specs = select_specs_for_density(collect_usage_specs(app), density=density, task_type="neri", scores={})
    lines = [line for line in render_inject(specs).splitlines() if "st bugout " in line]
    assert lines == [CAPABILITY_LINE]
    assert len(lines[0]) <= 100


def test_dispatch_preserves_exact_argv_cwd_exit_and_environment(tmp_path, monkeypatch):
    record = bugout_record()
    assert record.binding is not None
    owner = tmp_path / "registered-owner"
    executable = owner / record.binding.executable
    executable.parent.mkdir(parents=True)
    executable.write_text("fixture; never executed")
    executable.chmod(0o755)
    caller = tmp_path / "unrelated-project"
    caller.mkdir()
    context = {"contract_version": 1, "project_id": "unrelated-project", "cwd": str(caller)}
    arguments = ["recon", "validate", "--manifest", "path with spaces.json", "--", "-literal"]
    calls = []
    resolved_owners = []

    def resolve(owner_id):
        resolved_owners.append(owner_id)
        return str(owner)

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return 7, "", ""

    monkeypatch.setattr("cli.extensions._run_process", run)
    monkeypatch.setattr("cli.lib.task_claims.current_caller_identity", lambda: {"member_id": "fixture"})
    for key in ("UNRELATED_SECRET", "PYTHONPATH", "PYTHONHOME", "BUGOUT_TOKEN"):
        monkeypatch.setenv(key, "must-not-cross")
    assert dispatch_extension(record, arguments, context=context, root_resolver=resolve) == 7
    assert resolved_owners == ["bugout"]
    assert len(calls) == 1
    argv, kwargs = calls[0]
    assert argv == [str(executable), *arguments]
    assert kwargs["cwd"] == str(caller) and kwargs["capture"] is False
    assert json.loads(kwargs["env"]["ST_EXTENSION_CONTEXT"]) == context
    assert json.loads(kwargs["env"]["ST_CALLER_IDENTITY"]) == {"member_id": "fixture"}
    assert not {"UNRELATED_SECRET", "PYTHONPATH", "PYTHONHOME", "BUGOUT_TOKEN"} & kwargs["env"].keys()


@pytest.mark.parametrize(("prerequisite", "code"), [("unregistered", 127), ("missing", 127), ("not-executable", 126)])
def test_missing_exact_executable_fails_closed_without_path_or_cwd_fallback(tmp_path, monkeypatch, prerequisite, code):
    record = bugout_record()
    assert record.binding is not None
    caller = tmp_path / "caller"
    imposter = caller / record.binding.executable
    imposter.parent.mkdir(parents=True)
    imposter.write_text("imposter")
    imposter.chmod(0o755)
    monkeypatch.chdir(caller)
    monkeypatch.setenv("PATH", str(imposter.parent))
    monkeypatch.setattr("cli.extensions._run_process", lambda *a, **k: pytest.fail("missing owner dispatched"))
    owner = tmp_path / "owner"
    if prerequisite == "not-executable":
        executable = owner / record.binding.executable
        executable.parent.mkdir(parents=True)
        executable.write_text("not executable")
    owner_root = None if prerequisite == "unregistered" else str(owner)
    assert dispatch_extension(record, ["recon", "status"], context={"cwd": str(caller)},
                              root_resolver=lambda _: owner_root) == code


def test_owner_release_replaces_passive_fallback_without_changing_grant(tmp_path, monkeypatch):
    binding = bugout_record().binding
    assert binding is not None
    state = tmp_path / "service-state"
    monkeypatch.setenv("SUMMITFLOW_SERVICE_STATE_ROOT", str(state))
    fallback = bugout_record()
    assert fallback.manifest is not None
    release = state / "projects/bugout/releases/accepted/source"
    manifest_path = release / binding.owner_manifest
    manifest_path.parent.mkdir(parents=True)
    (state / "projects/bugout/current").symlink_to(release.parent)
    metadata = json.loads((ROOT / "scripts/lib" / binding.manifest).read_text())
    metadata.update(version="0.2.0", help={"": "Owner release help"})
    manifest_path.write_text(json.dumps(metadata))
    accepted = bugout_record()
    assert accepted.manifest is not None
    assert accepted.manifest.version == "0.2.0"
    assert accepted.manifest.help == {"": "Owner release help"}
    metadata["effects"] = ["credentials"]
    manifest_path.write_text(json.dumps(metadata))
    assert bugout_record().status == "denied"
