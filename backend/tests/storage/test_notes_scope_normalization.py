"""Tests for canonical SummitFlow note scope normalization."""

from app.storage.notes_helpers import normalize_project_scope


def test_normalize_project_scope_maps_terminal_alias() -> None:
    assert normalize_project_scope("terminal") == "a-term"


def test_normalize_project_scope_keeps_canonical_values() -> None:
    assert normalize_project_scope("a-term") == "a-term"
    assert normalize_project_scope("summitflow") == "summitflow"


def test_normalize_project_scope_defaults_blank_to_global() -> None:
    assert normalize_project_scope("") == "global"
    assert normalize_project_scope(None) == "global"
