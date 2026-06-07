"""Tests for `st ui gif` (record a window/region to an animated GIF).

`gif` wraps ffmpeg x11grab + palettegen/paletteuse. The X11/ffmpeg layer is
mocked the way `test_ui_grab.py` does it: `_run` is faked (and records the argv
so we can assert the constructed ffmpeg command), the output file is written for
real into a tmp dir, and tool presence + image dimensions are stubbed.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from cli.commands import ui as ui_mod
from cli.commands.ui import app as ui_app

runner = CliRunner()


def _proc(stdout: str = "", returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr="")


def _make_side_effect(calls: list[list[str]]):
    """Record every argv; `ffmpeg` writes its output file (last arg) so the
    command's existence/size checks pass."""

    def _side_effect(cmd, **_):
        calls.append(cmd)
        if cmd and cmd[0] == "ffmpeg":
            Path(cmd[-1]).write_bytes(b"GIF89a fake bytes")
        return _proc()

    return _side_effect


def _ffmpeg_call(calls: list[list[str]]) -> list[str]:
    return next(c for c in calls if c and c[0] == "ffmpeg")


def test_gif_region_builds_ffmpeg_command(tmp_path):
    dest = tmp_path / "clip.gif"
    calls: list[list[str]] = []
    with (
        patch.object(ui_mod, "_require", lambda b: b),
        patch.object(ui_mod, "_identify_dims", return_value=(960, 540)),
        patch.object(ui_mod, "_run", side_effect=_make_side_effect(calls)),
        patch.dict(os.environ, {"DISPLAY": ":1", "ST_UI_DISPLAY": ""}),
    ):
        result = runner.invoke(
            ui_app,
            ["gif", "--region", "1280x720+10+20", "-t", "3", "--fps", "15", "-o", str(dest)],
        )

    assert result.exit_code == 0, result.output
    ff = _ffmpeg_call(calls)
    # Region → exact capture geometry and display offset (":1" normalized to ":1.0").
    assert ff[ff.index("-video_size") + 1] == "1280x720"
    assert ff[ff.index("-i") + 1] == ":1.0+10,20"
    assert ff[ff.index("-t") + 1] == "3.0"
    # -t MUST precede -i: as an output option it deadlocks the live-capture
    # palettegen graph (the bug this guards against). As an input option it bounds
    # x11grab and EOFs cleanly.
    assert ff.index("-t") < ff.index("-i")
    assert ff[ff.index("-framerate") + 1] == "15"
    # High-quality GIF path + non-interactive + infinite loop.
    vf = ff[ff.index("-vf") + 1]
    assert "palettegen" in vf and "paletteuse" in vf
    assert "-nostdin" in ff and ff[ff.index("-loop") + 1] == "0"
    assert "gif:path=" in result.output and dest.exists()


def test_gif_window_uses_resolved_geometry(tmp_path):
    dest = tmp_path / "w.gif"
    calls: list[list[str]] = []
    with (
        patch.object(ui_mod, "_require", lambda b: b),
        patch.object(ui_mod, "_resolve_window", return_value=0x123),
        patch.object(ui_mod, "_window_geometry", return_value=(100, 50, 1440, 900)),
        patch.object(ui_mod, "_identify_dims", return_value=(960, 600)),
        patch.object(ui_mod, "_run", side_effect=_make_side_effect(calls)),
        patch.dict(os.environ, {"DISPLAY": ":1", "ST_UI_DISPLAY": ""}),
    ):
        result = runner.invoke(ui_app, ["gif", "-w", "A-Term", "-t", "2", "-o", str(dest)])

    assert result.exit_code == 0, result.output
    ff = _ffmpeg_call(calls)
    assert ff[ff.index("-video_size") + 1] == "1440x900"
    assert ff[ff.index("-i") + 1] == ":1.0+100,50"


def test_gif_native_width_skips_scale_filter(tmp_path):
    dest = tmp_path / "native.gif"
    calls: list[list[str]] = []
    with (
        patch.object(ui_mod, "_require", lambda b: b),
        patch.object(ui_mod, "_identify_dims", return_value=(800, 600)),
        patch.object(ui_mod, "_run", side_effect=_make_side_effect(calls)),
        patch.dict(os.environ, {"DISPLAY": ":0", "ST_UI_DISPLAY": ""}),
    ):
        result = runner.invoke(
            ui_app, ["gif", "--region", "800x600+0+0", "--width", "0", "-o", str(dest)]
        )

    assert result.exit_code == 0, result.output
    vf = _ffmpeg_call(calls)[_ffmpeg_call(calls).index("-vf") + 1]
    # width=0 → native resolution: no lanczos downscale filter (note "scale=" alone
    # would false-match "bayer_scale=3" in the paletteuse filter).
    assert "lanczos" not in vf


def test_gif_rejects_bad_region():
    with patch.object(ui_mod, "_require", lambda b: b):
        result = runner.invoke(ui_app, ["gif", "--region", "not-a-region", "-t", "1"])
    assert result.exit_code == 1
    assert "WxH+X+Y" in result.output


def test_gif_rejects_nonpositive_duration():
    with patch.object(ui_mod, "_require", lambda b: b):
        result = runner.invoke(ui_app, ["gif", "--region", "100x100+0+0", "-t", "0"])
    assert result.exit_code == 1
    assert "duration" in result.output


def test_window_geometry_parses_wmctrl():
    line = "0x00000123  0 100 50 1440 900 host  A-Term Title\n"
    with (
        patch.object(ui_mod, "_require", lambda b: b),
        patch.object(ui_mod, "_run", return_value=_proc(stdout=line)),
    ):
        assert ui_mod._window_geometry(0x123) == (100, 50, 1440, 900)
