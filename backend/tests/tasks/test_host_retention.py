"""Tests for host artifact retention."""

from __future__ import annotations

import os
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast


def test_host_retention_policy_defaults_keep_docker_cache_minimal() -> None:
    from app.tasks.host_retention import HostRetentionPolicy

    policy = HostRetentionPolicy()

    assert policy.builder_cache_target_gb == 2
    assert policy.builder_cache_pressure_target_gb == 1
    assert policy.image_max_age_hours == 0
    assert policy.image_pressure_max_age_hours == 0


def test_prune_images_without_age_grace_prunes_all_unused_images(mocker) -> None:
    from app.tasks.host_retention import HostRetentionPolicy, _prune_images

    run_command = mocker.patch(
        "app.tasks.host_retention._run_command",
        return_value=type("Proc", (), {"returncode": 0, "stdout": "ok", "stderr": ""})(),
    )

    result = _prune_images(policy=HostRetentionPolicy(image_max_age_hours=0), pressure_mode=False)

    assert run_command.call_args.args[0] == [
        "docker",
        "image",
        "prune",
        "--force",
        "--all",
    ]
    assert result["status"] == "success"
    assert result["max_age_hours"] == 0


def test_prune_builder_cache_uses_supported_keep_storage_flag(mocker) -> None:
    from app.tasks._retention_docker import prune_builder_cache
    from app.tasks.host_retention import HostRetentionPolicy

    run_command = mocker.Mock(
        return_value=type("Proc", (), {"returncode": 0, "stdout": "ok", "stderr": ""})()
    )

    result = prune_builder_cache(
        policy=HostRetentionPolicy(builder_cache_target_gb=2),
        pressure_mode=False,
        run=run_command,
    )

    assert run_command.call_args.args[0] == [
        "docker",
        "builder",
        "prune",
        "--force",
        "--all",
        "--keep-storage",
        "2gb",
    ]
    assert result["status"] == "success"


def test_cleanup_host_artifacts_prunes_rebuildable_data_and_reports_review_candidates(
    mocker,
    tmp_path: Path,
) -> None:
    from app.tasks.host_retention import cleanup_host_artifacts

    home_dir = tmp_path / "home"
    tmp_dir = tmp_path / "tmp"
    tmp_dir.mkdir()
    npx_old = home_dir / ".npm" / "_npx" / "old-run"
    playwright_old = home_dir / ".cache" / "ms-playwright" / "chromium-old"
    legacy_root = home_dir / "_legacy-project-roots" / "2026-03-01-btrfs-cutover"
    npx_old.mkdir(parents=True)
    playwright_old.mkdir(parents=True)
    legacy_root.mkdir(parents=True)
    (npx_old / "artifact.txt").write_text("npx temp data", encoding="utf-8")
    (playwright_old / "browser.bin").write_text("playwright cache", encoding="utf-8")
    (legacy_root / "README.txt").write_text("legacy snapshot", encoding="utf-8")

    old_time = (datetime.now(UTC) - timedelta(days=20)).timestamp()
    for path in (
        npx_old,
        npx_old / "artifact.txt",
        playwright_old,
        playwright_old / "browser.bin",
        legacy_root,
        legacy_root / "README.txt",
    ):
        os.utime(path, (old_time, old_time))

    mocker.patch(
        "app.tasks.host_retention.shutil.disk_usage",
        side_effect=[
            (100 * 1024**3, 60 * 1024**3, 40 * 1024**3),
            (100 * 1024**3, 55 * 1024**3, 45 * 1024**3),
        ],
    )
    mocker.patch("app.tasks.host_retention.shutil.which", return_value="/usr/bin/docker")

    def _run_command(args: list[str], *, timeout: int = 0, cwd: str | None = None):
        _ = timeout, cwd
        anon_name = "a" * 64
        if args[:4] == ["docker", "volume", "ls", "-q"]:
            return type(
                "Proc",
                (),
                {"returncode": 0, "stdout": f"{anon_name}\nnot-anon\n", "stderr": ""},
            )()
        if args[:3] == ["docker", "volume", "inspect"]:
            name = args[-1]
            if name == anon_name:
                stdout = f'[{{"Name":"{anon_name}","CreatedAt":"2026-03-01T00:00:00Z"}}]'
            else:
                stdout = (
                    '[{"Name":"not-anon","CreatedAt":"2026-03-01T00:00:00Z"}]'
                )
            return type("Proc", (), {"returncode": 0, "stdout": stdout, "stderr": ""})()
        return type("Proc", (), {"returncode": 0, "stdout": "ok", "stderr": ""})()

    mocker.patch("app.tasks.host_retention._run_command", side_effect=_run_command)

    result = cast(dict[str, Any], cleanup_host_artifacts(home_dir=home_dir, tmp_dir=tmp_dir))

    assert result["status"] == "success"
    assert result["pressure_mode"] is False
    assert result["bytes_reclaimed"] == 5 * 1024**3
    assert result["items_deleted"] >= 3
    assert result["tool_caches"]["deleted_paths"] == 2
    assert len(result["docker_anonymous_volumes"]["deleted"]) == 1
    assert not npx_old.exists()
    assert not playwright_old.exists()
    assert result["review_candidates"][0]["reason"] == "legacy_project_root"
    assert result["review_candidates"][0]["path"].endswith("2026-03-01-btrfs-cutover")



