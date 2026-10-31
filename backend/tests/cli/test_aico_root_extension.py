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
    assert "st aico root status|title|end|send" in manifest.help[""]
    for operation in ("status", "title", "end", "send"):
        assert f"st aico root {operation} REQUEST_ID" in manifest.help[f"root {operation}"]
        assert f"st.aico.root.{operation}" in {row["surface"] for row in manifest.usage}
    for operation in ("show", "position"):
        assert "Retired" in manifest.help[f"root {operation}"]
        assert f"st.aico.root.{operation}" not in {row["surface"] for row in manifest.usage}
    assert manifest.help_options["root end"]["--owner-socket"] == 1
    assert "compatibility alias" in manifest.help["root title"]
    assert "A-Term" not in manifest.help["root position"]
    assert all("--root-url" not in text and "--surface" not in text for text in manifest.help.values())
    assert "applied:null" in manifest.help["root end"]
    assert manifest.help_options["root send"] == {"--generation": 1, "--stdin": 0, "--root-socket": 1,
                                                  "--owner-socket": 1}
    assert "--generation is required" in manifest.help["root send"]
    assert "Pi has no atomic follow-up" not in manifest.help["create"]


@pytest.mark.parametrize("arguments, expected", [
    (["root", "--help"], "Control one exact retained owner root"),
    (["root", "end", "root-1", "--help"], "End the exact root"),
    (["root", "title", "root-1", "Name", "--help"], "Rename the exact running root"),
    (["root", "send", "root-1", "Follow up", "--generation", "a" * 64, "--help"], "Queue one follow-up"),
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


def test_create_help_exposes_fixed_work_roles_and_current_pi_launch_contract(monkeypatch):
    monkeypatch.setattr("cli.extensions.dispatch_extension", lambda *a, **k: pytest.fail("dispatched"))
    result = CliRunner().invoke(app(), ["aico", "create", "--help"])
    assert result.exit_code == 0
    assert "--work-role ID" in result.output
    assert "--work-role-name" in result.output
    assert "--agent-hub-context" in result.output
    assert "--approve" in result.output
    assert "Codex-only" not in result.output
    manifest = aico_record().manifest
    assert manifest is not None
    assert manifest.help_options["create"]["--work-role"] == 1
    assert manifest.help_options["create"]["--work-role-name"] == 1


def test_create_help_names_only_the_supported_root_tools(monkeypatch):
    monkeypatch.setattr("cli.extensions.dispatch_extension", lambda *a, **k: pytest.fail("dispatched"))
    result = CliRunner().invoke(app(), ["aico", "create", "--help"])
    assert result.exit_code == 0
    for slug in ("claude-code", "codex", "pi", "agent-hub"):
        assert slug in result.output
    assert "--blank-slate" in result.output
    assert "--instructions PROMPT[@REVISION]" in result.output
    assert "opencode" not in result.output.lower()
    manifest = aico_record().manifest
    assert manifest is not None
    usage = next(row for row in manifest.usage if row["surface"] == "st.aico.create")
    assert "--tool claude-code|codex|pi|agent-hub " in manifest.help[""]
    assert "--tool claude-code|codex|pi|agent-hub " in usage["cmd"]
    assert "--blank-slate" in usage["cmd"]
    assert manifest.help_options["create"]["--blank-slate"] == 0
    assert "--instructions PROMPT[@REVISION]" in usage["cmd"]
    assert manifest.help_options["create"]["--instructions"] == 1
    assert manifest.help_options["create"]["--agent"] == 1
    assert "--tool agent-hub --agent SLUG" in manifest.help[""]
    assert "opencode" not in " ".join(map(str, usage["precautions"])).lower()


def test_wake_is_an_on_demand_surface_with_short_help(monkeypatch):
    manifest = aico_record().manifest
    assert manifest is not None
    usage = next(row for row in manifest.usage if row["surface"] == "st.aico.wake")
    assert usage["on_demand"] and usage["tier"] == "reference"
    assert manifest.help_options["wake"]["--widget-id"] == 1
    monkeypatch.setattr("cli.extensions.dispatch_extension", lambda *a, **k: pytest.fail("dispatched"))
    result = CliRunner().invoke(app(), ["aico", "wake", "--help"])
    assert result.exit_code == 0
    assert 'Example: st aico wake +1h "check the lane reports"' in result.output
    assert len(result.output) < 1000
