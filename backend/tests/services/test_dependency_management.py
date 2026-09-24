"""Dependency evidence must remain bounded, revisioned, and honest about gaps."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.services import dependency_management as management
from app.services.explorer.types.dependencies_nodejs import _parse_pnpm_lock
from app.services.explorer.types.dependencies_python import _parse_pyproject_toml


def _entry() -> dict:
    return {
        "project_id": "summitflow", "path": "python/backend/fastapi", "name": "fastapi",
        "metadata": {"package_type": "python", "constraint": ">=0.100", "locked_version": "0.110", "vulnerabilities": {"high": 0}, "audit_advisories": []},
        "last_scanned_at": "2026-09-23T00:00:00+00:00",
    }


def test_inventory_does_not_treat_lock_or_missing_audit_as_installed_or_clear() -> None:
    item = management._inventory_entry(_entry(), None)
    assert item["locked_version"] == "0.110"
    assert item["installed_version"] is None
    assert item["vulnerabilities"] is None
    assert item["checks"]["installed"] == "unknown"
    assert item["checks"]["advisories"] == "unknown"


def test_review_reuses_unchanged_evidence(monkeypatch) -> None:
    records: list[dict] = []

    def append(_project: str, _path: str, **kwargs):
        if records and records[-1]["evidence_hash"] == kwargs["evidence_hash"]:
            return records[-1], False
        record = {"revision": len(records) + 1, **kwargs}
        records.append(record)
        return record, True

    monkeypatch.setattr(management, "_entry_for_path", lambda *_args, **_kwargs: _entry())
    monkeypatch.setattr(management.dependency_reviews, "append", append)
    source = ([], "checked")
    first = management.review_dependency("summitflow", "python/backend/fastapi", hosted_source=source)
    second = management.review_dependency("summitflow", "python/backend/fastapi", hosted_source=source)
    assert first["new_evidence"] is True
    assert second["new_evidence"] is False
    assert len(records) == 1
    assert first["packet"]["engines"]["dependabot_cli"] in {"unavailable", "available_unrun"}


def test_refresh_removes_entries_missing_from_current_scan() -> None:
    entry = SimpleNamespace(path="python/backend/fastapi", model_dump=lambda: {"path": "python/backend/fastapi"})
    with (
        patch("app.services.explorer.types.dependencies.DependencyScanner.scan", return_value=[entry]),
        patch.object(management.explorer_entries, "upsert_entries") as upsert_mock,
        patch.object(management.explorer_entries, "cleanup_stale_entries") as cleanup_mock,
    ):
        management._refresh_scan("summitflow")
    upsert_mock.assert_called_once()
    cleanup_mock.assert_called_once_with("summitflow", "dependency", {"python/backend/fastapi"})


def test_pyproject_parser_reads_standard_and_dev_groups(tmp_path: Path) -> None:
    manifest = tmp_path / "pyproject.toml"
    manifest.write_text(
        '[project]\ndependencies = ["fastapi>=0.110", "httpx>=0.27"]\n'
        '[dependency-groups]\ndev = ["pytest>=8"]\n',
    )
    parsed = _parse_pyproject_toml(manifest)
    assert parsed["fastapi"] == {"version": ">=0.110", "dev": False}
    assert parsed["pytest"] == {"version": ">=8", "dev": True}


def test_pnpm_lock_parser_includes_scoped_transitives(tmp_path: Path) -> None:
    lock = tmp_path / "pnpm-lock.yaml"
    lock.write_text("lockfileVersion: '9.0'\npackages:\n  '@scope/name@1.2.3': {}\n  'react@19.0.0': {}\n")
    assert _parse_pnpm_lock(lock) == {"@scope/name": "1.2.3", "react": "19.0.0"}


def test_queue_identity_is_stable_for_same_update(monkeypatch) -> None:
    evidence = {"inventory": {"name": "fastapi"}}
    previous = {"revision": 1, "evidence_hash": "digest", "evidence": evidence, "task_id": None}
    identities: list[dict] = []

    def fake_task(*_args, **kwargs):
        identities.append(kwargs["external_identity"])
        return {"id": "task-existing"}

    monkeypatch.setattr(management.dependency_reviews, "latest", lambda *_args: previous)
    monkeypatch.setattr(management.dependency_reviews, "append", lambda *_args, **_kwargs: ({"revision": 2}, True))
    with patch("app.storage.tasks.core.create_task", side_effect=fake_task):
        for _ in range(2):
            management.record_decision(
                "summitflow", "python/backend/fastapi", decision="update",
                rationale="Fixes a confirmed advisory", expected_revision=1,
                recommended_version="0.111", queue_task=True,
            )
    assert identities[0] == identities[1]


def test_scheduled_review_skips_unchanged_recent_evidence(monkeypatch) -> None:
    now = datetime(2026, 9, 23, tzinfo=UTC)
    item = {
        "entry_path": "python/backend/fastapi", "relationship": "direct",
        "advisories": [],
        "review": {
            "created_at": now.isoformat(),
            "evidence": {"inventory": {"advisories": []}},
        },
    }
    monkeypatch.setattr(management, "list_inventory", lambda *_args, **_kwargs: {"items": [item]})
    monkeypatch.setattr(management, "_hosted_pulls", lambda *_args: (_ for _ in ()).throw(AssertionError("unneeded fetch")))
    assert management.review_due_dependencies("summitflow", now=now)["due"] == 0


def test_new_advisory_is_reviewed_before_weekly_interval(monkeypatch) -> None:
    now = datetime(2026, 9, 23, tzinfo=UTC)
    item = {
        "entry_path": "python/backend/fastapi", "relationship": "direct",
        "advisories": ["CVE-1"],
        "review": {
            "created_at": now.isoformat(),
            "evidence": {"inventory": {"advisories": []}},
        },
    }
    monkeypatch.setattr(management, "list_inventory", lambda *_args, **_kwargs: {"items": [item]})
    monkeypatch.setattr(management, "_hosted_pulls", lambda *_args: ([], "checked"))
    calls: list[str] = []
    monkeypatch.setattr(management, "review_dependency", lambda _project, path, **_kwargs: (calls.append(path), {"new_evidence": True})[1])
    result = management.review_due_dependencies("summitflow", now=now)
    assert result == {"due": 1, "new_evidence": 1, "unchanged": 0, "failed": 0}
    assert calls == ["python/backend/fastapi"]
