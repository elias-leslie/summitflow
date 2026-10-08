"""ST exposes exact retained-root owner controls without duplicating them."""

from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

from cli.extensions import load_extensions, register_extensions

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


def test_root_manifest_exposes_owner_controls_and_alias():
    manifest = aico_record().manifest
    assert manifest is not None
    assert "st aico root status|show|title|position|end" in manifest.help[""]
    for operation in ("status", "show", "title", "position", "end"):
        assert f"st aico root {operation} REQUEST_ID" in manifest.help[f"root {operation}"]
        assert f"st.aico.root.{operation}" in {row["surface"] for row in manifest.usage}
    assert manifest.help_options["root end"]["--owner-socket"] == 1
    assert "compatibility alias" in manifest.help["root title"]
    assert "A-Term positioning is unavailable" in manifest.help["root position"]
    assert "applied:null" in manifest.help["root end"]


@pytest.mark.parametrize("arguments, expected", [
    (["root", "--help"], "Control one exact retained owner root"),
    (["root", "end", "root-1", "--surface", "a-term", "--help"], "End the exact root"),
    (["root", "title", "root-1", "Name", "--help"], "Rename the exact running root"),
])
def test_root_help_is_passive(monkeypatch, arguments, expected):
    monkeypatch.setattr("cli.extensions.dispatch_extension", lambda *a, **k: pytest.fail("dispatched"))
    result = CliRunner().invoke(app(), ["aico", *arguments])
    assert result.exit_code == 0
    assert expected in result.output


def test_root_dispatch_preserves_exact_argv(monkeypatch):
    observed = []
    monkeypatch.setattr("cli.extensions.extension_context", lambda _: {})
    monkeypatch.setattr("cli.extensions.dispatch_extension", lambda record, argv, **kwargs: observed.append(argv) or 0)
    arguments = ["root", "position", "root-1", "-20", "0", "960", "720", "--root-socket", "/fixture/gui.sock"]
    result = CliRunner().invoke(app(), ["aico", *arguments])
    assert result.exit_code == 0 and observed == [arguments]
