"""Nightshift canary files are never captured."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from app.tasks import backup_canaries
from app.tasks import backup_native_archive as archive
from app.tasks import backup_native_recovery as recovery
from app.tasks.backup_native_archive import _load_excludes, _should_exclude


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    (home / "Documents" / "archive").mkdir(parents=True)
    (home / "Documents" / "passwords [2025].pdf").write_text("decoy")
    (home / "Documents" / "archive" / ".env.production").write_text("decoy")
    (home / "Documents" / "notes.txt").write_text("mine")
    (home / ".aws").mkdir()
    (home / ".aws" / "credentials").write_text("decoy")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(backup_canaries.Path, "home", classmethod(lambda cls: home))
    return home


def test_canaries_inside_a_source_are_excluded_by_exact_path(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(backup_canaries, "_registry", lambda: [
        "~/Documents/passwords [2025].pdf", "~/Documents/archive/.env.production",
        "~/.aws/credentials [prod-archive]", "~/Documents/missing.pdf", "nightshift repo deploy/.env.example",
    ])
    excludes = _load_excludes(home / "Documents", "Documents")
    assert _should_exclude("passwords [2025].pdf", excludes)
    assert _should_exclude("archive/.env.production", excludes)
    assert not _should_exclude("notes.txt", excludes) and not _should_exclude("archive", excludes)
    # A section suffix names the file; the decoy file itself is the exclusion.
    assert backup_canaries.canary_excludes(home / ".aws") == ("./credentials",)
    with pytest.raises(RuntimeError, match="canary"):
        backup_canaries.canary_excludes(home / ".aws" / "credentials")


def test_last_good_list_survives_a_nightshift_outage_and_home_fails_closed_without_one(
        home: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(backup_canaries, "_registry", lambda: ["~/Documents/archive/.env.production"])
    assert backup_canaries.canary_excludes(home / "Documents") == ("./archive/.env.production",)
    monkeypatch.setattr(backup_canaries, "_registry", lambda: None)
    assert backup_canaries.canary_excludes(home / "Documents") == ("./archive/.env.production",)
    backup_canaries._cache_path().unlink()
    with pytest.raises(RuntimeError, match="unavailable"):
        backup_canaries.canary_excludes(home / "Documents")
    outside = tmp_path / "project"
    outside.mkdir()
    assert backup_canaries.canary_excludes(outside) == ()


def test_chrome_profile_keeps_user_data_and_drops_rebuildable_caches(tmp_path: Path) -> None:
    excludes = _load_excludes(tmp_path / "google-chrome", "google-chrome")
    for kept in ("Local State", "Default/Login Data", "Default/Bookmarks", "Default/IndexedDB/x", "Default/Cookies"):
        assert not _should_exclude(kept, excludes), kept
    for dropped in ("Default/Cache/x", "Default/Code Cache/js/x", "Default/Service Worker/CacheStorage/x",
                    "OptGuideOnDeviceModel/weights.bin", "Default/Extensions/abc/1.0/x.js", "SingletonLock",
                    "Default/DNR Extension Rules/abc/rules.fbs"):
        assert _should_exclude(dropped, excludes), dropped


def _write(root: Path, relative: str, value: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value)


@pytest.mark.parametrize("edit", [None, "Default/Bookmarks"])
def test_chrome_profile_capture_survives_a_running_browser(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, edit: str | None) -> None:
    monkeypatch.setattr(backup_canaries, "_registry", lambda: [])
    profile = tmp_path / "google-chrome"
    for relative, value in (("Local State", "{}"), ("Default/Preferences", '{"a": 1}'), ("Default/Bookmarks", "{}"),
                            ("Default/Network Persistent State", '{"n": 1}'),
                            ("Default/Extension State/000526.log", "record1"), ("Default/Extension State/MANIFEST-000001", "m1")):
        _write(profile, relative, value)
    original = recovery.copy_inventory_snapshot

    def copy_while_chrome_runs(*args: Any, **kwargs: Any) -> None:
        # Chrome replaces Preferences between the inventory and the copy, and again after it.
        _write(profile, "Default/Preferences.tmp", '{"a": 3}')
        os.replace(profile / "Default/Preferences.tmp", profile / "Default/Preferences")
        original(*args, **kwargs)
        _write(profile, "Default/Network Persistent State.tmp", '{"n": 2}')
        os.replace(profile / "Default/Network Persistent State.tmp", profile / "Default/Network Persistent State")
        with (profile / "Default/Extension State/000526.log").open("a") as log:
            log.write("record2")
        _write(profile, "Default/Preferences.tmp", '{"a": 2}')
        os.replace(profile / "Default/Preferences.tmp", profile / "Default/Preferences")
        if edit:
            _write(profile, edit, '{"changed": true}')

    monkeypatch.setattr(recovery, "copy_inventory_snapshot", copy_while_chrome_runs)
    if edit:
        with pytest.raises(RuntimeError, match=f"changed during capture: {edit}"):
            archive.prepare_project_payload(profile, "google-chrome", tmp_path / "staging", {})
        return
    payload = archive.prepare_project_payload(profile, "google-chrome", tmp_path / "staging", {})
    snapshot = payload["snapshot_dir"]
    assert payload["recovery"]["consistent"] is True
    assert (snapshot / "Default/Extension State/000526.log").read_text() == "record1"
    assert (snapshot / "Default/Preferences").read_text() == '{"a": 3}'
    assert (snapshot / "Default/Network Persistent State").read_text() == '{"n": 1}'
