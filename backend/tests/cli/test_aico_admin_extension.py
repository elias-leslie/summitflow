"""Aico owns administration; ST retains only its existing extension facade."""

import json
from pathlib import Path

from cli.extensions import load_extensions


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
    assert binding["environment"] == ["XDG_RUNTIME_DIR", "AICO_GUI_CONTROL_SOCKET", "AICO_CONTROL_SOCKET"]
