"""Test and gate budget: a cheap ratchet against unchecked suite growth.

Per project it measures tracked source and test lines, the median full-gate
duration from retained acceptance receipts, and slow tests from the latest
retained JUnit evidence. Every measurement fails open: missing data yields
``None`` and never blocks work.

The per-project baseline lives in ``<git-common-dir>/st/budget.json``, not in
``.st-check.toml``: it is measured state that moves with every ratchet, and
``.st-check.toml`` is a bound acceptance input, so writing it would invalidate
every receipt and stage result. Owner policy (thresholds) stays in
``.st-check.toml [budget]``.
"""

from __future__ import annotations

import json
import os
import re
import statistics
import subprocess
import tempfile
import time
import tomllib
import xml.etree.ElementTree as ET
from collections.abc import Callable, Mapping
from contextlib import suppress
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

DEFAULTS: dict[str, float] = {
    "ratio_ceiling": 0.8,
    "gate_seconds_per_kloc": 0.6,
    "gate_floor_seconds": 60.0,
    "slow_test_seconds": 3.0,
    "receipts": 5,
    # The gate median may wobble this much above its ratchet before it counts.
    "gate_tolerance": 0.1,
}
SLOW_TEST_NOISE = 2
TRIM_TASK_TITLE = "Trim test suite"
TRIM_TASK_LABEL = "test-budget"

_CODE_SUFFIXES = frozenset({
    ".py", ".pyi", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".go", ".rs", ".gd", ".sh", ".bash",
    ".svelte", ".vue", ".java", ".kt", ".swift", ".c", ".h", ".cc", ".cpp", ".hpp", ".rb", ".lua", ".sql",
})
_EXCLUDED_PARTS = frozenset({
    "vendor", "vendored", "third_party", "third-party", "node_modules", "dist", "build", "generated",
    "__generated__", "migrations", "versions", ".venv", "graphify-out", "fixtures",
})
_GENERATED_SUFFIXES = (".min.js", ".min.css", ".d.ts", "_pb2.py", "_pb2.pyi", ".pb.go", ".gen.ts", ".gen.go")
_TEST_SUFFIXES = (".test.ts", ".test.tsx", ".test.js", ".test.jsx", ".spec.ts", ".spec.tsx", ".spec.js", ".spec.jsx")


def is_counted(path: str) -> bool:
    pure = PurePosixPath(path)
    if pure.suffix not in _CODE_SUFFIXES or path.endswith(_GENERATED_SUFFIXES):
        return False
    return not _EXCLUDED_PARTS.intersection(pure.parts[:-1])


def is_test(path: str) -> bool:
    pure = PurePosixPath(path)
    name = pure.name
    return ("tests" in pure.parts[:-1] or "__tests__" in pure.parts[:-1]
            or (name.startswith("test_") and name.endswith(".py"))
            or name.endswith("_test.go") or name.endswith(_TEST_SUFFIXES))


@dataclass
class Measurement:
    project: str
    source_loc: int | None = None
    test_loc: int | None = None
    gate_median_seconds: float | None = None
    gate_receipts: int = 0
    slow_tests: int | None = None
    slowest_ten_seconds: float | None = None
    thresholds: dict[str, float] = field(default_factory=dict)

    @property
    def ratio(self) -> float | None:
        if not self.source_loc or self.test_loc is None:
            return None
        return self.test_loc / self.source_loc

    @property
    def gate_budget_seconds(self) -> float | None:
        if self.source_loc is None:
            return None
        return max(self.thresholds["gate_floor_seconds"],
                   self.thresholds["gate_seconds_per_kloc"] * self.source_loc / 1000)

    @property
    def gate_seconds_per_kloc(self) -> float | None:
        if self.gate_median_seconds is None or not self.source_loc:
            return None
        return self.gate_median_seconds / (self.source_loc / 1000)

    def over_budget(self) -> list[str]:
        reasons = []
        if self.ratio is not None and self.ratio > self.thresholds["ratio_ceiling"]:
            reasons.append("test_ratio")
        budget = self.gate_budget_seconds
        if self.gate_median_seconds is not None and budget is not None and self.gate_median_seconds > budget:
            reasons.append("gate_duration")
        return reasons

    def baseline(self) -> dict[str, Any]:
        return {"test_loc": self.test_loc, "ratio": self.ratio, "gate_median_seconds": self.gate_median_seconds,
                "slow_tests": self.slow_tests, "measured_at": time.time()}

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "ratio": self.ratio, "gate_budget_seconds": self.gate_budget_seconds,
                "gate_seconds_per_kloc": self.gate_seconds_per_kloc, "over_budget": self.over_budget()}


