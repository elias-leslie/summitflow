"""Host adapter contracts; retrieval behavior is exercised with current source."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from code_intelligence.precision import current_search

from app.services.context_gatherer import precision_code_search as adapter


@pytest.mark.parametrize(("minutes", "stale"), [(119, False), (151, True)])
def test_scheduled_index_age_remains_diagnostic(monkeypatch, minutes: int, stale: bool) -> None:
    stamp = (datetime.now(UTC) - timedelta(minutes=minutes)).isoformat()
    monkeypatch.setattr(adapter.explorer_service, "get_stats", lambda *_a, **_k: {"total": 12, "last_scanned": stamp})
    monkeypatch.setattr(adapter, "get_symbol_stats", lambda _: {"count": 4, "last_updated": stamp})
    status = adapter._get_precision_index_status("project-1")
    assert status["should_refresh"] is stale
    assert status["file_total"] == 12
    assert bool(status["refresh_reasons"]) is stale


def test_host_forwards_root_limits_and_optional_transport(monkeypatch, tmp_path: Path) -> None:
    collect = MagicMock()
    monkeypatch.setattr(current_search, "collect_current_search_context", collect)
    monkeypatch.setattr(adapter, "_get_precision_index_status", lambda _: {"should_refresh": False})
    monkeypatch.setattr(adapter.explorer_service, "get_project_root", lambda _: str(tmp_path))
    returned = adapter.collect_precision_code_search_context("p", ["exact_symbol"], budget_tokens=800, symbol_limit=3, path_prefix="api", include_candidates=True)
    assert returned is collect.return_value
    kwargs = collect.call_args.kwargs
    assert kwargs["project_root"] == tmp_path
    assert kwargs["budget_tokens"] == 800
    assert kwargs["symbol_limit"] == 3
    assert kwargs["path_prefix"] == "api"
    assert kwargs["include_candidates"] is True
    assert kwargs["index_status"]["refreshed_index"] is False


def test_unavailable_index_and_root_are_reported_without_private_connection_details(monkeypatch) -> None:
    def unavailable(*_args):
        raise ConnectionError("private connection detail")
    collect = MagicMock()
    monkeypatch.setattr(current_search, "collect_current_search_context", collect)
    monkeypatch.setattr(adapter, "_get_precision_index_status", unavailable)
    monkeypatch.setattr(adapter.explorer_service, "get_project_root", unavailable)
    adapter.collect_precision_code_search_context("p", ["exact_symbol"])
    kwargs = collect.call_args.kwargs
    assert kwargs["project_root"] is None
    assert kwargs["index_status"]["index_status_error"] == "ConnectionError"
    assert kwargs["index_status"]["root_lookup_error"] == "ConnectionError"
    assert "private connection detail" not in repr(kwargs)
