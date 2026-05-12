from __future__ import annotations

from pathlib import Path

from cli.lib.architecture_check import run_architecture_check


def test_architecture_check_reports_raw_subprocess(tmp_path: Path, capsys) -> None:
    target = tmp_path / "backend" / "app" / "services" / "bad.py"
    target.parent.mkdir(parents=True)
    target.write_text(
        "import subprocess\n"
        "subprocess.run(['true'])\n",
        encoding="utf-8",
    )

    assert run_architecture_check(tmp_path, None) == 1

    output = capsys.readouterr().out
    assert "ARCH:FAIL:1" in output
    assert "raw subprocess.run" in output


def test_architecture_check_skips_when_changed_files_are_irrelevant(tmp_path: Path, capsys) -> None:
    assert run_architecture_check(tmp_path, ["README.md"]) == 0

    output = capsys.readouterr().out
    assert "ARCH:SKIP:architecture:no_changed_paths" in output
