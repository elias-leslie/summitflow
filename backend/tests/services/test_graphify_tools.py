"""Graphify tool resolution tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services import graphify_tools


def test_graphify_bin_skips_broken_shebang_candidate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    broken = tmp_path / "graphify"
    broken.write_text("#!/missing/python\nprint('nope')\n", encoding="utf-8")
    broken.chmod(0o755)
    fallback = tmp_path / "fallback-graphify"
    fallback.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    fallback.chmod(0o755)

    monkeypatch.delenv("GRAPHIFY_BIN", raising=False)
    monkeypatch.setattr(graphify_tools.shutil, "which", lambda _: str(broken))
    monkeypatch.setattr(graphify_tools, "_DEFAULT_GRAPHIFY_BIN", fallback)

    assert graphify_tools.graphify_bin() == str(fallback)


def test_graphify_bin_reports_unrunnable_configured_binary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    broken = tmp_path / "graphify"
    broken.write_text("#!/missing/python\nprint('nope')\n", encoding="utf-8")
    broken.chmod(0o755)

    monkeypatch.setenv("GRAPHIFY_BIN", str(broken))

    with pytest.raises(FileNotFoundError, match="not runnable"):
        graphify_tools.graphify_bin()
