"""st search extension metadata routing."""

from __future__ import annotations


def test_registered_search_metadata_delivers_optional_routing() -> None:
    import json
    from pathlib import Path

    metadata = json.loads((Path(__file__).resolve().parents[3] / "scripts/lib/extensions/search.json").read_text())
    assert metadata["id"] == "code-intelligence.search"
    assert metadata["namespace"] == "search"
    spec = next(item for item in metadata["usage"] if item["surface"] == "st.search")
    assert spec["tier"] == "reference"
    assert "optional ranked discovery" in spec["when"]
    assert "regex" in " ".join(spec["precautions"])
    assert "exhaustive references" in " ".join(spec["precautions"])
    assert "case-insensitive literal phrase" in metadata["help"][""]
    assert "hypothetical" in metadata["help"][""]
