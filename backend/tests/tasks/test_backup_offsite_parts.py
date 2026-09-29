"""Large encrypted archives stay byte-identical across bounded Drive parts."""

import hashlib
import json
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest


@pytest.fixture
def drive(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Deterministic provider seam; actual splitting and verification run unchanged."""
    from app.tasks import backup_native_offsite as offsite

    archive = tmp_path / "source-20260921-120000.tar.gz.age"
    archive.write_bytes(b"abcdefghijklmnopqrstuvwxyz")
    folder = "google-drive://account/source"
    state: dict[str, Any] = {
        "archive": archive, "folder": folder, "remote": {}, "commands": [],
        "fail_upload": None, "fail_download": None, "fail_remove": None, "corrupt_download": None,
        "mutate_archive": False, "staged_part_sizes": [],
    }
    monkeypatch.setattr(offsite, "PART_SIZE_BYTES", 8)
    monkeypatch.setattr(offsite.shutil, "which", lambda _name: "/usr/bin/gio")
    monkeypatch.setattr(offsite, "_ensure_display_folder", lambda *_args: folder)
    monkeypatch.setattr(offsite, "_apply_remote_retention", lambda *_args: [])
    monkeypatch.setattr(offsite, "_find_display_child", lambda _folder, name: (
        f"{folder}/{name}" if f"{folder}/{name}" in state["remote"] else None
    ))

    def run(command: list[str], *, timeout: int = 600) -> subprocess.CompletedProcess[str]:
        assert timeout <= 600
        state["commands"].append(command)
        if command[1] == "remove":
            if state["fail_remove"] and command[-1].endswith(state["fail_remove"]):
                return subprocess.CompletedProcess(command, 1, "", "removal unavailable")
            del state["remote"][command[-1]]
            return subprocess.CompletedProcess(command, 0, "", "")
        assert command[:2] == ["gio", "copy"]
        source, target = command[-2:]
        downloading = source.startswith("google-drive://")
        remote_name = source if downloading else target
        failure = state["fail_download" if downloading else "fail_upload"]
        if failure and remote_name.endswith(failure):
            return subprocess.CompletedProcess(command, 1, "", "network unavailable")
        if downloading:
            content = state["remote"][source]
            if state["corrupt_download"] and source.endswith(state["corrupt_download"]):
                content = b"corrupt"
            Path(target).write_bytes(content)
            stage = Path(target).parent
        else:
            stage = Path(source).parent
            state["remote"][target] = Path(source).read_bytes()
            if state["mutate_archive"]:
                with archive.open("ab") as current:
                    current.write(b"changed")
                state["mutate_archive"] = False
        state["staged_part_sizes"].append(sum(
            entry.stat().st_size for entry in stage.iterdir()
            if entry.is_file() and entry.name.endswith(".part")
        ))
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(offsite, "_run", run)
    return state


def replicate(
    drive: dict[str, Any], *, retry: bool = False, on_progress: Callable[[], None] | None = None,
) -> dict[str, Any]:
    from app.tasks import backup_native_offsite as offsite

    return offsite.replicate_completed_archive(
        drive["archive"], source_id="source", local_dir=drive["archive"].parent,
        env={"BACKUP_OFFSITE_GIO_URI": "google-drive://account/root"},
        retention_days=14, retry=retry, on_progress=on_progress,
    )


@pytest.mark.parametrize("failure_part", [None, ".part000001", ".part000002"])
def test_progress_only_follows_verified_parts(drive: dict[str, Any], failure_part: str | None) -> None:
    drive["corrupt_download"] = failure_part
    progress: list[int] = []
    result = replicate(drive, on_progress=lambda: progress.append(len(drive["remote"])))
    expected = 4 if failure_part is None else (0 if failure_part.endswith("1") else 1)
    assert len(progress) == expected
    assert result["status"] == ("verified" if failure_part is None else "failed")


def test_retry_verified_existing_parts_reports_progress(drive: dict[str, Any]) -> None:
    assert replicate(drive)["status"] == "verified"
    progress: list[bool] = []
    assert replicate(drive, retry=True, on_progress=lambda: progress.append(True))["status"] == "verified"
    assert len(progress) == 4


def uploads(drive: dict[str, Any]) -> list[str]:
    return [command[-1] for command in drive["commands"]
            if command[1] == "copy" and not command[-2].startswith("google-drive://")]


def test_interrupted_parts_resume_without_reuploading_verified_parts(drive: dict[str, Any]) -> None:
    drive["fail_upload"] = ".part000003"
    failed = replicate(drive)
    assert failed["status"] == "failed"
    assert not any(name.endswith(".parts.json") for name in drive["remote"])
    assert len(drive["remote"]) == 2
    drive["fail_upload"] = None
    drive["commands"].clear()
    result = replicate(drive, retry=True)
    assert result["status"] == "verified"
    assert [name.rsplit(".", 1)[-1] for name in uploads(drive)] == [
        "part000003", "part000004", "json",
    ]
    assert result["part_count"] == 4
    # One upload part and one verification part, independent of archive size.
    assert max(drive["staged_part_sizes"]) <= 2 * 8


@pytest.mark.parametrize("failure", ["fail_download", "corrupt_download"])
def test_failed_part_verification_never_publishes_manifest(
    drive: dict[str, Any], failure: str,
) -> None:
    drive[failure] = ".part000002"
    result = replicate(drive)
    assert result["status"] == "failed"
    assert not any(name.endswith(".parts.json") for name in drive["remote"])
    assert not any(command[1] == "remove" for command in drive["commands"])


def test_retry_network_failure_preserves_existing_good_remote(drive: dict[str, Any]) -> None:
    assert replicate(drive)["status"] == "verified"
    before = dict(drive["remote"])
    drive["commands"].clear()
    drive["fail_download"] = ".part000002"
    result = replicate(drive, retry=True)
    assert result["status"] == "failed"
    assert drive["remote"] == before
    assert not uploads(drive)
    assert not any(command[1] == "remove" for command in drive["commands"])


def test_retry_replaces_only_part_proven_mismatching(drive: dict[str, Any]) -> None:
    assert replicate(drive)["status"] == "verified"
    part = next(name for name in drive["remote"] if name.endswith(".part000002"))
    drive["remote"][part] = b"corrupt"
    drive["commands"].clear()
    assert replicate(drive, retry=True)["status"] == "verified"
    manifest = f"{drive['folder']}/{drive['archive'].name}.parts.json"
    assert uploads(drive) == [part, manifest]
    assert [command[-1] for command in drive["commands"] if command[1] == "remove"] == [manifest, part]


@pytest.mark.parametrize("missing_part", [False, True])
def test_failed_part_repair_withdraws_old_completion(drive: dict[str, Any], missing_part: bool) -> None:
    assert replicate(drive)["status"] == "verified"
    part = next(name for name in drive["remote"] if name.endswith(".part000002"))
    if missing_part:
        del drive["remote"][part]
    else:
        drive["remote"][part] = b"corrupt"
    drive["commands"].clear()
    drive["fail_upload"] = ".part000002"

    assert replicate(drive, retry=True)["status"] == "failed"
    assert not any(name.endswith(".parts.json") for name in drive["remote"])
    removal_names = [command[-1] for command in drive["commands"] if command[1] == "remove"]
    assert removal_names[0].endswith(".parts.json")
    assert sum(name.endswith(".parts.json") for name in removal_names) == 1


def test_failed_completion_withdrawal_preserves_part_bytes(drive: dict[str, Any]) -> None:
    assert replicate(drive)["status"] == "verified"
    part = next(name for name in drive["remote"] if name.endswith(".part000002"))
    drive["remote"][part] = b"corrupt"
    before = dict(drive["remote"])
    drive["commands"].clear()
    drive["fail_remove"] = ".parts.json"

    result = replicate(drive, retry=True)

    assert result["status"] == "failed"
    assert "completion manifest withdrawal" in result["error"]
    assert drive["remote"] == before
    assert not uploads(drive)


@pytest.mark.parametrize("part_size", [8, 100])
def test_retention_failure_preserves_verified_copy_and_manifest(
    drive: dict[str, Any], monkeypatch: pytest.MonkeyPatch, part_size: int,
) -> None:
    from app.tasks import backup_native_offsite as offsite

    monkeypatch.setattr(offsite, "PART_SIZE_BYTES", part_size)

    def retention(*_args):
        raise RuntimeError("retention unavailable")

    monkeypatch.setattr(offsite, "_apply_remote_retention", retention)
    result = replicate(drive)

    assert result["status"] == "verified"
    assert result["retention_status"] == "failed"
    assert result["retention_deleted"] is None
    assert result["maintenance_error"] == "retention unavailable"
    assert result["location"] in drive["remote"]
    entry = json.loads((drive["archive"].parent / offsite.OFFSITE_MANIFEST_NAME).read_text())["archives"][0]
    assert entry["status"] == "verified"
    assert entry["remote_uri"] == result["location"]
    assert entry["encrypted_checksum"] == result["checksum"]


def test_changed_local_ciphertext_is_not_advertised_as_complete(drive: dict[str, Any]) -> None:
    drive["mutate_archive"] = True
    result = replicate(drive)
    assert result["status"] == "failed"
    assert "Local archive changed" in result["error"]
    assert not any(name.endswith(".parts.json") for name in drive["remote"])


@pytest.mark.parametrize("size", [1, 8])
def test_small_archive_keeps_existing_single_file_contract(drive: dict[str, Any], size: int) -> None:
    drive["archive"].write_bytes(b"x" * size)
    result = replicate(drive)
    assert result["status"] == "verified"
    assert "layout" not in result
    assert list(drive["remote"]) == [drive["folder"] + "/" + drive["archive"].name]


def test_large_archive_uploads_verified_parts_then_manifest_and_reuses_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.tasks import backup_native_offsite as offsite

    archive = tmp_path / "source-20260921-120000.tar.gz.age"
    ciphertext = b"already encrypted archive bytes"
    archive.write_bytes(ciphertext)
    folder = "google-drive://account/source"
    remote: dict[str, bytes] = {}
    uploads: list[str] = []
    monkeypatch.setattr(offsite, "PART_SIZE_BYTES", 8, raising=False)
    monkeypatch.setattr(offsite.shutil, "which", lambda _name: "/usr/bin/gio")
    monkeypatch.setattr(offsite, "_ensure_display_folder", lambda *_args: folder)
    monkeypatch.setattr(offsite, "_apply_remote_retention", lambda *_args: [])
    monkeypatch.setattr(offsite, "_find_display_child", lambda _folder, name: (
        f"{folder}/{name}" if f"{folder}/{name}" in remote else None
    ))

    def run(command: list[str], *, timeout: int = 600):
        assert timeout <= 600
        assert command[:2] == ["gio", "copy"]
        source, target = command[-2:]
        if source.startswith("google-drive://"):
            Path(target).write_bytes(remote[source])
        else:
            remote[target] = Path(source).read_bytes()
            uploads.append(target)
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(offsite, "_run", run)
    result = offsite.replicate_completed_archive(
        archive, source_id="source", local_dir=tmp_path,
        env={"BACKUP_OFFSITE_GIO_URI": "google-drive://account/root"}, retention_days=14,
    )
    assert result["status"] == "verified"
    assert result["layout"] == "parts-v1"
    assert uploads[-1].endswith(".parts.json")
    manifest = json.loads(remote[uploads[-1]])
    assert manifest["format"] == "summitflow-age-parts"
    assert manifest["version"] == 1
    assert manifest["archive_name"] == archive.name
    restored = b"".join(remote[f"{folder}/{part['name']}"] for part in manifest["parts"])
    assert restored == ciphertext
    assert manifest["checksum"] == "sha256:" + hashlib.sha256(restored).hexdigest()
    assert all(part["size_bytes"] <= 8 for part in manifest["parts"])
    assert archive.read_bytes() == ciphertext

    before_retry = len(uploads)
    retry = offsite.replicate_completed_archive(
        archive, source_id="source", local_dir=tmp_path,
        env={"BACKUP_OFFSITE_GIO_URI": "google-drive://account/root"}, retention_days=14,
        retry=True,
    )
    assert retry["status"] == "verified"
    assert retry["reused_local_archive"] is True
    assert len(uploads) == before_retry


def test_retention_removes_only_expired_parts_group_and_keeps_newest(monkeypatch):
    from app.tasks import backup_native_offsite as offsite

    old = "source-20200101-000000.tar.gz.age"
    new = "source-20260921-000000.tar.gz.age"
    names = [old + ".parts.json", old + ".part000001", new + ".parts.json",
             new + ".part000001", old + ".part-not-managed", "notes.json"]
    monkeypatch.setattr(offsite, "_list_children", lambda _uri: [
        {"uri": "drive/" + name, "display_name": name, "attributes": ""} for name in names
    ])
    removed = []

    def run(command, *, timeout=600):
        removed.append(command[-1])
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(offsite, "_run", run)
    offsite._apply_remote_retention("drive", 14, "drive/" + new + ".parts.json")
    assert set(removed) == {"drive/" + old + ".parts.json", "drive/" + old + ".part000001"}


def test_retention_reclaims_expired_incomplete_group_but_not_newest_complete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.tasks import backup_native_offsite as offsite

    old = "source-20180101-000000.tar.gz.age"
    complete = "source-20190101-000000.tar.gz.age"
    orphan = "source-20200101-000000.tar.gz.age"
    names = [old + ".part000001", complete + ".parts.json",
             complete + ".part000001", orphan + ".part000001",
             "source-20209999-000000.tar.gz.age.parts.json"]
    monkeypatch.setattr(offsite, "_list_children", lambda _uri: [
        {"uri": "drive/" + name, "display_name": name, "attributes": ""} for name in names
    ])
    removed: list[str] = []

    def run(command: list[str], *, timeout: int = 600) -> subprocess.CompletedProcess[str]:
        removed.append(command[-1])
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(offsite, "_run", run)
    offsite._apply_remote_retention("drive", 14, "drive/" + complete + ".parts.json")
    assert set(removed) == {"drive/" + old + ".part000001", "drive/" + orphan + ".part000001"}


def test_retention_without_any_complete_archive_does_not_delete_parts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.tasks import backup_native_offsite as offsite

    monkeypatch.setattr(offsite, "_list_children", lambda _uri: [{
        "uri": "drive/part", "display_name": "source-20180101-000000.tar.gz.age.part000001",
        "attributes": "",
    }])
    assert offsite._apply_remote_retention("drive", 14) == []


def test_unmounted_existing_drive_mounts_account_once_then_retries_listing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.tasks import backup_native_offsite as offsite

    commands: list[list[str]] = []
    results = [(1, "The specified location is not mounted"), (0, ""), (0, "")]

    def run(command: list[str], *, timeout: int = 600) -> subprocess.CompletedProcess[str]:
        assert timeout == 60
        commands.append(command)
        status, error = results.pop(0)
        return subprocess.CompletedProcess(command, status, "", error)

    monkeypatch.setattr(offsite, "_run", run)
    assert offsite._list_children("google-drive://owner@example.com/folder") == []
    assert commands[1] == ["gio", "mount", "google-drive://owner@example.com/"]
    assert commands[0] == commands[2]


@pytest.mark.parametrize("mount_error", ["Authentication failed", "Permission denied"])
def test_drive_mount_failure_is_actionable_without_retrying_authentication(
    monkeypatch: pytest.MonkeyPatch, mount_error: str,
) -> None:
    from app.tasks import backup_native_offsite as offsite

    commands: list[list[str]] = []

    def run(command: list[str], *, timeout: int = 600) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        error = "The specified location is not mounted" if command[1] == "list" else mount_error
        return subprocess.CompletedProcess(command, 1, "", error)

    monkeypatch.setattr(offsite, "_run", run)
    with pytest.raises(RuntimeError, match="existing Google Online Account"):
        offsite._list_children("google-drive://owner@example.com/folder")
    assert len(commands) == 2


@pytest.mark.parametrize(("uri", "error"), [
    ("smb://server/share", "The specified location is not mounted"),
    ("google-drive://owner@example.com/folder", "Permission denied"),
    ("google-drive://owner@example.com/folder", "Network unreachable"),
])
def test_non_mount_errors_never_trigger_mount(
    monkeypatch: pytest.MonkeyPatch, uri: str, error: str,
) -> None:
    from app.tasks import backup_native_offsite as offsite

    commands: list[list[str]] = []

    def run(command: list[str], *, timeout: int = 600) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return subprocess.CompletedProcess(command, 1, "", error)

    monkeypatch.setattr(offsite, "_run", run)
    with pytest.raises(RuntimeError, match="GIO list failed"):
        offsite._list_children(uri)
    assert len(commands) == 1


def test_listing_timeout_does_not_trigger_mount(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.tasks import backup_native_offsite as offsite

    calls = 0

    def run(command: list[str], *, timeout: int = 600) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        raise subprocess.TimeoutExpired(command, timeout)

    monkeypatch.setattr(offsite, "_run", run)
    with pytest.raises(subprocess.TimeoutExpired):
        offsite._list_children("google-drive://owner@example.com/folder")
    assert calls == 1


def test_runner_is_noninteractive_and_uses_stable_error_locale(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.tasks import backup_native_offsite as offsite

    def run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        assert kwargs["stdin"] == subprocess.DEVNULL
        assert kwargs["env"]["LC_ALL"] == "C"
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(offsite.subprocess, "run", run)
    offsite._run(["gio", "list", "google-drive://owner@example.com/"])
