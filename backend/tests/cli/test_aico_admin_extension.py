"""Aico owns administration; ST retains only its existing extension facade."""

import json
from pathlib import Path

import typer
from typer.testing import CliRunner

from cli.extensions import load_extensions, register_extensions


def test_aico_admin_manifest_advertises_pins_and_fail_closed_owner_boundary():
    registry = Path(__file__).resolve().parents[3] / "scripts/lib/tool-registry.json"
    record = next(row for row in load_extensions(set(), registry_path=registry).records
                  if row.manifest is not None and row.manifest.namespace == "aico")
    assert record.manifest is not None
    assert "st aico admin" in record.manifest.help[""]
    help_text = record.manifest.help["admin"]
    for phrase in ("--generation", "--thread", "--request-key", "--stdin", "fails closed"):
        assert phrase in help_text
    options = record.manifest.help_options["admin"]
    assert options["--generation"] == options["--thread"] == options["--request-key"] == 1
    assert options["--stdin"] == 0
    assert "st.aico.admin" in {row["surface"] for row in record.manifest.usage}
    binding = next(row for row in json.loads(registry.read_text())["extensions"] if row["namespace"] == "aico")
    assert binding["executable"] == "scripts/aico-root-watch.py"
    assert binding["environment"] == ["XDG_RUNTIME_DIR", "AICO_GUI_CONTROL_SOCKET", "AICO_CONTROL_SOCKET", "A_TERM_ROOT_CONTROL_URL"]


def test_aico_create_manifest_exposes_exact_resume_without_fleet_retention():
    registry = Path(__file__).resolve().parents[3] / "scripts/lib/tool-registry.json"
    record = next(row for row in load_extensions(set(), registry_path=registry).records
                  if row.manifest is not None and row.manifest.namespace == "aico")
    assert record.manifest is not None
    assert "st aico create" in record.manifest.help[""]
    text = record.manifest.help["create"]
    for phrase in ("--resume-session", "--surface a-term", "--project-root", "--stdin",
                   "same REQUEST_ID", "No prompt retention", "already running owner"):
        assert phrase in text
    options = record.manifest.help_options["create"]
    assert all(options[name] == 1 for name in ("--resume-session", "--surface", "--project", "--project-root"))
    assert options["--stdin"] == 0
    assert "st.aico.create" in {row["surface"] for row in record.manifest.usage}


def test_aico_create_cli_preserves_exact_owner_argv_and_help(monkeypatch):
    registry = Path(__file__).resolve().parents[3] / "scripts/lib/tool-registry.json"
    app = typer.Typer()

    @app.callback()
    def root():
        pass

    register_extensions(app, registry_path=registry)
    observed = []
    monkeypatch.setattr("cli.extensions.extension_context", lambda _: {})
    monkeypatch.setattr("cli.extensions.dispatch_extension", lambda record, argv, **kwargs: observed.append(argv) or 0)
    args = ["create", "recovery-1", "Reconcile after crash.", "--project", "neri",
            "--project-root", "/fixture/project", "--resume-session", "00000000-0000-4000-8000-000000000001",
            "--surface", "a-term"]
    result = CliRunner().invoke(app, ["aico", *args])
    assert result.exit_code == 0
    assert observed == [args]
    help_result = CliRunner().invoke(app, ["aico", "create", "--help"])
    assert help_result.exit_code == 0 and "--resume-session SESSION_ID" in help_result.output
    assert observed == [args]
