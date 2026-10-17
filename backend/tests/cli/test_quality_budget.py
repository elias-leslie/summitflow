from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from cli.lib import quality_budget as budget


@pytest.mark.parametrize(
    ("path", "counted", "test"),
    [
        ("backend/app/x.py", True, False),
        ("backend/tests/test_x.py", True, True),
        ("frontend/src/a.test.tsx", True, True),
        ("frontend/src/__tests__/a.ts", True, True),
        ("pkg/a_test.go", True, True),
        ("backend/migrations/versions/1.py", False, False),
        ("frontend/node_modules/a/index.js", False, False),
        ("app/types.d.ts", False, False),
        ("docs/readme.md", False, False),
    ],
)
def test_classifies_source_and_tests(path: str, counted: bool, test: bool) -> None:
    assert budget.is_counted(path) is counted
    assert (budget.is_counted(path) and budget.is_test(path) is test) or not counted


def _repo(root: Path, files: dict[str, str], *, config: str = "") -> Path:
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    for name, content in {**files, **({".st-check.toml": config} if config else {})}.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(content)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init"], cwd=root, check=True)
    return root


def test_counts_non_blank_lines_including_uncommitted_work(tmp_path: Path) -> None:
    root = _repo(tmp_path, {"app/a.py": "x = 1\n\ny = 2\n", "tests/test_a.py": "def test():\n    pass\n"})
    assert budget.line_counts(root, budget._state_dir(root)) == (2, 2)
    (root / "tests" / "test_b.py").write_text("a\nb\nc\n")
    (root / "app" / "a.py").write_text("x = 1\n")
    assert budget.line_counts(root, budget._state_dir(root)) == (1, 5)


def _receipt(directory: Path, name: str, seconds: float, *, coverage: str = "full", state: str = "success",
             plan: str = "p1", mtime: float | None = None) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name}.json"
    path.write_text(json.dumps({"acceptance_id": name, "coverage": coverage, "state": state,
                                "duration_ms": seconds * 1000, "plan": {"fingerprint": plan}}))
    if mtime is not None:
        os.utime(path, (mtime, mtime))


def test_gate_median_uses_successful_full_receipts_only(tmp_path: Path) -> None:
    for name, seconds in (("a", 100), ("b", 200), ("c", 300)):
        _receipt(tmp_path / "acceptance", name, seconds)
    _receipt(tmp_path / "acceptance", "task", 5, coverage="task")
    _receipt(tmp_path / "acceptance", "failed", 9000, state="failed")
    assert budget.gate_median(tmp_path, 5) == (200, 3)
    assert budget.gate_median(tmp_path / "missing", 5) == (None, 0)


def test_gate_median_excludes_admission_queue_wait(tmp_path: Path) -> None:
    directory = tmp_path / "acceptance"
    directory.mkdir()
    (directory / "busy.json").write_text(json.dumps({
        "acceptance_id": "busy", "coverage": "full", "state": "success", "duration_ms": 106_000,
        "plan": {"fingerprint": "p1"},
        "checks": [{"detail": "TYPES:OK:0|queue_ms:21000.0|execution_ms:400\nTEST:OK:0|queue_ms:42000.0|execution_ms:17000",
                    "evidence": {"stages": [{"id": "python", "queue_ms": 3000.0}]}}],
    }))
    assert budget.gate_median(tmp_path, 5) == (40, 1)


def test_gate_median_ignores_runs_under_an_older_gate_plan(tmp_path: Path) -> None:
    for index, seconds in enumerate((300, 320, 310)):
        _receipt(tmp_path / "acceptance", f"old{index}", seconds, plan="before", mtime=1000 + index)
    _receipt(tmp_path / "acceptance", "new0", 90, plan="after", mtime=2000)
    _receipt(tmp_path / "acceptance", "new1", 110, plan="after", mtime=2001)
    assert budget.gate_median(tmp_path, 5) == (100, 2)


def _measurement(*, test_loc: int, source_loc: int = 1000, gate: float | None = None, slow: int | None = None,
                 **limits: float) -> budget.Measurement:
    return budget.Measurement(project="p", source_loc=source_loc, test_loc=test_loc, gate_median_seconds=gate,
                              slow_tests=slow, thresholds={**budget.DEFAULTS, **limits})


BASE = {"test_loc": 900, "ratio": 0.9, "gate_median_seconds": 100.0, "slow_tests": 2}


