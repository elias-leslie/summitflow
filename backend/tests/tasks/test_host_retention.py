"""Tests for host artifact retention."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pytest


@pytest.fixture(autouse=True)
def _isolate_scratch(mocker) -> Any:
    """Host retention must never touch the live /srv/scratch or its stamp in tests."""
    mocker.patch("app.tasks.host_retention.SCRATCH_ROOT", Path("/nonexistent-test-scratch"))
    return mocker.patch("app.tasks.host_retention.weekly_scratch_retention",
                        return_value={"status": "skipped", "reason": "weekly-cadence"})


def test_host_retention_policy_defaults_keep_docker_cache_minimal() -> None:
    from app.tasks.host_retention import HostRetentionPolicy

    policy = HostRetentionPolicy()

    assert policy.builder_cache_target_gb == 2
    assert policy.builder_cache_pressure_target_gb == 1
    assert policy.image_max_age_hours == 0
    assert policy.image_pressure_max_age_hours == 0


def test_scratch_pressure_runs_retention_now_without_shortening_its_age(monkeypatch) -> None:
    """Pressure must not delete idle owner work in scratch sooner than the weekly pass would."""
    from app.tasks.host_retention import HostRetentionPolicy

    for name in ("SF_HOST_RETENTION_SCRATCH_PRESSURE_MAX_AGE_HOURS", "SF_HOST_RETENTION_SCRATCH_REVIEW_MAX_AGE_HOURS"):
        monkeypatch.delenv(name, raising=False)
    for policy in (HostRetentionPolicy(), HostRetentionPolicy.from_env()):
        assert policy.scratch_pressure_max_age_hours == policy.scratch_review_max_age_hours == 7 * 24


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

    result = cast(dict[str, Any], cleanup_host_artifacts(home_dir=home_dir, tmp_dir=tmp_dir, project_roots=[]))

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


def test_playwright_retention_keeps_builds_pinned_by_installed_packages(tmp_path: Path) -> None:
    """Regression: age-pruning removed browser builds a live Playwright install still pins."""
    import json

    from app.tasks._retention_fs import cleanup_old_children, playwright_required_children

    root = tmp_path / "ms-playwright"
    package = tmp_path / "project" / "playwright-core"
    gone_package = tmp_path / "removed" / "playwright-core"
    package.mkdir(parents=True)
    (package / "browsers.json").write_text(
        json.dumps({"browsers": [
            {"name": "chromium", "revision": "1208"},
            {"name": "chromium-headless-shell", "revision": "1208"},
            {"name": "ffmpeg", "revision": "1011"},
        ]}),
        encoding="utf-8",
    )
    (root / ".links").mkdir(parents=True)
    (root / ".links" / "live").write_text(str(package), encoding="utf-8")
    (root / ".links" / "stale").write_text(str(gone_package), encoding="utf-8")
    names = ("chromium-1208", "chromium_headless_shell-1208", "ffmpeg-1011", "chromium-1100")
    old_time = (datetime.now(UTC) - timedelta(days=30)).timestamp()
    for name in (*names, ".links"):
        (root / name).mkdir(exist_ok=True)
        os.utime(root / name, (old_time, old_time))

    result = cleanup_old_children(
        root, max_age_hours=24, now=datetime.now(UTC), protected=playwright_required_children(root),
    )

    assert result["deleted"] == [str(root / "chromium-1100")]
    assert sorted(child.name for child in root.iterdir()) == sorted([".links", *names[:3]])


def test_playwright_retention_protects_everything_when_registry_unreadable(tmp_path: Path) -> None:
    from app.tasks._retention_fs import playwright_required_children

    root = tmp_path / "ms-playwright"
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "browsers.json").write_text("not json", encoding="utf-8")
    (root / ".links").mkdir(parents=True)
    (root / ".links" / "broken").write_text(str(package), encoding="utf-8")
    (root / "chromium-1208").mkdir()

    assert playwright_required_children(root) == frozenset({".links", "chromium-1208"})



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
    mocker.patch(
        "app.tasks.host_retention._run_command",
        return_value=type("Proc", (), {"returncode": 1, "stdout": "", "stderr": "fixture unavailable"})(),
    )

    result = cast(dict[str, Any], cleanup_host_artifacts(home_dir=home_dir, tmp_dir=tmp_dir, project_roots=[]))

    assert result["status"] == "success"
    assert result["temp_backups"]["deleted_paths"] == 2
    assert result["hermes_checkpoints"]["deleted_paths"] == 2
    assert not tmp_backup.exists()
    assert not release_backup.exists()
    assert not tmp_checkpoint.exists()
    assert not internal_checkpoint.exists()
    assert keep_checkpoint.exists()


def test_veeam_retention_preserves_old_incremental_parents(mocker, tmp_path: Path) -> None:
    from app.tasks.host_retention import HostRetentionPolicy, cleanup_stale_veeam_snapshots

    parent = tmp_path / ".veeam_snapshots" / "old-parent"
    parent.mkdir(parents=True)
    command = mocker.patch("app.tasks.host_retention._run_command")
    result = cleanup_stale_veeam_snapshots(
        policy=HostRetentionPolicy(), now=datetime.now(UTC), mount_point=tmp_path,
    )
    assert result["reason"] == "vendor-managed-incremental-parents"
    assert result["deleted"] == []
    assert parent.is_dir()
    command.assert_not_called()


def test_scratch_filesystem_pressure_reclaims_now_while_root_stays_normal(mocker, tmp_path: Path) -> None:
    """Regression: pressure only looked at '/', so a nearly full scratch filesystem waited for the weekly pass."""
    from app.tasks import host_retention

    scratch = tmp_path / "scratch"
    scratch.mkdir()
    mocker.patch.object(host_retention, "SCRATCH_ROOT", scratch)
    mocker.patch.object(host_retention, "filesystem_source", lambda path: "p8" if path == scratch else "p7")
    usage = {"/": (100 * 1024**3, 40 * 1024**3, 60 * 1024**3), str(scratch): (100 * 1024**3, 89 * 1024**3, 11 * 1024**3)}
    mocker.patch.object(host_retention.shutil, "disk_usage", lambda path: usage[str(path)])
    mocker.patch.object(host_retention, "_docker_available", return_value=False)
    reclaim = mocker.patch.object(host_retention, "reclaim_filesystem", return_value={"steps": [
        {"step": "uv_cache", "status": "success"},
        {"step": "scratch", "status": "success", "deleted_paths": ["/srv/scratch/old"], "bytes": 5}]})
    weekly = host_retention.weekly_scratch_retention

    result = cast(dict[str, Any], host_retention.cleanup_host_artifacts(
        home_dir=tmp_path / "home", tmp_dir=tmp_path, project_roots=[]))

    assert reclaim.call_args.args == (scratch,)
    assert not weekly.called  # type: ignore[attr-defined]
    assert result["pressure_mode"] is True and result["pressure_filesystems"] == [str(scratch)]
    assert result["scratch"]["trigger"] == "pressure" and result["scratch"]["deleted_paths"] == ["/srv/scratch/old"]


def test_reclaim_stops_at_target_and_keeps_cache_roots(mocker, tmp_path: Path) -> None:
    from app.tasks import _retention_reclaim as reclaim

    cache = tmp_path / "cache"
    hub = cache / "huggingface-hub"
    old_repo, used_repo = hub / "models--old--x", hub / "models--new--y"
    for repo in (old_repo, used_repo):
        (repo / "blobs").mkdir(parents=True)
        (repo / "blobs" / "b").write_text("weights")
    old = (datetime.now(UTC) - timedelta(days=40)).timestamp()
    (cache / "uv").mkdir()
    mocker.patch.multiple(reclaim, UV_CACHE=cache / "uv", HF_HUB=hub, SCRATCH_ROOT=tmp_path, TMP_ROOT=tmp_path / "tmp")
    (tmp_path / "tmp").mkdir()
    mocker.patch.object(reclaim, "filesystem_source", lambda path: "p8")
    mocker.patch.object(reclaim.shutil, "which", lambda name: f"/usr/bin/{name}")
    free = {"bytes": 10}
    mocker.patch.object(reclaim, "free_bytes", lambda path: free["bytes"])
    calls: list[tuple[list[str], dict[str, str] | None]] = []

    def run(args: list[str], *, env: dict[str, str] | None = None, timeout: int = 0):
        calls.append((args, env))
        if args[:3] in (["go", "env", "GOCACHE"], ["docker", "info", "--format"]):
            return type("Proc", (), {"returncode": 1, "stdout": "", "stderr": ""})()
        if args[:3] == ["pnpm", "store", "path"]:
            return type("Proc", (), {"returncode": 0, "stdout": f"{cache}\n", "stderr": ""})()
        if args[:3] == ["pnpm", "store", "prune"]:
            free["bytes"] = 100
        return type("Proc", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    receipt = reclaim.reclaim_filesystem(tmp_path, target_free_bytes=50, run=run)
    assert [step["step"] for step in receipt["steps"]] == ["agent_tmp", "go_cache", "uv_cache", "pnpm_store"]
    assert receipt["steps"][1]["reason"] == "not on this filesystem"  # no Go cache reported
    assert receipt["target_met"] and receipt["steps"][3]["freed_bytes"] == 90
    assert (["uv", "cache", "prune"], {"UV_CACHE_DIR": str(cache / "uv")}) in calls
    assert old_repo.exists()  # target met before the Hugging Face step

    # Scratch is mounted noatime; age is the newest mtime/ctime, which utime cannot backdate.
    mocker.patch.object(reclaim, "_tree_stats", lambda path, max_entries: (old if path == old_repo else datetime.now(UTC).timestamp(), 7, 3))
    pruned = reclaim.prune_unused_hf_repos(hub=hub, now=datetime.now(UTC), proc_root=tmp_path / "no-proc")
    assert pruned["deleted_paths"] == [str(old_repo)]
    assert hub.is_dir() and used_repo.exists() and not old_repo.exists()


def test_hf_prune_keeps_repos_holding_a_mount(mocker, tmp_path: Path) -> None:
    """Regression: an old hub repo with a bind mount inside was removed with rmtree, mount data included."""
    from app.tasks import _retention_reclaim as reclaim

    hub = tmp_path / "hub"
    mounted_repo, plain_repo = hub / "models--mounted--x", hub / "models--plain--y"
    for repo in (mounted_repo, plain_repo):
        (repo / "blobs").mkdir(parents=True)
        (repo / "blobs" / "b").write_text("weights")
    table = tmp_path / "mountinfo"
    table.write_text("22 1 0:21 / / rw - btrfs /dev/p7 rw\n"
                     f"90 22 0:21 /data {os.path.realpath(mounted_repo / 'blobs')} rw - btrfs /dev/p8 rw\n")
    old = (datetime.now(UTC) - timedelta(days=40)).timestamp()
    mocker.patch.object(reclaim, "_tree_stats", lambda path, max_entries: (old, 7, 3))
    pruned = reclaim.prune_unused_hf_repos(hub=hub, now=datetime.now(UTC), proc_root=tmp_path / "no-proc", mountinfo=table)
    assert pruned["deleted_paths"] == [str(plain_repo)] and not plain_repo.exists()
    assert (mounted_repo / "blobs" / "b").exists()
    assert pruned["kept"][0]["reason"].startswith("mount point ")
