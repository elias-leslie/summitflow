"""Managed launcher adoption must preserve a custom st executable."""

from pathlib import Path

from cli.lib.service_ops import ProjectServices, install_st_monitor_launcher


def _project(root: Path) -> ProjectServices:
    return ProjectServices(
        project_id="summitflow",
        root=root,
        backend_service="summitflow-backend.service",
        frontend_service="summitflow-frontend.service",
        default_workers=("summitflow-host-monitor.service",),
        optional_workers=(),
        backend_port=8001,
        frontend_port=3001,
        backend_dir=root / "backend",
        frontend_dir=root / "frontend",
        health_endpoint="/health",
    )


def test_managed_launcher_replaces_only_expected_link(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    root = tmp_path / "checkout"
    script = root / "scripts" / "st"
    script.parent.mkdir(parents=True)
    script.write_text("#!/bin/sh\nexit 0\n")
    script.chmod(0o755)
    target = tmp_path / "bin" / "st"
    target.parent.mkdir()
    custom = tmp_path / "custom-st"
    custom.write_text("custom")
    target.symlink_to(custom)

    assert install_st_monitor_launcher(_project(root)) == 1
    assert target.resolve() == custom

    target.unlink()
    target.symlink_to(root / "backend" / ".venv" / "bin" / "st")
    assert install_st_monitor_launcher(_project(root)) == 0
    assert target.resolve() == script
    assert install_st_monitor_launcher(_project(root)) == 0
