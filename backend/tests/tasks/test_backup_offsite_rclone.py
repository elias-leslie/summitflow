"""Native Drive replication verifies fresh hashes without payload readback."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import pytest


@pytest.fixture
def drive(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    from app.tasks import backup_native_offsite as offsite
    from app.tasks import backup_native_rclone as provider

    keys = tmp_path / "keys"
    keys.mkdir(mode=0o700)
    config = keys / "summitflow-drive.conf"
    config.write_text("[summitflow-drive]\ntype = drive\ntoken = private-oauth-fixture\n")
    config.chmod(0o600)
    archive = tmp_path / "source-20260921-120000.tar.gz.age"
    archive.write_bytes(b"already encrypted canonical payload")
    root = "summitflow-drive:Canonical"
    folder = root + "/source"
    state: dict[str, Any] = {
        "archive": archive, "env": {"BACKUP_OFFSITE_TRANSPORT": "rclone",
        "BACKUP_OFFSITE_RCLONE_REMOTE": root, "BACKUP_OFFSITE_RCLONE_CONFIG": str(config)},
        "root": root, "folder": folder, "objects": {}, "directories": {root: "root-id"},
        "commands": [], "hashes": ["SHA-256", "SHA-1", "MD5"], "next_id": 0,
        "fail_upload": None, "fail_stat": None, "fail_remove": None,
        "change_id": None, "bad_size": None, "corrupt_upload": None,
        "duplicate": None, "fail_retention": False, "mutate_local": False,
        "hash_override": None, "duplicate_folder": False,
        "duplicate_root": False, "change_source_folder_id": False, "source_folder_reads": 0,
    }
    monkeypatch.setattr(offsite.shutil, "which", lambda name: f"/usr/bin/{name}")
    # No live provider request can escape this process seam.
    monkeypatch.setenv("RCLONE_CONFIG_SUMMITFLOW_DRIVE_TOKEN", "must-not-inherit")
    monkeypatch.setenv("RCLONE_DRIVE_USE_TRASH", "false")

    def item(target: str, *, hashes: bool = False) -> dict[str, Any]:
        obj = state["objects"][target]
        result = {"Name": target.rsplit("/", 1)[-1], "Path": target.rsplit("/", 1)[-1],
                  "ID": obj["id"], "Size": len(obj["content"]), "IsDir": False}
        if hashes:
            result["Hashes"] = {name: hashlib.new(name.lower().replace("-", ""), obj["content"]).hexdigest()
                                for name in state["hashes"]}
            if state["hash_override"] is not None:
                result["Hashes"] = state["hash_override"]
            if state["change_id"] and target.endswith(state["change_id"]):
                result["ID"] = "replacement-id"
            if state["bad_size"] and target.endswith(state["bad_size"]):
                result["Size"] = -1
        return result

    def run(command: list[str], *, env: dict[str, str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        assert not any(key.startswith(("RESTIC_", "RCLONE_")) for key in env)
        assert command[-2:] == ["--config", str(config)]
        assert kwargs["phase"] in {"verification", "upload", "retention"}
        args = command[1:-2]
        state["commands"].append(args)
        result: Any = ""
        if args[0] == "lsjson":
            target = args[1]
            if "--stat" in args:
                if target in state["directories"]:
                    # Actual rclone directory --stat describes a virtual Fs
                    # root, rather than an object with a provider ID.
                    result = {"Path": "", "Name": "", "IsDir": True, "Size": -1}
                else:
                    if state["fail_stat"] and target.endswith(state["fail_stat"]):
                        return subprocess.CompletedProcess(command, 1, "", "token=private-oauth-fixture")
                    result = item(target, hashes=True)
            elif "--dirs-only" in args:
                result = []
                for path, provider_id in state["directories"].items():
                    remote, relative = path.split(":", 1)
                    parent = remote + ":" + (relative.rsplit("/", 1)[0] if "/" in relative else "")
                    if parent == target:
                        result.append({"ID": provider_id, "IsDir": True, "Name": relative.rsplit("/", 1)[-1]})
                if target == state["root"]:
                    state["source_folder_reads"] += 1
                    if state["change_source_folder_id"] and state["source_folder_reads"] > 1:
                        result = [dict(entry, ID="replacement-source-id") if entry["Name"] == "source" else entry for entry in result]
                if state["duplicate_folder"] and target == state["root"]:
                    result += [{"ID": "folder-1", "IsDir": True, "Name": "source"},
                               {"ID": "folder-2", "IsDir": True, "Name": "source"}]
                if state["duplicate_root"] and target == "summitflow-drive:":
                    result.append({"ID": "duplicate-root-id", "IsDir": True, "Name": "Canonical"})
            else:
                result = [item(path) for path in state["objects"] if path.rsplit("/", 1)[0] == target]
                if state["duplicate"]:
                    result += [dict(entry, ID="duplicate-id") for entry in result if entry["Name"].endswith(state["duplicate"])]
        elif args[0] == "mkdir":
            state["directories"].setdefault(args[1], "source-id")
        elif args[0] == "copyto":
            source, target = args[1:3]
            assert args[3:] == ["--immutable"]
            assert target not in state["objects"]
            if state["fail_upload"] and target.endswith(state["fail_upload"]):
                return subprocess.CompletedProcess(command, 1, "", "token=private-oauth-fixture")
            state["next_id"] += 1
            content = Path(source).read_bytes()
            if state["corrupt_upload"] and target.endswith(state["corrupt_upload"]):
                content = b"corrupt"
            state["objects"][target] = {"id": f"object-{state['next_id']}", "content": content}
            if state["mutate_local"]:
                state["archive"].write_bytes(state["archive"].read_bytes() + b"changed")
                state["mutate_local"] = False
        elif args[0] == "deletefile":
            assert args[2:] in (["--drive-use-trash=true"], ["--drive-use-trash=false"])
            if args[2:] == ["--drive-use-trash=false"]:
                assert state["env"].get("BACKUP_OFFSITE_RCLONE_PERMANENT_EXPIRY") == "true"
                assert state["env"].get("BACKUP_OFFSITE_RCLONE_ROOT_ID") == "root-id"
            if (state["fail_remove"] and args[1].endswith(state["fail_remove"])) or state["fail_retention"]:
                return subprocess.CompletedProcess(command, 1, "", "token=private-oauth-fixture")
            del state["objects"][args[1]]
        else:
            pytest.fail(f"Unexpected command: {args[0]}")
        return subprocess.CompletedProcess(command, 0, json.dumps(result) if result != "" else "", "")

    monkeypatch.setattr(provider, "run_bulk_process", run)
    return state


def replicate(drive: dict[str, Any], *, retry: bool = False, on_progress=None) -> dict[str, Any]:
    from app.tasks.backup_native_offsite import replicate_completed_archive

    return replicate_completed_archive(
        drive["archive"], source_id="source", local_dir=drive["archive"].parent,
        env=drive["env"], retention_days=14, retry=retry, on_progress=on_progress,
    )


def uploads(drive: dict[str, Any]) -> list[str]:
    return [args[2] for args in drive["commands"] if args[0] == "copyto"]


def test_provider_hash_verification_needs_no_full_archive_scratch_copy(drive, monkeypatch, backup_job_scratch):
    import shutil

    from app.utils import transient_scratch as scratch

    usage = shutil.disk_usage(backup_job_scratch)
    monkeypatch.setenv("SF_HOST_RETENTION_PRESSURE_MIN_FREE_GB", "25")
    monkeypatch.setattr(scratch.shutil, "disk_usage", lambda _path: usage._replace(free=25 * 1024**3))
    result = replicate(drive)
    assert result["status"] == "verified"
    assert not list(backup_job_scratch.glob("st-backups-*/*"))
    assert not any(args[0] == "copyto" and args[2].startswith("/") for args in drive["commands"])


def replicate_legacy_parts(drive: dict[str, Any], *, retry: bool = False, on_progress=None) -> dict[str, Any]:
    """Exercise legacy multipart repair independently of whole-file dispatch."""
    from app.tasks import backup_native_offsite as offsite
    from app.tasks.backup_native_rclone import NativeRcloneProvider

    provider = NativeRcloneProvider(drive["env"])
    folder = provider.ensure_folder("source")
    with tempfile.TemporaryDirectory(prefix="test-offsite-parts-") as staging:
        return offsite._replicate_parts(
            drive["archive"], source_folder_uri=folder,
            local_checksum="sha256:" + hashlib.sha256(drive["archive"].read_bytes()).hexdigest(),
            temporary_dir=Path(staging), retry=retry, on_progress=on_progress, provider=provider,
        )


def test_rclone_above_legacy_part_threshold_copies_one_exact_archive(drive, monkeypatch):
    from app.tasks import backup_native_offsite as offsite

    monkeypatch.setattr(offsite, "PART_SIZE_BYTES", 8)
    original = drive["archive"].read_bytes()
    result = replicate(drive)
    target = drive["folder"] + "/" + drive["archive"].name
    assert result["status"] == "verified"
    assert uploads(drive) == [target]
    assert drive["objects"][target]["content"] == original
    assert drive["archive"].read_bytes() == original
    assert not any(".part" in path for path in drive["objects"])
    assert not any(args[0] in {"copy", "cat"} for args in drive["commands"])
    assert result["transfer_bytes"] == len(original)
    drive["commands"].clear()
    retried = replicate(drive, retry=True)
    assert retried["status"] == "verified"
    assert retried["transfer_bytes"] == 0
    assert not uploads(drive)
    assert drive["objects"][target]["content"] == original


@pytest.mark.parametrize("hash_name,method", [("SHA-256", "sha256"), ("SHA-1", "sha1"), ("MD5", "md5")])
def test_single_exact_ciphertext_with_fresh_provider_hash_and_identity(drive, hash_name, method):
    before = drive["archive"].read_bytes()
    drive["hashes"] = [hash_name]
    result = replicate(drive)
    assert result["status"] == "verified"
    assert result["transport"] == "rclone"
    assert result["checksum"] == "sha256:" + hashlib.sha256(before).hexdigest()
    assert result["transfer_bytes"] == len(before)
    artifact = result["artifacts"][0]
    assert result["location"] == "gdrive://" + artifact["provider_id"]
    assert artifact["verification_method"] == "provider-" + method
    assert artifact["provider_checksum"] == method + ":" + hashlib.new(method, before).hexdigest()
    assert drive["objects"][artifact["remote_path"]]["content"] == before
    assert drive["archive"].read_bytes() == before
    assert not any(args[0] in {"cat", "copy", "backend"} for args in drive["commands"])
    entry = json.loads((drive["archive"].parent / "offsite-manifest.json").read_text())["archives"][0]
    assert entry["artifacts"] == result["artifacts"]


def test_retry_freshly_checks_existing_objects_without_upload_or_download(drive):
    assert replicate(drive)["status"] == "verified"
    drive["commands"].clear()
    result = replicate(drive, retry=True)
    assert result["status"] == "verified"
    assert result["transfer_bytes"] == 0
    assert not uploads(drive)
    assert any("--hash-type" in args for args in drive["commands"])


def test_offline_upload_then_retry_uses_unchanged_retained_ciphertext(drive):
    original = drive["archive"].read_bytes()
    checksum = "sha256:" + hashlib.sha256(original).hexdigest()
    drive["fail_upload"] = drive["archive"].name
    failed = replicate(drive)
    assert failed["status"] == "failed"
    assert failed["local_checksum"] == checksum
    assert drive["archive"].read_bytes() == original
    assert not drive["objects"]
    drive["fail_upload"] = None
    drive["commands"].clear()
    result = replicate(drive, retry=True)
    assert result["status"] == "verified"
    assert result["reused_local_archive"] is True
    assert result["checksum"] == checksum
    assert drive["archive"].read_bytes() == original
    assert drive["objects"][result["artifacts"][0]["remote_path"]]["content"] == original
    assert not any(args[0] in {"age", "tar", "restic", "cat"} for args in drive["commands"])


def test_unavailable_verification_then_retry_checks_uploaded_exact_artifact(drive):
    original = drive["archive"].read_bytes()
    drive["fail_stat"] = drive["archive"].name
    failed = replicate(drive)
    assert failed["status"] == "failed"
    assert drive["archive"].read_bytes() == original
    assert len(drive["objects"]) == 1
    before = dict(drive["objects"])
    drive["fail_stat"] = None
    drive["commands"].clear()
    result = replicate(drive, retry=True)
    assert result["status"] == "verified"
    assert result["transfer_bytes"] == 0
    assert drive["objects"] == before
    assert not uploads(drive)


def test_explicit_rclone_route_without_remote_fails_truthfully(drive):
    drive["env"].pop("BACKUP_OFFSITE_RCLONE_REMOTE")
    result = replicate(drive)
    assert result["status"] == "failed"
    assert "remote is missing" in result["error"]
    assert not drive["commands"]


@pytest.mark.parametrize("failure", ["invalid_transport", "missing_remote", "missing_rclone", "missing_gio", "unencrypted_archive"])
def test_preflight_failure_records_manifest_and_preserves_expired_secondary_copy(drive, monkeypatch, failure):
    from app.tasks import backup_native_offsite as offsite
    from app.tasks.backup_native_storage import apply_local_retention

    original = drive["archive"].read_bytes()
    if failure == "invalid_transport":
        drive["env"]["BACKUP_OFFSITE_TRANSPORT"] = "private-token-invalid-transport"
    elif failure == "missing_remote":
        drive["env"].pop("BACKUP_OFFSITE_RCLONE_REMOTE")
    elif failure in {"missing_rclone", "missing_gio"}:
        if failure == "missing_gio":
            drive["env"].update(BACKUP_OFFSITE_TRANSPORT="gio", BACKUP_OFFSITE_GIO_URI="google-drive://fixture/root")
        monkeypatch.setattr(offsite.shutil, "which", lambda _name: None)
    else:
        unencrypted = drive["archive"].with_name(drive["archive"].name.removesuffix(".age"))
        drive["archive"].rename(unencrypted)
        drive["archive"] = unencrypted
    result = replicate(drive)
    assert result["status"] == "failed"
    assert not drive["commands"]
    assert "private-token" not in str(result)
    manifest_path = drive["archive"].parent / offsite.OFFSITE_MANIFEST_NAME
    entry = json.loads(manifest_path.read_text())["archives"][0]
    assert entry["archive_name"] == drive["archive"].name
    assert entry["source_id"] == "source"
    assert entry["status"] == "failed"
    assert entry["error"] == result["error"]
    assert "private-token" not in manifest_path.read_text()
    # Ensure the failed copy falls outside both retention age and minimum-three
    # protection; only the durable replica manifest may preserve it here.
    os.utime(drive["archive"], (1, 1))
    for number in range(4):
        (drive["archive"].parent / f"new-{number}-20260930-120000.tar.gz.age").write_bytes(b"new recovery point")
    apply_local_retention(drive["archive"].parent, retention_days=14)
    assert drive["archive"].read_bytes() == original


def test_invalid_private_config_does_not_expose_contents_or_chained_exception(drive):
    from app.tasks.backup_native_rclone import NativeRcloneProvider

    config = Path(drive["env"]["BACKUP_OFFSITE_RCLONE_CONFIG"])
    config.write_text("private-oauth-fixture missing a section\n")
    with pytest.raises(RuntimeError) as failure:
        NativeRcloneProvider(drive["env"])
    assert failure.value.__suppress_context__ is True
    assert "private-oauth-fixture" not in str(failure.value)
    assert not drive["commands"]


@pytest.mark.parametrize("failure", ["missing_hash", "identity", "size", "corruption"])
def test_invalid_fresh_metadata_never_claims_valid(drive, failure):
    suffix = drive["archive"].name
    if failure == "missing_hash":
        drive["hashes"] = []
    else:
        drive[{"identity": "change_id", "size": "bad_size", "corruption": "corrupt_upload"}[failure]] = suffix
    result = replicate(drive)
    assert result["status"] == "failed"
    assert not any(args[0] == "deletefile" for args in drive["commands"])


def test_stat_failure_on_retry_preserves_good_objects_and_redacts_provider_errors(drive):
    assert replicate(drive)["status"] == "verified"
    before = dict(drive["objects"])
    drive["commands"].clear()
    drive["fail_stat"] = drive["archive"].name
    result = replicate(drive, retry=True)
    assert result["status"] == "failed"
    assert "private-oauth-fixture" not in result["error"]
    assert drive["objects"] == before
    assert not uploads(drive)
    assert not any(args[0] == "deletefile" for args in drive["commands"])


def test_duplicate_display_name_is_rejected_before_remote_mutation(drive):
    assert replicate(drive)["status"] == "verified"
    before = dict(drive["objects"])
    drive["commands"].clear()
    drive["duplicate"] = drive["archive"].name
    assert replicate(drive, retry=True)["status"] == "failed"
    assert drive["objects"] == before
    assert not any(args[0] in {"copyto", "deletefile"} for args in drive["commands"])


def test_duplicate_source_folders_fail_before_remote_mutation(drive):
    drive["duplicate_folder"] = True
    assert replicate(drive)["status"] == "failed"
    assert not any(args[0] in {"mkdir", "copyto", "deletefile"} for args in drive["commands"])


@pytest.mark.parametrize("hashes", [{"SHA-256": "not-a-digest"}, {"SHA-256": 42}, [], {"SHA-256": ""}])
def test_malformed_or_empty_hash_never_claims_valid(drive, hashes):
    drive["hash_override"] = hashes
    assert replicate(drive)["status"] == "failed"
    assert not any(args[0] == "deletefile" for args in drive["commands"])


def test_existing_object_without_hash_is_not_removed_or_reuploaded(drive):
    assert replicate(drive)["status"] == "verified"
    before = dict(drive["objects"])
    drive["commands"].clear()
    drive["hashes"] = []
    assert replicate(drive, retry=True)["status"] == "failed"
    assert drive["objects"] == before
    assert not any(args[0] in {"copyto", "deletefile"} for args in drive["commands"])


@pytest.mark.parametrize("missing", [False, True])
def test_multipart_repair_withdraws_completion_before_replacing_part(drive, monkeypatch, missing, tmp_path):
    from app.tasks import backup_native_offsite as offsite

    monkeypatch.setattr(offsite, "PART_SIZE_BYTES", 8)
    original = drive["archive"].read_bytes()
    assert replicate_legacy_parts(drive)["layout"] == "parts-v1"
    part = drive["folder"] + "/" + drive["archive"].name + ".part000002"
    manifest = drive["folder"] + "/" + drive["archive"].name + ".parts.json"
    if missing:
        del drive["objects"][part]
    else:
        drive["objects"][part]["content"] = b"corrupt"
    drive["commands"].clear()
    progress = []
    result = replicate_legacy_parts(drive, retry=True, on_progress=lambda: progress.append(True))
    assert result["layout"] == "parts-v1"
    assert uploads(drive) == [part, manifest]
    removals = [args[1] for args in drive["commands"] if args[0] == "deletefile"]
    assert removals == ([manifest] if missing else [manifest, part])
    assert len(progress) == result["part_count"]
    metadata = json.loads(drive["objects"][manifest]["content"])
    assert all(set(item) == {"name", "size_bytes", "checksum"} for item in metadata["parts"])
    assert all(item["location"] == "gdrive://" + item["provider_id"] for item in result["artifacts"])
    download = tmp_path / "download"
    download.mkdir()
    manifest_path = download / (drive["archive"].name + ".parts.json")
    manifest_path.write_bytes(drive["objects"][manifest]["content"])
    for item in metadata["parts"]:
        (download / item["name"]).write_bytes(drive["objects"][drive["folder"] + "/" + item["name"]]["content"])
    restored_dir = tmp_path / "restored"
    restored_dir.mkdir()
    destination = restored_dir / drive["archive"].name
    script = Path(__file__).resolve().parents[3] / "scripts/recovery-bootstrap.py"
    assembled = subprocess.run(
        [sys.executable, str(script), "--assemble-parts", str(manifest_path), "--output-file", str(destination)],
        capture_output=True, text=True, check=False,
    )
    assert assembled.returncode == 0, assembled.stderr
    assert destination.read_bytes() == original
    assert "sha256:" + hashlib.sha256(destination.read_bytes()).hexdigest() == metadata["checksum"]
    assert drive["archive"].read_bytes() == original


def test_failed_multipart_upload_or_hash_never_publishes_completion(drive, monkeypatch):
    from app.tasks import backup_native_offsite as offsite

    monkeypatch.setattr(offsite, "PART_SIZE_BYTES", 8)
    drive["fail_upload"] = ".part000003"
    with pytest.raises(RuntimeError):
        replicate_legacy_parts(drive)
    assert not any(path.endswith(".parts.json") for path in drive["objects"])
    drive["fail_upload"] = None
    drive["commands"].clear()
    result = replicate_legacy_parts(drive, retry=True)
    assert result["layout"] == "parts-v1"
    assert not any(path.endswith((".part000001", ".part000002")) for path in uploads(drive))


def test_failed_multipart_repair_withdrawal_preserves_part(drive, monkeypatch):
    from app.tasks import backup_native_offsite as offsite

    monkeypatch.setattr(offsite, "PART_SIZE_BYTES", 8)
    assert replicate_legacy_parts(drive)["layout"] == "parts-v1"
    part = drive["folder"] + "/" + drive["archive"].name + ".part000002"
    drive["objects"][part]["content"] = b"corrupt"
    before = dict(drive["objects"])
    drive["fail_remove"] = ".parts.json"
    drive["commands"].clear()
    with pytest.raises(RuntimeError):
        replicate_legacy_parts(drive, retry=True)
    assert drive["objects"] == before
    assert not uploads(drive)


@pytest.mark.parametrize("hashes", [["SHA-256"], ["MD5"]])
def test_changed_local_ciphertext_never_claims_valid(drive, hashes):
    drive["hashes"] = hashes
    drive["mutate_local"] = True
    assert replicate(drive)["status"] == "failed"


@pytest.mark.parametrize("permanent", [False, True])
def test_retention_expires_only_managed_group_completion_first(drive, permanent):
    if permanent:
        drive["env"].update(BACKUP_OFFSITE_RCLONE_PERMANENT_EXPIRY="true", BACKUP_OFFSITE_RCLONE_ROOT_ID="root-id")
    old = "source-20200101-000000.tar.gz.age"
    newest = "source-20260930-000000.tar.gz.age"
    names = [old + ".parts.json", old + ".part000001", newest + ".parts.json",
             newest + ".part000001", "source-20260601-000000.tar.gz.age",
             "notes.json", "orphan-20200101-000000.tar.gz.age.part000001"]
    for index, name in enumerate(names):
        drive["objects"][drive["folder"] + "/" + name] = {"id": f"retained-{index}", "content": b"data"}
    result = replicate(drive)
    assert result["status"] == "verified"
    assert result["retention_deleted"] == 3
    assert result["retention_mode"] == ("permanent" if permanent else "trash")
    deleted = [args[1].rsplit("/", 1)[-1] for args in drive["commands"] if args[0] == "deletefile"]
    assert deleted[:2] == [old + ".parts.json", old + ".part000001"]
    assert newest + ".parts.json" not in deleted
    assert "notes.json" not in deleted
    assert all(args[2:] == [f"--drive-use-trash={str(not permanent).lower()}"]
               for args in drive["commands"] if args[0] == "deletefile")


def test_retention_failure_preserves_verified_result(drive):
    old = drive["folder"] + "/old-20200101-000000.tar.gz.age"
    drive["objects"][old] = {"id": "old-id", "content": b"old"}
    for year in (2024, 2025):
        drive["objects"][drive["folder"] + f"/source-{year}0101-000000.tar.gz.age"] = {"id": f"keep-{year}", "content": b"keep"}
    drive["fail_retention"] = True
    result = replicate(drive)
    assert result["status"] == "verified"
    assert result["retention_status"] == "failed"
    assert result["location"] == "gdrive://" + result["artifacts"][0]["provider_id"]


@pytest.mark.parametrize("pending_status", ["pending", "failed"])
@pytest.mark.parametrize("pending_layout", ["whole", "parts"])
@pytest.mark.parametrize("permanent", [False, True])
def test_retention_preserves_manifest_backlog_without_displacing_three_completed_points(drive, pending_status, pending_layout, permanent):
    from app.tasks.backup_native_offsite import OFFSITE_MANIFEST_NAME

    if permanent:
        drive["env"].update(BACKUP_OFFSITE_RCLONE_PERMANENT_EXPIRY="true", BACKUP_OFFSITE_RCLONE_ROOT_ID="root-id")
    stable = [f"source-{year}0101-000000.tar.gz.age" for year in range(2018, 2022)]
    pending = "source-20260101-000000.tar.gz.age"
    incomplete = "source-20260201-000000.tar.gz.age"
    pending_names = [pending] if pending_layout == "whole" else [pending + ".parts.json", pending + ".part000001"]
    names = [stable[0], stable[1] + ".parts.json", stable[1] + ".part000001", stable[2], stable[3],
             *pending_names, incomplete + ".part000001"]
    for index, name in enumerate(names):
        drive["objects"][drive["folder"] + "/" + name] = {"id": f"seed-{index}", "content": b"retained"}
    manifest = drive["archive"].parent / OFFSITE_MANIFEST_NAME
    manifest.write_text(json.dumps({"version": 1, "archives": [
        {"archive_name": pending, "status": pending_status},
        {"archive_name": incomplete, "status": pending_status},
        {"archive_name": drive["archive"].name, "status": "failed"},
    ]}))
    result = replicate(drive, retry=True)
    assert result["status"] == "verified"
    assert result["retention_deleted"] == 3
    remaining = {path.rsplit("/", 1)[-1] for path in drive["objects"]}
    assert {stable[2], stable[3], drive["archive"].name, *pending_names, incomplete + ".part000001"} <= remaining
    assert not {stable[0], stable[1] + ".parts.json", stable[1] + ".part000001"} & remaining
    deleted = [args[1] for args in drive["commands"] if args[0] == "deletefile"]
    assert deleted.index(drive["folder"] + "/" + stable[1] + ".parts.json") < deleted.index(drive["folder"] + "/" + stable[1] + ".part000001")


@pytest.mark.parametrize("corruption", [b"{invalid-json", b'{"archives":{}}', b"\xff\xfe"])
@pytest.mark.parametrize("permanent", [False, True])
def test_corrupt_manifest_blocks_remote_cleanup_across_retries_but_upload_stays_verified(drive, corruption, permanent):
    from app.tasks.backup_native_offsite import OFFSITE_MANIFEST_NAME

    if permanent:
        drive["env"].update(BACKUP_OFFSITE_RCLONE_PERMANENT_EXPIRY="true", BACKUP_OFFSITE_RCLONE_ROOT_ID="root-id")
    for year in range(2017, 2021):
        drive["objects"][drive["folder"] + f"/source-{year}0101-000000.tar.gz.age"] = {"id": f"old-{year}", "content": b"old"}
    manifest = drive["archive"].parent / OFFSITE_MANIFEST_NAME
    manifest.write_bytes(corruption)
    for retry in (False, True):
        result = replicate(drive, retry=retry)
        assert result["status"] == "verified"
        assert result["retention_status"] == "failed"
        assert result["retention_deleted"] is None
        assert "manifest state is unknown" in result["maintenance_error"]
        assert manifest.read_bytes() == corruption
    assert not any(args[0] == "deletefile" for args in drive["commands"])


def test_legacy_verified_manifest_without_status_allows_rotation_and_stays_protected(drive):
    from app.tasks.backup_native_offsite import OFFSITE_MANIFEST_NAME

    legacy_name = "source-20160101-000000.tar.gz.age"
    legacy = {"archive_name": legacy_name, "verified_at": "2016-01-01T00:00:00+00:00",
              "remote_uri": "google-drive://legacy-folder/legacy-id", "local_checksum": "sha256:" + "a" * 64}
    manifest = drive["archive"].parent / OFFSITE_MANIFEST_NAME
    manifest.write_text(json.dumps({"version": 1, "archives": [legacy]}))
    for year in range(2016, 2021):
        drive["objects"][drive["folder"] + f"/source-{year}0101-000000.tar.gz.age"] = {"id": f"old-{year}", "content": b"old"}
    result = replicate(drive)
    assert result["status"] == "verified"
    assert result["retention_status"] == "completed"
    assert result["retention_deleted"] > 0
    assert drive["folder"] + "/" + legacy_name in drive["objects"]
    assert json.loads(manifest.read_text())["archives"][1] == legacy


@pytest.mark.parametrize("fields", [{}, {"status": None}, {"status": "unknown"},
                                   {"verified_at": "yesterday", "remote_uri": "somewhere", "local_checksum": "bad"}])
def test_unknown_legacy_manifest_entry_still_blocks_rotation(tmp_path, fields):
    from app.tasks.backup_native_offsite import OFFSITE_MANIFEST_NAME, _pending_archive_names

    (tmp_path / OFFSITE_MANIFEST_NAME).write_text(json.dumps({"version": 1, "archives": [
        {"archive_name": "source-20160101-000000.tar.gz.age", **fields},
    ]}))
    with pytest.raises(RuntimeError, match="manifest state is unknown"):
        _pending_archive_names(tmp_path)


@pytest.mark.parametrize("permanent", [False, True])
def test_retention_preserves_old_copy_just_verified_on_retry(drive, permanent):
    if permanent:
        drive["env"].update(BACKUP_OFFSITE_RCLONE_PERMANENT_EXPIRY="true", BACKUP_OFFSITE_RCLONE_ROOT_ID="root-id")
    old = drive["archive"].with_name("source-20200101-000000.tar.gz.age")
    drive["archive"].rename(old)
    drive["archive"] = old
    new = drive["folder"] + "/source-20260930-000000.tar.gz.age"
    drive["objects"][new] = {"id": "new-id", "content": b"newest"}
    result = replicate(drive, retry=True)
    assert result["status"] == "verified"
    assert result["retention_deleted"] == 0
    assert drive["folder"] + "/" + old.name in drive["objects"]


@pytest.mark.parametrize("settings", [
    {"BACKUP_OFFSITE_RCLONE_PERMANENT_EXPIRY": "true"},
    {"BACKUP_OFFSITE_RCLONE_PERMANENT_EXPIRY": "yes", "BACKUP_OFFSITE_RCLONE_ROOT_ID": "root-id"},
    {"BACKUP_OFFSITE_RCLONE_PERMANENT_EXPIRY": "true", "BACKUP_OFFSITE_RCLONE_ROOT_ID": "different-id"},
])
def test_permanent_expiry_refuses_missing_invalid_or_changed_root_before_mutation(drive, settings):
    drive["env"].update(settings)
    assert replicate(drive)["status"] == "failed"
    assert not any(args[0] in {"mkdir", "copyto", "deletefile"} for args in drive["commands"])


@pytest.mark.parametrize("folder", ["summitflow-drive:Other/source", "summitflow-drive:Canonical", "summitflow-drive:Canonical/../other", "summitflow-drive:Canonical/source/nested"])
def test_permanent_removal_refuses_outside_root_or_non_source_folder(drive, folder):
    from app.tasks.backup_native_rclone import NativeRcloneProvider

    drive["env"].update(BACKUP_OFFSITE_RCLONE_PERMANENT_EXPIRY="true", BACKUP_OFFSITE_RCLONE_ROOT_ID="root-id")
    with pytest.raises(RuntimeError, match="outside the approved"):
        NativeRcloneProvider(drive["env"]).remove(folder, {"Name": "old.tar.gz.age", "ID": "object-id"}, permanent=True)
    assert not drive["commands"]


def test_permanent_expiry_does_not_make_corrupt_upload_repair_permanent(drive):
    drive["env"].update(BACKUP_OFFSITE_RCLONE_PERMANENT_EXPIRY="true", BACKUP_OFFSITE_RCLONE_ROOT_ID="root-id")
    assert replicate(drive)["status"] == "verified"
    target = drive["folder"] + "/" + drive["archive"].name
    drive["objects"][target]["content"] = b"corrupt"
    drive["commands"].clear()
    assert replicate(drive, retry=True)["status"] == "verified"
    removals = [args for args in drive["commands"] if args[0] == "deletefile"]
    assert len(removals) == 1 and removals[0][2:] == ["--drive-use-trash=true"]


def test_permanent_deletion_rechecks_root_identity_at_time_of_removal(drive):
    from app.tasks.backup_native_rclone import NativeRcloneProvider

    drive["env"].update(BACKUP_OFFSITE_RCLONE_PERMANENT_EXPIRY="true", BACKUP_OFFSITE_RCLONE_ROOT_ID="root-id")
    provider = NativeRcloneProvider(drive["env"])
    assert provider.probe()["provider_id"] == "root-id"
    drive["directories"][drive["root"]] = "new-unapproved-id"
    with pytest.raises(RuntimeError, match="approved identity"):
        provider.remove(drive["folder"], {"Name": "source-20200101-000000.tar.gz.age", "ID": "old-id"}, permanent=True)
    assert not any(args[0] == "deletefile" for args in drive["commands"])


def test_retention_does_not_delete_without_complete_recovery_point(drive):
    from app.tasks.backup_native_offsite import _ARCHIVE_TIMESTAMP
    from app.tasks.backup_native_rclone import NativeRcloneProvider

    orphan = drive["folder"] + "/source-20200101-000000.tar.gz.age.part000001"
    drive["objects"][orphan] = {"id": "orphan-id", "content": b"incomplete"}
    provider = NativeRcloneProvider(drive["env"])
    assert provider.retention(drive["folder"], 14, "gdrive://other-id", _ARCHIVE_TIMESTAMP) == []
    assert orphan in drive["objects"]


def test_probe_reads_metadata_only(drive):
    from app.tasks.backup_native_rclone import probe_rclone_destination

    assert probe_rclone_destination(drive["env"]) == {
        "reachable": True, "provider_id": "root-id", "remote_path": drive["root"],
    }
    assert drive["commands"] == [["lsjson", "summitflow-drive:", "--dirs-only"]]


def test_directory_virtual_root_stat_without_id_does_not_prevent_probe_or_upload(drive):
    from app.tasks.backup_native_rclone import NativeRcloneProvider

    provider = NativeRcloneProvider(drive["env"])
    assert provider._json("lsjson", drive["root"], "--stat") == {
        "Path": "", "Name": "", "IsDir": True, "Size": -1,
    }
    drive["commands"].clear()
    assert provider.probe()["provider_id"] == "root-id"
    assert replicate(drive)["status"] == "verified"
    directory_stats = [args for args in drive["commands"] if args[0] == "lsjson"
                       and args[1] in drive["directories"] and "--stat" in args]
    assert directory_stats == []


@pytest.mark.parametrize("failure", ["missing", "duplicate"])
def test_missing_or_ambiguous_destination_fails_before_mutation(drive, failure):
    if failure == "missing":
        del drive["directories"][drive["root"]]
    else:
        drive["duplicate_root"] = True
    assert replicate(drive)["status"] == "failed"
    assert not any(args[0] in {"mkdir", "copyto", "deletefile"} for args in drive["commands"])


def test_existing_source_directory_is_revalidated_by_fresh_parent_listing(drive):
    drive["directories"][drive["folder"]] = "original-source-id"
    drive["change_source_folder_id"] = True
    result = replicate(drive)
    assert result["status"] == "failed"
    assert "source folder identity changed" in result["error"]
    assert not any(args[0] in {"mkdir", "copyto", "deletefile"} for args in drive["commands"])


def test_nested_destination_is_resolved_by_unique_exact_parent_entries(drive):
    from app.tasks.backup_native_rclone import probe_rclone_destination

    drive["directories"]["summitflow-drive:Parent"] = "parent-id"
    drive["directories"]["summitflow-drive:Parent/Canonical"] = "nested-root-id"
    drive["env"]["BACKUP_OFFSITE_RCLONE_REMOTE"] = "summitflow-drive:Parent/Canonical"
    assert probe_rclone_destination(drive["env"])["provider_id"] == "nested-root-id"
    assert drive["commands"] == [["lsjson", "summitflow-drive:", "--dirs-only"],
                                 ["lsjson", "summitflow-drive:Parent", "--dirs-only"]]


@pytest.mark.parametrize("unsafe", ["public_file", "public_directory", "symlink", "non_drive", "root_remote"])
def test_unsafe_configuration_fails_before_remote_operations(drive, tmp_path, unsafe):
    config = Path(drive["env"]["BACKUP_OFFSITE_RCLONE_CONFIG"])
    if unsafe == "public_file":
        config.chmod(0o644)
    elif unsafe == "public_directory":
        config.parent.chmod(0o755)
    elif unsafe == "symlink":
        link = config.parent / "linked.conf"
        link.symlink_to(config)
        drive["env"]["BACKUP_OFFSITE_RCLONE_CONFIG"] = str(link)
    elif unsafe == "non_drive":
        config.write_text("[summitflow-drive]\ntype = local\n")
    else:
        drive["env"]["BACKUP_OFFSITE_RCLONE_REMOTE"] = "summitflow-drive:"
    assert replicate(drive)["status"] == "failed"
    assert not drive["commands"]