def _git(root: Path, *args: str, data: bytes | None = None) -> bytes | None:
    try:
        result = subprocess.run(["git", "--no-optional-locks", *args], cwd=root, input=data,
                                capture_output=True, check=False, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout if result.returncode == 0 else None


def _state_dir(root: Path) -> Path | None:
    common = _git(root, "rev-parse", "--path-format=absolute", "--git-common-dir")
    return Path(common.decode().strip()) / "st" if common else None


def thresholds(root: Path) -> dict[str, float]:
    values = dict(DEFAULTS)
    try:
        configured = tomllib.loads((root / ".st-check.toml").read_text(encoding="utf-8")).get("budget", {})
    except (OSError, UnicodeError, tomllib.TOMLDecodeError):
        configured = {}
    if isinstance(configured, dict):
        for key in DEFAULTS:
            value = configured.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
                values[key] = float(value)
    return values


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False) as handle:
        json.dump(value, handle, sort_keys=True)
        temporary = Path(handle.name)
    temporary.replace(path)


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def count_lines(content: bytes) -> int:
    """Non-blank lines."""
    return sum(1 for line in content.splitlines() if line.strip())


def line_counts(root: Path, state: Path | None) -> tuple[int, int] | None:
    """Count tracked source/test lines; blob line counts are cached by OID."""
    listing = _git(root, "ls-files", "-s", "-z")
    if listing is None:
        return None
    blobs: dict[str, str] = {}
    for entry in listing.decode("utf-8", "replace").split("\0"):
        header, _, path = entry.partition("\t")
        fields = header.split()
        if path and len(fields) == 3 and fields[0] in {"100644", "100755"} and is_counted(path):
            blobs[path] = fields[1]
    cache_path = state / "budget-loc-cache-v2.json" if state else None
    cached = _read_json(cache_path) if cache_path else None
    cache: dict[str, int] = cached if isinstance(cached, dict) else {}
    missing = sorted({oid for oid in blobs.values() if not isinstance(cache.get(oid), int)})
    if missing:
        output = _git(root, "cat-file", "--batch", data="".join(f"{oid}\n" for oid in missing).encode())
        if output is None:
            return None
        offset = 0
        for oid in missing:
            end = output.find(b"\n", offset)
            header = output[offset:end].split()
            if end < 0 or len(header) != 3:
                return None
            size = int(header[2])
            content = output[end + 1:end + 1 + size]
            cache[oid] = count_lines(content)
            offset = end + 1 + size + 1
    if cache_path and missing:
        live = set(blobs.values())
        with suppress(OSError):
            _write_json(cache_path, {oid: lines for oid, lines in cache.items() if oid in live})
    lines = {path: cache[oid] for path, oid in blobs.items()}
    # Uncommitted edits and new files count now, not at the next measurement.
    changed = _git(root, "ls-files", "-m", "-o", "--exclude-standard", "-z")
    for path in (changed or b"").decode("utf-8", "replace").split("\0"):
        if not path or not is_counted(path):
            continue
        try:
            content = (root / path).read_bytes()
        except OSError:
            lines.pop(path, None)
            continue
        lines[path] = count_lines(content)
    source = sum(count for path, count in lines.items() if not is_test(path))
    tests = sum(count for path, count in lines.items() if is_test(path))
    return source, tests