@pytest.mark.parametrize(
    ("current", "baseline", "worsened"),
    [
        (_measurement(test_loc=950), BASE, True),  # over ratio, more tests
        (_measurement(test_loc=880), BASE, False),  # over, but shrinking
        (_measurement(test_loc=900, slow=6), BASE, True),  # more slow tests than load noise explains
        (_measurement(test_loc=900, slow=4), BASE, False),  # within load noise
        (_measurement(test_loc=900, gate=200, gate_floor_seconds=60), BASE, True),  # gate past ratchet
        (_measurement(test_loc=900, gate=105), BASE, False),  # within tolerance
        (_measurement(test_loc=500), {**BASE, "test_loc": 400}, False),  # under budget: free to grow
        (_measurement(test_loc=950), None, False),  # no baseline yet
    ],
)
def test_regressions_only_count_while_over_budget(current: budget.Measurement, baseline: dict | None,
                                                  worsened: bool) -> None:
    assert bool(budget.regressions(current, baseline)) is worsened


def test_ratchet_tightens_over_budget_and_follows_when_accepted_or_under() -> None:
    over = _measurement(test_loc=950)
    assert budget.next_baseline(over, BASE, accepted=False)["test_loc"] == 900
    assert budget.next_baseline(_measurement(test_loc=850), BASE, accepted=False)["test_loc"] == 850
    assert budget.next_baseline(over, BASE, accepted=True)["test_loc"] == 950
    assert budget.next_baseline(_measurement(test_loc=500), BASE, accepted=False)["test_loc"] == 500


def test_completion_needs_a_note_only_when_an_over_budget_project_grows(tmp_path: Path) -> None:
    root = _repo(tmp_path, {"app/a.py": "a\n", "tests/test_a.py": "a\nb\n"},
                 config="[budget]\nratio_ceiling = 0.5\n")
    first = budget.assess(root, "p", note=None)
    assert first.allowed
    budget.record(root, "p", first, note=None, list_open=list, create=lambda task: {"id": "t"}, log=print)
    (root / "tests" / "test_b.py").write_text("c\n")
    assert not budget.assess(root, "p", note=None).allowed
    logged: list[str] = []
    accepted = budget.assess(root, "p", note="covers a new bug")
    assert accepted.allowed
    budget.record(root, "p", accepted, note="covers a new bug", list_open=list,
                  create=lambda task: {"id": "t"}, log=logged.append)
    assert logged
    assert budget.assess(root, "p", note=None).allowed


def test_missing_measurements_never_block(tmp_path: Path) -> None:
    assert budget.assess(tmp_path, "p", note=None).allowed


@pytest.mark.parametrize(
    ("existing", "creates"),
    [([], True), ([{"title": budget.TRIM_TASK_TITLE, "status": "pending"}], False),
     ([{"title": budget.TRIM_TASK_TITLE, "status": "completed"}], True)],
)
def test_one_open_trim_task_per_over_budget_project(existing: list[dict], creates: bool) -> None:
    created: list[dict] = []
    over = _measurement(test_loc=950)
    budget.ensure_trim_task("p", over, list_open=lambda: existing, create=lambda task: created.append(task) or {"id": "t"})
    assert bool(created) is creates
    budget.ensure_trim_task("p", _measurement(test_loc=100), list_open=list, create=lambda task: created.append(task) or {})
    assert len(created) == int(creates)


@pytest.mark.parametrize("budget_toml", [
    "[budget]\nratio_ceiling = 0\n",
    "[budget]\nratio_ceiling = \"high\"\n",
    "[budget]\nratio_cieling = 0.9\n",
    "[budget\n",
])
def test_invalid_budget_config_raises_instead_of_falling_back(tmp_path: Path, budget_toml: str) -> None:
    (tmp_path / ".st-check.toml").write_text(budget_toml)
    with pytest.raises(budget.BudgetConfigError):
        budget.thresholds(tmp_path)


def test_budget_config_overrides_and_missing_file_uses_defaults(tmp_path: Path) -> None:
    assert budget.thresholds(tmp_path) == budget.DEFAULTS
    (tmp_path / ".st-check.toml").write_text("[budget]\nratio_ceiling = 0.9\n")
    assert budget.thresholds(tmp_path)["ratio_ceiling"] == 0.9