def test_cleanup_host_artifacts_prunes_stale_tmp_backups_and_hermes_checkpoints(
    mocker,
    tmp_path: Path,
) -> None:
    from app.tasks.host_retention import cleanup_host_artifacts

    home_dir = tmp_path / "home"
    hermes_dir = home_dir / ".hermes"
    checkpoints_dir = hermes_dir / "checkpoints"
    tmp_dir = tmp_path / "tmp"

    tmp_backup = tmp_dir / "agent-hub-backup-123456"
    tmp_backup.mkdir(parents=True)
    (tmp_backup / "agent-hub.tar.gz").write_text("backup", encoding="utf-8")

    release_backup = tmp_dir / "terminal-release-backup"
    release_backup.mkdir(parents=True)
    (release_backup / "terminal.tar").write_text("release", encoding="utf-8")

    tmp_checkpoint = checkpoints_dir / "tmp-shadow"
    (tmp_checkpoint / "objects" / "pack").mkdir(parents=True)
    (tmp_checkpoint / "HERMES_WORKDIR").write_text("/tmp\n", encoding="utf-8")
    (tmp_checkpoint / "objects" / "pack" / "tmp_pack_dead").write_text("stale tmp checkpoint", encoding="utf-8")

    internal_checkpoint = checkpoints_dir / "internal-shadow"
    (internal_checkpoint / "objects" / "pack").mkdir(parents=True)
    (internal_checkpoint / "HERMES_WORKDIR").write_text(str(hermes_dir), encoding="utf-8")
    (internal_checkpoint / "objects" / "pack" / "pack-self").write_text("recursive hermes checkpoint", encoding="utf-8")

    keep_checkpoint = checkpoints_dir / "keep-shadow"
    (keep_checkpoint / "objects").mkdir(parents=True)
    (keep_checkpoint / "HERMES_WORKDIR").write_text("/srv/workspaces/projects/summitflow\n", encoding="utf-8")
    (keep_checkpoint / "objects" / "keep").write_text("keep", encoding="utf-8")

    old_time = (datetime.now(UTC) - timedelta(days=10)).timestamp()
    for path in (
        tmp_backup,
        tmp_backup / "agent-hub.tar.gz",
        release_backup,
        release_backup / "terminal.tar",
        tmp_checkpoint,
        tmp_checkpoint / "HERMES_WORKDIR",
        tmp_checkpoint / "objects",
        tmp_checkpoint / "objects" / "pack",
        tmp_checkpoint / "objects" / "pack" / "tmp_pack_dead",
        internal_checkpoint,
        internal_checkpoint / "HERMES_WORKDIR",
        internal_checkpoint / "objects",
        internal_checkpoint / "objects" / "pack",
        internal_checkpoint / "objects" / "pack" / "pack-self",
    ):
        os.utime(path, (old_time, old_time))

    mocker.patch(
        "app.tasks.host_retention.shutil.disk_usage",
        side_effect=[
            (100 * 1024**3, 90 * 1024**3, 10 * 1024**3),
            (100 * 1024**3, 84 * 1024**3, 16 * 1024**3),
        ],
    )
    mocker.patch("app.tasks.host_retention.shutil.which", return_value=None)

    result = cast(dict[str, Any], cleanup_host_artifacts(home_dir=home_dir, tmp_dir=tmp_dir))

    assert result["status"] == "success"
    assert result["temp_backups"]["deleted_paths"] == 2
    assert result["hermes_checkpoints"]["deleted_paths"] == 2
    assert not tmp_backup.exists()
    assert not release_backup.exists()
    assert not tmp_checkpoint.exists()
    assert not internal_checkpoint.exists()
    assert keep_checkpoint.exists()


