"""Tests for mockup generator service boundaries."""

from __future__ import annotations

from unittest.mock import patch

from app.services.mockup_generator import MockupResult, generate_mockup


@patch("app.services.mockup_generator._run_with_fallback")
@patch("app.services.mockup_generator.get_design_standard")
@patch("app.storage.explorer_entries.get_entry_by_id")
def test_generate_mockup_fetches_page_info_from_storage_module(
    mock_get_entry_by_id,
    mock_get_design_standard,
    mock_run_with_fallback,
) -> None:
    mock_get_entry_by_id.return_value = {
        "path": "/landing",
        "name": "Landing Page",
        "description": "Marketing page",
    }
    mock_get_design_standard.return_value = {"id": 1, "name": "Base"}
    mock_run_with_fallback.return_value = MockupResult(success=True, mockup_id="mockup-1")

    result = generate_mockup("summitflow", 42)

    assert result.success is True
    mock_get_entry_by_id.assert_called_once_with(42)
    assert mock_run_with_fallback.call_args.args[2] == {
        "path": "/landing",
        "name": "Landing Page",
        "description": "Marketing page",
    }
