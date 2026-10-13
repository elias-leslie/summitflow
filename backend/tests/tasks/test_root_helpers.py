"""Path confinement of the root-owned SummitFlow helpers (they replace root-equivalent sudo rules)."""

from __future__ import annotations

import hashlib
import importlib.machinery
import importlib.util
import os
from pathlib import Path
from types import ModuleType

import pytest

SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"
RUN = "20261012T223307Z-91d4c21f"


def _load(name: str) -> ModuleType:
    loader = importlib.machinery.SourceFileLoader(name.replace("-", "_"), str(SCRIPTS / name))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


@pytest.fixture
def native(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    helper = _load("summitflow-native-capture")
    captures = tmp_path / "store" / "captures"
    captures.mkdir(parents=True)
    home = tmp_path / "home"
    (home / helper.OPERATIONS / RUN).mkdir(parents=True)
    monkeypatch.setattr(helper, "CAPTURES", captures)
    monkeypatch.setattr(helper, "_root_directory", lambda _path: None)  # root ownership is the installed host's job
    monkeypatch.setattr(helper.pwd, "getpwuid", lambda _uid: type("Account", (), {"pw_dir": str(home)}))
    monkeypatch.setenv("SUDO_UID", str(os.getuid()))
    return helper


def _source(helper: ModuleType, tmp_path: Path, data: bytes = b"{}") -> tuple[Path, str]:
    path = tmp_path / "home" / helper.OPERATIONS / RUN / "publication.json"
    path.write_bytes(data)
    return path, hashlib.sha256(data).hexdigest()


def test_publish_installs_verified_bytes_into_its_capture(native: ModuleType, tmp_path: Path) -> None:
    source, digest = _source(native, tmp_path)
    native.publish(RUN, "capture.json", str(source), digest)
    published = native.CAPTURES / RUN / "capture.json"
    assert published.read_bytes() == b"{}" and published.stat().st_mode & 0o777 == 0o600
    assert not (native.CAPTURES / RUN / "capture.json.preparing").exists()


@pytest.mark.parametrize("case", ["traversal-run", "unknown-name", "bad-digest", "outside-source", "dotdot-source", "symlink-source"])
def test_publish_refuses_anything_outside_its_fixed_paths(native: ModuleType, tmp_path: Path, case: str) -> None:
    source, digest = _source(native, tmp_path)
    run, name = RUN, "capture.json"
    if case == "traversal-run":
        run = f"../{RUN}"
    elif case == "unknown-name":
        name = "../../etc/passwd"
    elif case == "bad-digest":
        digest = "0" * 64
    elif case == "outside-source":
        source = tmp_path / "elsewhere.json"
        source.write_text("{}")
    elif case == "dotdot-source":
        source = source.parent / ".." / RUN / source.name
    else:
        secret = tmp_path / "secret"
        secret.write_text("{}")
        source.unlink()
        source.symlink_to(secret)
    with pytest.raises((SystemExit, OSError)):
        native.publish(run, name, str(source), digest)
    assert not (native.CAPTURES / RUN / "capture.json").exists()


def test_listing_and_sync_only_name_fixed_stores(native: ModuleType) -> None:
    for action in (native.listing, native.sync):
        with pytest.raises(SystemExit):
            action("/etc")


def test_remove_only_takes_a_run_id(native: ModuleType) -> None:
    with pytest.raises(SystemExit):
        native.remove("..")


@pytest.mark.parametrize("name", ["../shadow", "a/b", ".hidden", "", "x" * 200])
def test_steward_receipt_names_stay_in_the_receipt_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    helper = _load("summitflow-steward-receipt")
    monkeypatch.setattr(helper, "RECEIPTS", tmp_path)
    with pytest.raises(SystemExit):
        helper._store(name, b"data")


def test_steward_receipt_replaces_atomically_and_refuses_symlinks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    helper = _load("summitflow-steward-receipt")
    monkeypatch.setattr(helper, "RECEIPTS", tmp_path)
    monkeypatch.setattr(helper.os, "lstat", lambda _path: os.stat_result((0o40755, 0, 0, 0, 0, 0, 0, 0, 0, 0)))
    helper._store("run.json", b"first")
    helper._store("run.json", b"second")
    assert (tmp_path / "run.json").read_bytes() == b"second"
    (tmp_path / "link.json").symlink_to(tmp_path / "run.json")
    with pytest.raises(SystemExit):
        helper._store("link.json", b"overwrite through a link")
    assert (tmp_path / "run.json").read_bytes() == b"second"
