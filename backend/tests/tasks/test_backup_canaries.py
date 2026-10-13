"""Nightshift canary files are never captured."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.tasks import backup_canaries
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
                    "OptGuideOnDeviceModel/weights.bin", "Default/Extensions/abc/1.0/x.js", "SingletonLock"):
        assert _should_exclude(dropped, excludes), dropped
