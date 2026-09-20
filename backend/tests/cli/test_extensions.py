"""Trusted executable registration is passive; dispatch is explicitly authorized."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

from cli.extensions import dispatch_extension, load_extensions, register_extensions
from cli.lib.usage import collect_usage_specs, filter_specs, select_specs_for_density


def registration(tmp_path, *, namespace="fixture", manifest_changes=None, binding_changes=None):
    metadata = {
        "id": "fixture.extension", "owner": "fixture-owner", "version": "1.0.0",
        "namespace": namespace, "st_contract_versions": [1], "summary": "Isolated fixture",
        "effects": ["read-local"],
        "help": {"": "Usage: st fixture [OPTIONS]\nFixture help", "inspect": "Inspect --json"},
        "usage": [{"surface": f"st.{namespace}", "cmd": f"st {namespace}",
                   "when": "inspect fixture", "task_types": ["fixture-work"],
                   "on_demand": "fixture inspection"}],
    }
    metadata.update(manifest_changes or {})
    manifests = tmp_path / "extensions"
    manifests.mkdir(exist_ok=True)
    (manifests / f"{namespace}.json").write_text(json.dumps(metadata))
    binding = {
        "id": "fixture.extension", "owner": "fixture-owner", "namespace": namespace,
        "manifest": f"extensions/{namespace}.json", "executable": "fixture",
        "grant": {"enabled": True, "effects": ["read-local"]}, "environment": ["FIXTURE_SETTING"],
    }
    binding.update(binding_changes or {})
    registry = tmp_path / "tool-registry.json"
    registry.write_text(json.dumps({"extensions": [binding]}))
    return registry


def context(tmp_path):
    return {"contract_version": 1, "project_id": "selected-not-cwd", "project_root": str(tmp_path),
            "cwd": str(tmp_path), "api_base": "http://localhost:8001/api",
            "agent_hub_url": "http://localhost:8003", "output": {
                "human": True, "compact": False, "progress_only": False}}


def test_help_and_metadata_never_resolve_or_execute(tmp_path, monkeypatch):
    registry = registration(tmp_path)
    def forbidden(*args, **kwargs):
        pytest.fail("passive discovery attempted execution or project resolution")
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr("cli.config.get_project_root_path", forbidden)
    app = typer.Typer()
    @app.callback()
    def root():
        pass
    register_extensions(app, registry_path=registry)
    runner = CliRunner()
    assert "fixture" in runner.invoke(app, ["--help"]).output
    assert "Fixture help" in runner.invoke(app, ["fixture", "--help"]).output
    assert "Inspect --json" in runner.invoke(app, ["fixture", "inspect", "--help"]).output
    assert "Inspect --json" in runner.invoke(app, ["fixture", "inspect", "a positional value", "--help"]).output
    assert "Inspect --json" in runner.invoke(app, ["fixture", "--json", "inspect", "--help"]).output
    assert "Fixture help" in runner.invoke(app, ["fixture", "a positional value", "--help"]).output
    specs = collect_usage_specs(app)
    assert filter_specs(specs, surface="st.fixture")[0].cmd == "st fixture"
    assert any(s.surface == "st.fixture" for s in select_specs_for_density(
        specs, density="task", task_type="fixture-work"))


@pytest.mark.parametrize(("changes", "code"), [
    ({"st_contract_versions": [99]}, "incompatible"),
    ({"usage": [{"surface": "st.claim"}]}, "malformed"),
    ({"owner": "imposter"}, "malformed"),
    ({"unexpected": True}, "malformed"),
])
def test_bad_metadata_is_localized(tmp_path, changes, code):
    registry = registration(tmp_path, manifest_changes=changes)
    app = typer.Typer()
    @app.command()
    def core():
        print("core works")
    catalog = register_extensions(app, registry_path=registry)
    assert catalog.records[0].status == code
    runner = CliRunner()
    assert runner.invoke(app, ["core"]).output == "core works\n"
    assert runner.invoke(app, ["fixture"]).exit_code == 2
    assert runner.invoke(app, ["--help"]).exit_code == 0


def test_malformed_registry_does_not_disable_core(tmp_path):
    registry = tmp_path / "tool-registry.json"
    registry.write_text("{")
    catalog = load_extensions(set(), registry_path=registry)
    assert not catalog.records
    assert catalog.diagnostics


def test_malformed_binding_does_not_hide_valid_registration(tmp_path):
    registry = registration(tmp_path)
    payload = json.loads(registry.read_text())
    payload["extensions"].append({"namespace": "broken", "executable": "../../untrusted"})
    registry.write_text(json.dumps(payload))
    catalog = load_extensions(set(), registry_path=registry)
    assert len(catalog.records) == 1
    assert catalog.records[0].status == "unverified"
    assert catalog.diagnostics == ["Extension binding 2 is malformed."]


def test_stdio_is_forwarded_without_st_content_telemetry(tmp_path):
    registry = registration(tmp_path)
    script = tmp_path / "fixture"
    script.write_text(f"#!{sys.executable}\nimport sys\nprint(sys.stdin.read(),end='')\nprint('diagnostic',file=sys.stderr)\n")
    script.chmod(0o755)
    code = ("from pathlib import Path; from cli.extensions import load_extensions,dispatch_extension; "
            f"r=load_extensions(set(),registry_path=Path({str(registry)!r})).records[0]; "
            f"raise SystemExit(dispatch_extension(r,[],context={context(tmp_path)!r},root_resolver=lambda _: {str(tmp_path)!r}))")
    result = subprocess.run([sys.executable, "-c", code], cwd=Path(__file__).resolve().parents[2],
                            input="fixture input\n", capture_output=True, text=True, check=False)
    assert result.returncode == 0
    assert result.stdout == "fixture input\n"
    assert result.stderr == "diagnostic\n"


def test_root_project_output_context_reaches_registered_owner(tmp_path, monkeypatch):
    from cli.config import Config
    from cli.main import app

    monkeypatch.setattr("cli.config.get_config_optional", lambda: Config("http://localhost:8001/api", "selected", str(tmp_path)))
    observed = []
    monkeypatch.setattr("cli.extensions.dispatch_extension", lambda record, argv, **kwargs: observed.append(kwargs["context"]) or 0)
    result = CliRunner().invoke(app, ["-P", "selected", "--human", "--no-compact", "jobs", "ready"])
    assert result.exit_code == 0, result.output
    assert observed[0]["project_id"] == "selected"
    assert observed[0]["project_root"] == str(tmp_path)
    assert observed[0]["cwd"] != observed[0]["project_root"]
    assert observed[0]["output"] == {"human": True, "compact": False, "progress_only": False}
    from cli.config import set_project_override
    set_project_override(None)


def test_all_duplicate_and_core_collisions_are_rejected(tmp_path):
    registry = registration(tmp_path)
    payload = json.loads(registry.read_text())
    payload["extensions"] *= 2
    registry.write_text(json.dumps(payload))
    assert all(row.status == "collision" for row in load_extensions(set(), registry_path=registry).records)
    assert all(row.status == "collision" for row in load_extensions({"fixture"}, registry_path=registry).records)


def test_effect_metadata_is_not_dispatch_authority(tmp_path):
    registry = registration(tmp_path, binding_changes={"grant": {"enabled": False, "effects": []}})
    record = load_extensions(set(), registry_path=registry).records[0]
    assert record.status == "denied"
    assert dispatch_extension(record, [], context=context(tmp_path)) == 2


def test_wrapper_preserves_separator_and_help_as_positional(tmp_path, monkeypatch):
    registry = registration(tmp_path)
    app = typer.Typer()
    @app.callback()
    def root():
        pass
    register_extensions(app, registry_path=registry)
    observed = []
    monkeypatch.setattr("cli.extensions.extension_context", lambda _: context(tmp_path))
    monkeypatch.setattr("cli.extensions.dispatch_extension", lambda record, argv, **kwargs: observed.append(argv) or 7)
    args = ["--json", "value with spaces", "*", "--", "-x", "--help"]
    result = CliRunner().invoke(app, ["fixture", *args])
    assert result.exit_code == 7, result.output
    assert observed == [args]


def test_denied_browser_binding_cannot_enter_core_policy(tmp_path, monkeypatch):
    registry = registration(tmp_path, binding_changes={
        "policy_adapter": "browser", "grant": {"enabled": False, "effects": []},
    })
    app = typer.Typer()
    @app.callback()
    def root():
        pass
    register_extensions(app, registry_path=registry)
    def forbidden(*args, **kwargs):
        pytest.fail("denied dispatch entered browser policy")
    monkeypatch.setattr("cli.commands.browser.run_registered", forbidden)
    monkeypatch.setattr("cli.extensions.extension_context", forbidden)
    assert CliRunner().invoke(app, ["fixture", "open", "example"]).exit_code == 2


def test_missing_and_non_executable_dependencies(tmp_path):
    registry = registration(tmp_path)
    record = load_extensions(set(), registry_path=registry).records[0]
    assert dispatch_extension(record, [], context=context(tmp_path), root_resolver=lambda _: str(tmp_path)) == 127
    (tmp_path / "fixture").write_text("not executable")
    assert dispatch_extension(record, [], context=context(tmp_path), root_resolver=lambda _: str(tmp_path)) == 126


def test_exact_arguments_context_environment_and_nonzero_exit(tmp_path, capfd, monkeypatch):
    registry = registration(tmp_path)
    script = tmp_path / "fixture"
    script.write_text(f"#!{sys.executable}\n" + "import json,os,sys\nprint(json.dumps({'args':sys.argv[1:], 'cwd':os.getcwd(), 'context':json.loads(os.environ['ST_EXTENSION_CONTEXT']), 'allowed':os.getenv('FIXTURE_SETTING'), 'secret':os.getenv('UNRELATED_SECRET'), 'pythonpath':os.getenv('PYTHONPATH')}))\nprint('child stderr',file=sys.stderr)\nsys.exit(7)\n")
    script.chmod(0o755)
    monkeypatch.setenv("FIXTURE_SETTING", "enabled")
    monkeypatch.setenv("UNRELATED_SECRET", "must-not-cross")
    monkeypatch.setenv("PYTHONPATH", "must-not-cross")
    monkeypatch.chdir(tmp_path)
    record = load_extensions(set(), registry_path=registry).records[0]
    assert dispatch_extension(record, ["--json", "value with spaces", "*", "--", "-x"], context=context(tmp_path), root_resolver=lambda _: str(tmp_path)) == 7
    out, err = capfd.readouterr()
    payload = json.loads(out)
    assert payload["args"] == ["--json", "value with spaces", "*", "--", "-x"]
    assert payload["context"] == context(tmp_path)
    assert payload["cwd"] == str(tmp_path)
    assert payload["allowed"] == "enabled"
    assert payload["secret"] is payload["pythonpath"] is None
    assert err == "child stderr\n"


@pytest.mark.parametrize("signum", [signal.SIGINT, signal.SIGTERM])
def test_real_cancellation_forwards_signal_and_reaps(tmp_path, signum):
    registry = registration(tmp_path)
    marker = tmp_path / "started"
    stopped = tmp_path / "stopped"
    script = tmp_path / "fixture"
    script.write_text(f"#!{sys.executable}\n" + f"import os,signal,time\nfrom pathlib import Path\ndef stop(sig,frame):\n Path({str(stopped)!r}).write_text(str(sig))\n raise SystemExit(128+sig)\nsignal.signal(signal.SIGINT,stop)\nsignal.signal(signal.SIGTERM,stop)\nPath({str(marker)!r}).write_text(str(os.getpid()))\nwhile True: time.sleep(1)\n")
    script.chmod(0o755)
    code = ("from pathlib import Path; from cli.extensions import load_extensions,dispatch_extension; "
            f"r=load_extensions(set(),registry_path=Path({str(registry)!r})).records[0]; "
            f"raise SystemExit(dispatch_extension(r,[],context={context(tmp_path)!r},root_resolver=lambda _: {str(tmp_path)!r}))")
    process = subprocess.Popen([sys.executable, "-c", code], cwd=Path(__file__).resolve().parents[2])
    try:
        deadline = time.monotonic() + 10
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert marker.exists()
        process.send_signal(signum)
        assert process.wait(timeout=10) == 128 + signum
        assert stopped.read_text() == str(signum)
        with pytest.raises(ProcessLookupError):
            os.kill(int(marker.read_text()), 0)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
