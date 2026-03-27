"""Tests for system resource monitoring helpers."""

from __future__ import annotations

from types import SimpleNamespace

from app.services import resource_monitor


def _usage(total_gb: int, used_gb: int) -> SimpleNamespace:
    total = total_gb * 1024**3
    used = used_gb * 1024**3
    return SimpleNamespace(total=total, used=used, free=total - used)


def test_get_disk_usages_includes_workspace_mount_when_present(mocker) -> None:
    usages = {
        "/": _usage(total_gb=100, used_gb=45),
        "/srv/workspaces": _usage(total_gb=200, used_gb=8),
    }
    mocker.patch(
        "app.services.resource_monitor.os.path.ismount",
        side_effect=lambda path: path == "/srv/workspaces",
    )
    mocker.patch(
        "app.services.resource_monitor.shutil.disk_usage",
        side_effect=lambda path: usages[path],
    )

    disks = resource_monitor.get_disk_usages()

    assert [disk["mount_path"] for disk in disks] == ["/", "/srv/workspaces"]
    assert disks[0]["label"] == "Root"
    assert disks[1]["label"] == "Workspaces"
    assert disks[1]["percent_used"] == 4.0


def test_get_disk_usages_skips_workspace_when_not_mounted(mocker) -> None:
    mocker.patch("app.services.resource_monitor.os.path.ismount", return_value=False)
    mocker.patch(
        "app.services.resource_monitor.shutil.disk_usage",
        return_value=_usage(total_gb=100, used_gb=48),
    )

    disks = resource_monitor.get_disk_usages()

    assert len(disks) == 1
    assert disks[0]["mount_path"] == "/"
