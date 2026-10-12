from __future__ import annotations

from pathlib import Path

import pytest

from cli.lib.architecture_check import run_architecture_check


@pytest.mark.parametrize(("code", "expected"), [
    ("import subprocess\nsubprocess.run(['true'])\n", "raw subprocess.run"),
    ("import asyncio\nasync def f():\n    return await asyncio.create_subprocess_exec('true')\n",
     "bad.py:3 raw asyncio.create_subprocess_exec"),
    ("from app.utils import safe_subprocess\nsafe_subprocess.run(['true'])\n", None),
])
def test_architecture_check_reports_raw_subprocess(tmp_path: Path, capsys, code: str, expected: str | None) -> None:
    target = tmp_path / "backend" / "app" / "services" / "bad.py"
    target.parent.mkdir(parents=True)
    target.write_text(code, encoding="utf-8")

    assert run_architecture_check(tmp_path, None) == (1 if expected else 0)

    output = capsys.readouterr().out
    if expected:
        assert "ARCH:FAIL:1" in output and expected in output
    else:
        assert "ARCH:OK:architecture" in output


def test_architecture_check_skips_when_changed_files_are_irrelevant(tmp_path: Path, capsys) -> None:
    assert run_architecture_check(tmp_path, ["README.md"]) == 0

    output = capsys.readouterr().out
    assert "ARCH:SKIP:architecture:no_changed_paths" in output


def test_shared_heavy_admission_keeps_raw_processes_behind_canonical_boundary() -> None:
    root = Path(__file__).resolve().parents[3]
    assert run_architecture_check(root, ["backend/app/utils/heavy_work.py"]) == 0
