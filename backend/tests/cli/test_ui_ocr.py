"""Tests for `st ui ocr` target resolution.

`ocr` mirrors `st ui shot`: a bare invocation OCRs the focused window, a file
path OCRs the file, and any other argument is resolved as a window id/name.
"""

from __future__ import annotations

import subprocess
from unittest.mock import patch

from typer.testing import CliRunner

from cli.commands import ui as ui_mod
from cli.commands.ui import app as ui_app

runner = CliRunner()


def _proc(stdout: str = "", returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr="")


def _run_side_effect(cmd, **_):
    # import (capture) -> ok; tesseract -> the OCR text
    if cmd and cmd[0] == "tesseract":
        return _proc(stdout="hello from ocr\n")
    return _proc()


def test_ocr_no_target_uses_focused_window():
    with (
        patch.object(ui_mod, "_require", lambda b: b),
        patch.object(ui_mod, "_focused_window", return_value="0x123") as focused,
        patch.object(ui_mod, "_resolve_window") as resolve,
        patch.object(ui_mod, "_run", side_effect=_run_side_effect) as run,
    ):
        result = runner.invoke(ui_app, ["ocr"])

    assert result.exit_code == 0, result.output
    assert "hello from ocr" in result.output
    focused.assert_called_once()
    resolve.assert_not_called()
    # the focused id must flow into the capture command
    import_calls = [c.args[0] for c in run.call_args_list if c.args[0][0] == "import"]
    assert import_calls and "0x123" in import_calls[0]


def test_ocr_named_target_resolves_window():
    with (
        patch.object(ui_mod, "_require", lambda b: b),
        patch.object(ui_mod, "_focused_window") as focused,
        patch.object(ui_mod, "_resolve_window", return_value=456) as resolve,
        patch.object(ui_mod, "_run", side_effect=_run_side_effect),
    ):
        result = runner.invoke(ui_app, ["ocr", "aico"])

    assert result.exit_code == 0, result.output
    resolve.assert_called_once_with("aico")
    focused.assert_not_called()


def test_ocr_file_target_skips_capture():
    with (
        patch.object(ui_mod, "_require", lambda b: b),
        patch.object(ui_mod, "_focused_window") as focused,
        patch.object(ui_mod, "_run", side_effect=_run_side_effect) as run,
        patch("cli.commands.ui.Path.is_file", return_value=True),
    ):
        result = runner.invoke(ui_app, ["ocr", "/tmp/shot.png"])

    assert result.exit_code == 0, result.output
    focused.assert_not_called()
    # no capture step — only tesseract runs
    assert all(c.args[0][0] != "import" for c in run.call_args_list)
