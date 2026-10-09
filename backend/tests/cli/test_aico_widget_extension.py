"""ST exposes the owner widget contract without importing or duplicating it."""

import json
from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

from cli.extensions import _environment, load_extensions, register_extensions

REGISTRY = Path(__file__).resolve().parents[3] / "scripts/lib/tool-registry.json"


def aico_record():
    return next(record for record in load_extensions(set(), registry_path=REGISTRY).records
                if record.binding is not None and record.binding.namespace == "aico")


def app():
    result = typer.Typer()

    @result.callback()
    def root():
        pass

    register_extensions(result, registry_path=REGISTRY)
    return result


def test_widget_manifest_exposes_exact_current_pane_owner_controls():
    manifest = aico_record().manifest
    assert manifest is not None
    assert "st aico widget" in manifest.help[""]
    assert "before using desktop automation" in manifest.help["widget"]
    for operation in ("status", "title", "position"):
        text = manifest.help[f"widget {operation}"]
        assert "AICO_WIDGET_ID" in text
        assert "--widget-id ID" in text
        assert manifest.help_options[f"widget {operation}"] == {"--widget-id": 1, "--root-socket": 1}
    assert {"st.aico.widget.status", "st.aico.widget.title", "st.aico.widget.position"} <= {
        row["surface"] for row in manifest.usage
    }
    assert "1-160" in manifest.help["widget title"]
    assert "100000" in manifest.help["widget position"]
    assert "Output contains" in manifest.help["widget"]
    assert "No prompt retention or fleet ledger" in manifest.help["create"]


@pytest.mark.parametrize("arguments, expected", [
    (["widget", "status", "--help"], "Read one exact ordinary widget"),
    (["widget", "title", "--help"], "Rename the exact ordinary widget"),
    (["widget", "position", "--help"], "Arrange the exact ordinary widget"),
    (["widget", "--widget-id", "title", "status", "--help"], "Read one exact ordinary widget"),
])
def test_widget_help_is_passive_and_resolves_nested_routes(monkeypatch, arguments, expected):
    def unexpected(*args, **kwargs):
        pytest.fail("Passive help must not dispatch or resolve runtime context")

    monkeypatch.setattr("cli.extensions.dispatch_extension", unexpected)
    monkeypatch.setattr("cli.extensions.extension_context", unexpected)
    result = CliRunner().invoke(app(), ["aico", *arguments])
    assert result.exit_code == 0
    assert expected in result.output


@pytest.mark.parametrize("arguments", [
    ["widget", "status"],
    ["widget", "title", "A non-secret label"],
    ["widget", "position", "-20", "0", "960", "720", "--widget-id", "0123abcd"],
    ["widget", "title", "A non-secret label", "--widget-id", "0123abcd", "--root-socket", "/fixture/gui.sock"],
])
def test_widget_dispatch_preserves_exact_argv_without_label_echo(monkeypatch, arguments):
    observed = []
    monkeypatch.setattr("cli.extensions.extension_context", lambda _: {})
    monkeypatch.setattr("cli.extensions.dispatch_extension", lambda record, argv, **kwargs: observed.append(argv) or 0)
    result = CliRunner().invoke(app(), ["aico", *arguments])
    assert result.exit_code == 0
    assert observed == [arguments]
    assert result.output == ""


def test_widget_binding_forwards_current_pane_identity_without_unrelated_secrets(monkeypatch):
    record = aico_record()
    assert record.binding is not None
    monkeypatch.setattr("cli.lib.task_claims.current_caller_identity", lambda: {})
    monkeypatch.setenv("AICO_WIDGET_ID", "0123abcd")
    monkeypatch.setenv("UNRELATED_SECRET", "fixture-must-not-cross")
    forwarded = _environment(record.binding, {})
    assert forwarded["AICO_WIDGET_ID"] == "0123abcd"
    assert "UNRELATED_SECRET" not in forwarded
    monkeypatch.delenv("AICO_WIDGET_ID")
    assert "AICO_WIDGET_ID" not in _environment(record.binding, {})
    assert json.loads(REGISTRY.read_text())["extensions"][0]["namespace"] == "aico"