def _full_receipts(state: Path, limit: int) -> list[dict[str, Any]]:
    directory = state / "acceptance"
    try:
        candidates = sorted(directory.glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    except OSError:
        return []
    selected: dict[str, dict[str, Any]] = {}
    # Timings under an older gate plan (stages, tools, workers) are not
    # comparable, so only runs sharing the newest run's plan count.
    current_plan: object = None
    for path in candidates[:limit * 6]:
        value = _read_json(path)
        if (isinstance(value, dict) and value.get("coverage") == "full" and value.get("state") == "success"
                and isinstance(value.get("duration_ms"), (int, float))):
            plan = (value.get("plan") or {}).get("fingerprint") if isinstance(value.get("plan"), dict) else None
            if not selected:
                current_plan = plan
            elif plan != current_plan:
                continue
            selected.setdefault(str(value.get("acceptance_id")), value)
        if len(selected) >= limit:
            break
    return list(selected.values())


_QUEUE_MS = re.compile(r"queue_ms:([\d.]+)")


def _queued_ms(receipt: Mapping[str, Any]) -> float:
    """Time spent waiting for heavy-work admission behind other projects.

    Legacy tools print ``queue_ms:`` in their result lines; native stages
    record it per stage. Neither is the project's own cost.
    """
    total = 0.0
    for check in receipt.get("checks") or []:
        if not isinstance(check, Mapping):
            continue
        total += sum(float(value) for value in _QUEUE_MS.findall(str(check.get("detail") or "")))
        evidence = check.get("evidence")
        for stage in (evidence.get("stages") or []) if isinstance(evidence, Mapping) else []:
            if isinstance(stage, Mapping) and isinstance(stage.get("queue_ms"), (int, float)):
                total += float(stage["queue_ms"])
    return total


def gate_median(state: Path | None, limit: int) -> tuple[float | None, int]:
    receipts = _full_receipts(state, limit) if state else []
    if not receipts:
        return None, 0
    seconds = (max(0.0, receipt["duration_ms"] - _queued_ms(receipt)) / 1000 for receipt in receipts)
    return statistics.median(seconds), len(receipts)


def _junit_reports(root: Path, state: Path | None) -> list[Path]:
    """Native stage JUnit artifacts of the newest receipt; legacy pytest reports otherwise."""
    if state:
        for receipt in _full_receipts(state, 1) or []:
            reports = [Path(artifact["retained_path"])
                       for check in receipt.get("checks", []) for stage in (check.get("evidence") or {}).get("stages", [])
                       for artifact in stage.get("artifacts", [])
                       if str(artifact.get("path", "")).endswith(".xml") and artifact.get("retained_path")]
            if reports:
                return [path for path in reports if path.is_file()]
    try:
        legacy = sorted((root / ".dev-tools").glob("*.xml"), key=lambda path: path.stat().st_mtime, reverse=True)
    except OSError:
        return []
    newest: dict[str, Path] = {}
    for path in legacy:
        newest.setdefault(path.name.split("-", 1)[0], path)
    return list(newest.values())


def slow_tests(reports: list[Path], threshold: float) -> tuple[int, float] | None:
    durations: list[float] = []
    for report in reports:
        try:
            for case in ET.parse(report).getroot().iter("testcase"):
                try:
                    durations.append(float(case.get("time") or 0))
                except ValueError:
                    continue
        except (OSError, ET.ParseError):
            continue
    if not durations:
        return None
    durations.sort(reverse=True)
    return sum(value > threshold for value in durations), round(sum(durations[:10]), 3)


def measure(root: Path, project: str | None = None) -> Measurement:
    root = root.resolve()
    limits = thresholds(root)
    state = _state_dir(root)
    result = Measurement(project=project or root.name, thresholds=limits)
    try:
        counts = line_counts(root, state)
        if counts:
            result.source_loc, result.test_loc = counts
    except (OSError, ValueError):
        pass
    result.gate_median_seconds, result.gate_receipts = gate_median(state, int(limits["receipts"]))
    slow = slow_tests(_junit_reports(root, state), limits["slow_test_seconds"])
    if slow:
        result.slow_tests, result.slowest_ten_seconds = slow
    return result


def load_baseline(root: Path) -> dict[str, Any] | None:
    state = _state_dir(root.resolve())
    value = _read_json(state / "budget.json") if state else None
    return value if isinstance(value, dict) else None


def save_baseline(root: Path, baseline: Mapping[str, Any]) -> None:
    state = _state_dir(root.resolve())
    if state:
        _write_json(state / "budget.json", dict(baseline))


def regressions(current: Measurement, baseline: Mapping[str, Any] | None) -> list[str]:
    """What this change worsened while the project is over budget."""
    if baseline is None or not current.over_budget():
        return []
    found = []
    if current.test_loc is not None and isinstance(baseline.get("test_loc"), int) and current.test_loc > baseline["test_loc"]:
        found.append(f"test_loc +{current.test_loc - baseline['test_loc']}")
    # Test durations vary with host load; only growth beyond that noise counts.
    if (current.slow_tests is not None and isinstance(baseline.get("slow_tests"), int)
            and current.slow_tests > baseline["slow_tests"] * (1 + current.thresholds["gate_tolerance"]) + SLOW_TEST_NOISE):
        found.append(f"slow_tests +{current.slow_tests - baseline['slow_tests']}")
    ratchet = baseline.get("gate_median_seconds")
    if (current.gate_median_seconds is not None and isinstance(ratchet, (int, float))
            and current.gate_median_seconds > ratchet * (1 + current.thresholds["gate_tolerance"])):
        found.append(f"gate_median {ratchet:.0f}s->{current.gate_median_seconds:.0f}s")
    return found


def next_baseline(current: Measurement, baseline: Mapping[str, Any] | None, *, accepted: bool) -> dict[str, Any]:
    """Under budget the baseline follows; over budget it only tightens unless a note accepted growth."""
    measured = current.baseline()
    if baseline is None or not current.over_budget() or accepted:
        return {key: (measured[key] if measured[key] is not None else (baseline or {}).get(key)) for key in measured}
    tightened = dict(measured)
    for key in ("test_loc", "ratio", "gate_median_seconds", "slow_tests"):
        old, new = baseline.get(key), measured[key]
        tightened[key] = old if new is None else new if not isinstance(old, (int, float)) else min(old, new)
    return tightened


def _kilo(value: int | None) -> str:
    return "?" if value is None else f"{value / 1000:.0f}k"


def budget_line(current: Measurement, found: list[str] | None = None) -> str:
    over = current.over_budget()
    state = "over" if over else "ok"
    ratio = "?" if current.ratio is None else f"{current.ratio:.2f}"
    gate = "?" if current.gate_median_seconds is None else f"{current.gate_median_seconds:.0f}s"
    budget = "?" if current.gate_budget_seconds is None else f"{current.gate_budget_seconds:.0f}s"
    per_kloc = "?" if current.gate_seconds_per_kloc is None else f"{current.gate_seconds_per_kloc:.2f}"
    slow = "?" if current.slow_tests is None else str(current.slow_tests)
    parts = [f"BUDGET:{current.project}", f"state={state}", f"src={_kilo(current.source_loc)}",
             f"tests={_kilo(current.test_loc)}", f"ratio={ratio}/{current.thresholds['ratio_ceiling']:.2f}",
             f"gate={gate}/{budget}", f"gate_s_per_kloc={per_kloc}",
             f"slow>{current.thresholds['slow_test_seconds']:.0f}s={slow}"]
    if current.slowest_ten_seconds is not None:
        parts.append(f"slowest10={current.slowest_ten_seconds:.0f}s")
    if over:
        parts.append("over=" + ",".join(over))
    if found:
        parts.append("worsened=" + ",".join(found))
    return "|".join(parts)


_CLOSED = frozenset({"completed", "cancelled", "failed"})


def ensure_trim_task(project: str, current: Measurement, *, list_open: Callable[[], list[dict[str, Any]]],
                     create: Callable[[dict[str, Any]], dict[str, Any]]) -> str | None:
    """Open at most one trim task per project; returns its id when created."""
    if not current.over_budget():
        return None
    if any(task.get("title") == TRIM_TASK_TITLE and task.get("status") not in _CLOSED for task in list_open()):
        return None
    created = create({
        "title": TRIM_TASK_TITLE, "task_type": "debt", "priority": 3, "labels": [TRIM_TASK_LABEL],
        "description": (f"{project} is over its test/gate budget ({', '.join(current.over_budget())}). "
                        f"{budget_line(current)}. Remove redundant, slow or low-value tests, or move "
                        "slow-but-valuable ones to the nightly deep lane (pytest marker `slow`)."),
    })
    return str(created.get("id") or "") or None


@dataclass
class Decision:
    allowed: bool
    line: str
    worsened: list[str] = field(default_factory=list)
    current: Measurement | None = None
    baseline: dict[str, Any] | None = None


def assess(root: Path, project: str, *, note: str | None) -> Decision:
    """Whether completion may proceed; measurement failures always allow it."""
    try:
        current = measure(root, project)
        baseline = load_baseline(root)
        found = regressions(current, baseline)
        return Decision(not found or bool(note), budget_line(current, found), found, current, baseline)
    except Exception:
        return Decision(True, f"BUDGET:{project}|state=unavailable")


def record(root: Path, project: str, decision: Decision, *, note: str | None,
           list_open: Callable[[], list[dict[str, Any]]], create: Callable[[dict[str, Any]], dict[str, Any]],
           log: Callable[[str], None]) -> None:
    """After completion: log an accepted overrun, move the ratchet, open a trim task when over budget."""
    current = decision.current
    if current is None:
        return
    accepted = bool(decision.worsened and note)
    with suppress(Exception):
        if accepted:
            log(f"Test budget exceeded ({', '.join(decision.worsened)}); accepted: {note}")
    with suppress(Exception):
        save_baseline(root, next_baseline(current, decision.baseline, accepted=accepted))
    with suppress(Exception):
        ensure_trim_task(project, current, list_open=list_open, create=create)


def report(root: Path, *, json_output: bool) -> int:
    """`st check budget`: print the line; the first measurement becomes the baseline."""
    current = measure(root)
    baseline = load_baseline(root)
    if baseline is None:
        with suppress(OSError):
            save_baseline(root, current.baseline())
    print(budget_line(current, regressions(current, baseline)))
    if json_output:
        print("BUDGET_EVIDENCE:" + json.dumps({**current.to_dict(), "baseline": baseline}, sort_keys=True))
    return 0


def environment_disabled() -> bool:
    return os.environ.get("ST_BUDGET") == "off"
