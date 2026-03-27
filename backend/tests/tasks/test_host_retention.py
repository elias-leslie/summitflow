"""Tests for host artifact retention."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path


def test_cleanup_host_artifacts_prunes_rebuildable_data_and_reports_review_candidates(
    mocker,
    tmp_path: Path,
) -> None:
    from app.tasks.host_retention import cleanup_host_artifacts

    home_dir = tmp_path / "home"
    npx_old = home_dir / ".npm" / "_npx" / "old-run"
    playwright_old = home_dir / ".cache" / "ms-playwright" / "chromium-old"
    legacy_root = home_dir / "_legacy-project-roots" / "2026-03-01-btrfs-cutover"
    npx_old.mkdir(parents=True)
    playwright_old.mkdir(parents=True)
    legacy_root.mkdir(parents=True)
    (npx_old / "artifact.txt").write_text("npx temp data", encoding="utf-8")
    (playwright_old / "browser.bin").write_text("playwright cache", encoding="utf-8")
    (legacy_root / "README.txt").write_text("legacy snapshot", encoding="utf-8")

    old_time = (datetime.now(UTC) - timedelta(days=10)).timestamp()
    for path in (npx_old, playwright_old, legacy_root):
        path.touch()
        (path / next(iter(p.name for p in path.iterdir()))).touch()
        Path(path).chmod(0o755)
    for path in (
        npx_old,
        npx_old / "artifact.txt",
        playwright_old,
        playwright_old / "browser.bin",
        legacy_root,
        legacy_root / "README.txt",
    ):
        import os

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
        if args[:4] == ["docker", "volume", "ls", "-q"]:
            return type("Proc", (), {"returncode": 0, "stdout": "abc123\nnot-anon\n", "stderr": ""})()
        if args[:3] == ["docker", "volume", "inspect"]:
            name = args[-1]
            if name == "abc123":
                stdout = (
                    '[{"Name":"abc123","CreatedAt":"2026-03-01T00:00:00Z"}]'
                )
            else:
                stdout = (
                    '[{"Name":"not-anon","CreatedAt":"2026-03-01T00:00:00Z"}]'
                )
            return type("Proc", (), {"returncode": 0, "stdout": stdout, "stderr": ""})()
        return type("Proc", (), {"returncode": 0, "stdout": "ok", "stderr": ""})()

    mocker.patch("app.tasks.host_retention._run_command", side_effect=_run_command)

    result = cleanup_host_artifacts(home_dir=home_dir)

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