def test_cleanup_stale_veeam_snapshots_deletes_old_btrfs_subvolumes(tmp_path: Path) -> None:
    from app.tasks.host_retention import HostRetentionPolicy, cleanup_stale_veeam_snapshots

    now = datetime(2026, 6, 23, 12, tzinfo=UTC)
    snapshot = tmp_path / ".veeam_snapshots" / "{stale}"
    child = snapshot / "259_@docker"
    child.mkdir(parents=True)
    old_time = (now - timedelta(hours=8)).timestamp()
    os.utime(snapshot, (old_time, old_time))
    os.utime(child, (old_time, old_time))
    calls: list[list[str]] = []

    def run(args: list[str], *, timeout: int = 0, cwd: str | None = None):
        _ = timeout, cwd
        calls.append(args)
        if args[:4] == ["sudo", "-n", "veeamconfig", "session"]:
            return type("Proc", (), {"returncode": 0, "stdout": "State\nSuccess\n", "stderr": ""})()
        if args[:5] == ["sudo", "-n", "btrfs", "subvolume", "list"]:
            return type(
                "Proc",
                (),
                {
                    "returncode": 0,
                    "stdout": "ID 1 gen 1 top level 5 path .veeam_snapshots/{stale}/259_@docker\n",
                    "stderr": "",
                },
            )()
        if args[:5] == ["sudo", "-n", "btrfs", "subvolume", "delete"]:
            shutil.rmtree(args[-1])
        if args[:3] == ["sudo", "-n", "rmdir"]:
            Path(args[-1]).rmdir()
        return type("Proc", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    result = cleanup_stale_veeam_snapshots(
        policy=HostRetentionPolicy(veeam_snapshot_max_age_hours=6),
        now=now,
        run=run,
        mount_point=tmp_path,
    )

    assert result["status"] == "success"
    assert result["deleted"] == [str(snapshot)]
    assert not snapshot.exists()
    assert any(call[:5] == ["sudo", "-n", "btrfs", "subvolume", "sync"] for call in calls)


def test_cleanup_stale_veeam_snapshots_skips_active_session(tmp_path: Path) -> None:
    from app.tasks.host_retention import HostRetentionPolicy, cleanup_stale_veeam_snapshots

    calls: list[list[str]] = []

    def run(args: list[str], *, timeout: int = 0, cwd: str | None = None):
        _ = timeout, cwd
        calls.append(args)
        return type("Proc", (), {"returncode": 0, "stdout": "Job  Type  ID  Running\n", "stderr": ""})()

    result = cleanup_stale_veeam_snapshots(
        policy=HostRetentionPolicy(),
        now=datetime(2026, 6, 23, 12, tzinfo=UTC),
        run=run,
        mount_point=tmp_path,
    )

    assert result["status"] == "skipped"
    assert result["reason"] == "veeam_session_active"
    assert len(calls) == 1
