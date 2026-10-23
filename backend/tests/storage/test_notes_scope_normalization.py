"""Tests for canonical SummitFlow note scope normalization."""

from app.storage.notes_helpers import normalize_project_scope


def test_normalize_project_scope_maps_merged_aico_aliases() -> None:
    assert [normalize_project_scope(s) for s in ("terminal", "a-term", "Tether")] == ["aico"] * 3


def test_normalize_project_scope_keeps_canonical_values() -> None:
    assert normalize_project_scope("aico") == "aico"
    assert normalize_project_scope("summitflow") == "summitflow"


def test_normalize_project_scope_defaults_blank_to_global() -> None:
    assert normalize_project_scope("") == "global"
    assert normalize_project_scope(None) == "global"
