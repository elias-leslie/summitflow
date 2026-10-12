from __future__ import annotations

import subprocess
from datetime import date
from pathlib import Path

import pytest

from app.tasks.nightly_deep_lane import skip_reason
from cli.lib.deep_lane import DeepLaneError, _run, deep_stages

SLOW_INI = "[pytest]\nmarkers =\n    slow: long tests\n    unit: fast\n"


@pytest.mark.parametrize(
    ("files", "expected"),
    [
        ({"pytest.ini": SLOW_INI}, ["pytest-slow"]),
        ({"backend/pytest.ini": SLOW_INI}, ["pytest-slow"]),
        ({"pyproject.toml": '[tool.pytest.ini_options]\nmarkers = ["slow: long"]\n'}, ["pytest-slow"]),
        ({"setup.cfg": "[tool:pytest]\nmarkers =\n    slow\n"}, ["pytest-slow"]),
        ({"pytest.ini": "[pytest]\nmarkers =\n    slowish: no\n"}, []),
        ({"go.mod": "module x\n", "a_test.go": "//go:build slow\n\npackage x\n"}, ["go-slow"]),
        ({"go.mod": "module x\n", "a_test.go": "package x\n"}, []),
        ({"pytest.ini": SLOW_INI,
          ".st-check.toml": '[[deep.stages]]\nid = "fixture"\nargv = ["run", "deep"]\n'}, ["fixture"]),
    ],
)
def test_deep_stages_follow_opt_in_conventions(tmp_path: Path, files: dict[str, str], expected: list[str]) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    for name, content in files.items():
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text(content)
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    assert [stage["id"] for stage in deep_stages(tmp_path)] == expected


@pytest.mark.parametrize("declaration", [
    "[deep]\n",
    '[[deep.stages]]\nid = "x"\nargv = []\n',
    '[[deep.stages]]\nid = "x"\nargv = ["a"]\ncwd = "../elsewhere"\n',
])
def test_invalid_deep_declaration_is_refused(tmp_path: Path, declaration: str) -> None:
    (tmp_path / ".st-check.toml").write_text(declaration)
    with pytest.raises(DeepLaneError):
        deep_stages(tmp_path)


@pytest.mark.parametrize(
    ("code", "none_ok", "state"),
    [(0, False, "pass"), (5, True, "pass"), (5, False, "fail"), (1, True, "fail")],
)
def test_stage_outcome_tolerates_only_an_empty_opt_in(tmp_path: Path, code: int, none_ok: bool, state: str) -> None:
    stage = {"id": "s", "argv": ["sh", "-c", f"exit {code}"], "cwd": ".", "timeout_seconds": 10,
             "admitted": True, "none_ok": none_ok}
    assert _run(tmp_path, stage, {"PATH": "/usr/bin:/bin"})["state"] == state


HEAD, OTHER = "a" * 40, "b" * 40


@pytest.mark.parametrize(
    ("prior", "skipped"),
    [
        ({}, False),
        ({"date": "2026-10-12", "sha": OTHER, "state": "fail"}, True),
        ({"date": "2026-10-10", "sha": HEAD, "state": "pass"}, True),
        ({"date": "2026-10-10", "sha": HEAD, "state": "fail"}, False),
        ({"date": "2026-10-10", "sha": OTHER, "state": "pass"}, False),
        ({"date": "2026-09-01", "sha": HEAD, "state": "pass"}, False),
    ],
)
def test_nightly_runs_each_project_once_a_day_unless_its_head_recently_passed(prior: dict, skipped: bool) -> None:
    assert (skip_reason(prior, HEAD, date(2026, 10, 12)) is not None) is skipped
