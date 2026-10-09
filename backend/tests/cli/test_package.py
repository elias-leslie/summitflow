import json
import os
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

from cli.commands import package


def _identity(**packaging):
    return {"packaging": {"command": ["true"], "artifacts": ["dist/*.bin"], **packaging}}


@pytest.mark.parametrize("packaging, message", [
    ({"command": []}, "command"),
    ({"artifacts": []}, "artifacts"),
    ({"artifacts": ["../out/*.bin"]}, "relative"),
    ({"artifacts": ["build/*.bin"]}, "inside packaging.output_dir"),
    ({"output_dir": "/tmp"}, "relative"),
    ({"work_class": "heavy2"}, "work_class"),
    ({"timeout_seconds": 5}, "timeout_seconds"),
])
def test_packaging_spec_rejects_unsafe_declarations(packaging, message):
    with pytest.raises(package.PackagingError, match=message):
        package.packaging_spec(_identity(**packaging))


def test_packaging_spec_requires_a_block():
    with pytest.raises(package.PackagingError, match="no packaging block"):
        package.packaging_spec({"project": {}})


def test_collect_artifacts_requires_fresh_matches_inside_output(tmp_path):
    spec = package.packaging_spec(_identity())
    (tmp_path / "dist").mkdir()
    stale = tmp_path / "dist" / "old.bin"
    stale.write_bytes(b"old")
    os.utime(stale, (1_000_000, 1_000_000))
    started = 2_000_000.0
    with pytest.raises(package.PackagingError, match=r"dist/\*\.bin"):
        package.collect_artifacts(tmp_path, spec, started=started)
    fresh = tmp_path / "dist" / "app.bin"
    fresh.write_bytes(b"payload")
    artifacts = package.collect_artifacts(tmp_path, spec, started=started)
    assert [item["path"] for item in artifacts] == ["dist/app.bin"]
    assert artifacts[0]["size"] == 7 and len(artifacts[0]["sha256"]) == 64


def test_run_package_records_receipt_bound_to_head(monkeypatch, tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "-c", "user.name=t", "-c", "user.email=t@example.invalid",
                    "commit", "-q", "--allow-empty", "-m", "fixture"], check=True)
    script = "import pathlib; pathlib.Path('dist').mkdir(exist_ok=True); pathlib.Path('dist/app.bin').write_bytes(b'x')"
    identity = _identity(command=[sys.executable, "-c", script], work_class="light")
    monkeypatch.setattr(package, "get_project_identity_root", lambda _: str(tmp_path))
    monkeypatch.setattr(package, "get_project_identity", lambda _: identity)
    admitted = []

    class Work:
        def run(self, command, **kwargs):
            return subprocess.run(command, **kwargs)

    @contextmanager
    def admission(label, *, work_class, project):
        admitted.append((label, work_class, project))
        yield Work()

    monkeypatch.setattr(package, "heavy_work", admission)
    code, line = package.run_package("fixture")
    head = subprocess.run(["git", "-C", str(tmp_path), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    assert code == 0 and "state=ok" in line and "artifacts=1" in line
    assert admitted == [("package fixture", "light", "fixture")]
    receipt = json.loads((tmp_path / ".git" / "st" / "package" / f"{head}.json").read_text())
    assert receipt["source_commit"] == head and receipt["artifacts"][0]["path"] == "dist/app.bin"


def test_run_package_reports_command_failure(monkeypatch, tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "-c", "user.name=t", "-c", "user.email=t@example.invalid",
                    "commit", "-q", "--allow-empty", "-m", "fixture"], check=True)
    monkeypatch.setattr(package, "get_project_identity_root", lambda _: str(tmp_path))
    monkeypatch.setattr(package, "get_project_identity", lambda _: _identity(command=[sys.executable, "-c", "raise SystemExit(3)"]))

    @contextmanager
    def admission(label, *, work_class, project):
        yield type("Work", (), {"run": staticmethod(lambda command, **kwargs: subprocess.run(command, **kwargs))})()

    monkeypatch.setattr(package, "heavy_work", admission)
    code, line = package.run_package("fixture")
    assert code == 3 and "state=failed" in line
    assert not (Path(tmp_path) / ".git" / "st" / "package").exists()
