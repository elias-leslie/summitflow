"""Nightly deep lane: the full gate without reuse plus the tests the gate skips.

A project opts tests in without new configuration:
- Python: mark tests ``@pytest.mark.slow`` (the project's pytest config must
  declare the ``slow`` marker; the gate keeps excluding it).
- Go: put tests behind ``//go:build slow``.
- Anything else, or a project needing a fixture: declare ``[[deep.stages]]``
  (``id``, ``argv``, optional ``cwd`` and ``timeout_seconds``) in
  ``.st-check.toml``; explicit stages replace detection.
Tests needing production or live credentials stay out of every lane.

Repos with migrations or workspace packages also rerun the gate the way a
hosted CI runner would (``clean-env``): a fresh clone of the commit, locked
dependencies installed as copies, and the CI workflow's service database
started empty (``cli.lib.ci_parity``).
"""

from __future__ import annotations

import configparser
import os
import pwd
import re
import subprocess
import sys
import time
import tomllib
from pathlib import Path
from typing import Any

GATE_TIMEOUT_SECONDS = 2 * 60 * 60
STAGE_TIMEOUT_SECONDS = 60 * 60
NO_TESTS_COLLECTED = 5  # pytest: every test deselected


class DeepLaneError(ValueError):
    """The project's deep-lane declaration is invalid."""


def _st() -> list[str]:
    """This running gate, as acceptance invokes it, so nested checks use the same code."""
    bootstrap = "import sys; sys.path.insert(0, sys.argv.pop(1)); from cli.main import app; app()"
    return [sys.executable, "-P", "-c", bootstrap, str(Path(__file__).resolve().parents[2])]


def _declared(root: Path) -> list[dict[str, Any]] | None:
    try:
        data = tomllib.loads((root / ".st-check.toml").read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise DeepLaneError(f"invalid .st-check.toml: {exc}") from exc
    deep = data.get("deep")
    if deep is None:
        return None
    stages = deep.get("stages") if isinstance(deep, dict) else None
    if not isinstance(stages, list) or not stages:
        raise DeepLaneError("[deep] must declare at least one [[deep.stages]] entry")
    normalized = []
    for stage in stages:
        argv = stage.get("argv") if isinstance(stage, dict) else None
        cwd = stage.get("cwd", ".") if isinstance(stage, dict) else None
        timeout = stage.get("timeout_seconds", STAGE_TIMEOUT_SECONDS) if isinstance(stage, dict) else None
        if (not isinstance(stage.get("id"), str) or not stage["id"] or not isinstance(argv, list) or not argv
                or any(not isinstance(part, str) for part in argv) or not isinstance(cwd, str)
                or Path(cwd).is_absolute() or ".." in Path(cwd).parts
                or not isinstance(timeout, int) or timeout <= 0):
            raise DeepLaneError("each [[deep.stages]] needs id, argv, a project-relative cwd and a positive timeout_seconds")
        normalized.append({"id": stage["id"], "argv": argv, "cwd": cwd, "timeout_seconds": timeout})
    return normalized


def _marker_lines(base: Path) -> str:
    ini = base / "pytest.ini"
    if ini.is_file():
        parser = configparser.ConfigParser(interpolation=None)
        parser.read(ini, encoding="utf-8")
        return parser.get("pytest", "markers", fallback="")
    pyproject = base / "pyproject.toml"
    if pyproject.is_file():
        try:
            options = tomllib.loads(pyproject.read_text(encoding="utf-8")).get("tool", {}).get("pytest", {})
        except (OSError, UnicodeError, tomllib.TOMLDecodeError):
            options = {}
        markers = options.get("ini_options", {}).get("markers", [])
        if markers:
            return "\n".join(str(marker) for marker in markers)
    setup = base / "setup.cfg"
    if setup.is_file():
        parser = configparser.ConfigParser(interpolation=None)
        parser.read(setup, encoding="utf-8")
        return parser.get("tool:pytest", "markers", fallback="")
    return ""


def _declares_slow_marker(base: Path) -> bool:
    return any(line.strip().split(":", 1)[0].strip() == "slow" for line in _marker_lines(base).splitlines())


def _has_slow_go_tests(root: Path) -> bool:
    if not (root / "go.mod").is_file():
        return False
    found = subprocess.run(["git", "grep", "-lE", r"^//go:build .*\bslow\b", "--", "*.go"],
                           cwd=root, capture_output=True, text=True, check=False)
    return found.returncode == 0 and bool(found.stdout.strip())


def deep_stages(root: Path) -> list[dict[str, Any]]:
    """Explicit ``[[deep.stages]]``, else the stages the opt-in conventions imply."""
    declared = _declared(root)
    if declared is not None:
        return declared
    stages: list[dict[str, Any]] = []
    if any(_declares_slow_marker(base) for base in (root, root / "backend")):
        stages.append({"id": "pytest-slow", "argv": [*_st(), "check", "pytest", "--", "-m", "slow"],
                       "cwd": ".", "timeout_seconds": STAGE_TIMEOUT_SECONDS, "admitted": True, "none_ok": True})
    if _has_slow_go_tests(root):
        stages.append({"id": "go-slow", "argv": ["go", "test", "-count=1", "-tags", "slow", "./..."],
                       "cwd": ".", "timeout_seconds": STAGE_TIMEOUT_SECONDS})
    return stages


def clean_env_applies(root: Path) -> bool:
    """Migrations or workspace packages: where a reused checkout and its deps hid CI-only failures."""
    tracked = subprocess.run(["git", "ls-files", "--", ":(glob)**/alembic.ini", ":(glob)**/migrations/**",
                              ":(glob)**/pnpm-workspace.yaml"], cwd=root, capture_output=True, text=True, check=False)
    if tracked.stdout.strip():
        return True
    uv = subprocess.run(["git", "grep", "-lF", "[tool.uv.workspace]", "--", ":(glob)**/pyproject.toml"],
                        cwd=root, capture_output=True, text=True, check=False)
    return bool(uv.stdout.strip())


def clean_env_stage(head: str) -> dict[str, Any]:
    """The full gate with CI parity in a fresh clone of ``head`` with freshly installed deps."""
    from . import ci_parity

    environment = [f"{ci_parity.PARITY_FLAG}=1", f"{ci_parity.SEED_VAR}={ci_parity.new_seed()}", "ST_NATIVE_NO_REUSE=1"]
    # The cleanroom's private HOME hides st's own settings; CI parity gives every tool a scrubbed HOME anyway.
    gate = ["/usr/bin/env", f"HOME={pwd.getpwuid(os.getuid()).pw_dir}", *_st(), "check", "--check"]
    return {"id": "clean-env",
            "argv": [*_st(), "check", "cleanroom", "--clone", head, "--deps",
                     *(arg for item in environment for arg in ("--env", item)), "--", *gate],
            "cwd": ".", "timeout_seconds": GATE_TIMEOUT_SECONDS, "admitted": True}


def _run(root: Path, stage: dict[str, Any], env: dict[str, str]) -> dict[str, Any]:
    from app.utils.heavy_work import heavy_work

    started = time.monotonic()
    cwd, timeout = root / stage["cwd"], stage["timeout_seconds"]
    try:
        if stage.get("admitted"):  # the command takes its own heavy-work admission
            result = subprocess.run(stage["argv"], cwd=cwd, env=env, stdin=subprocess.DEVNULL, capture_output=True,
                                    text=True, errors="replace", timeout=timeout, check=False)
        else:
            with heavy_work(f"deep {stage['id']}", work_class="heavy", project=root.name) as work:
                result = work.run(stage["argv"], cwd=cwd, env=env, stdin=subprocess.DEVNULL, capture_output=True,
                                  text=True, errors="replace", timeout=timeout, check=False)
        returncode, output = result.returncode, (result.stdout or "") + (result.stderr or "")
    except subprocess.TimeoutExpired:
        returncode, output = 124, f"timed out after {stage['timeout_seconds']}s"
    except OSError as exc:
        returncode, output = 127, f"{type(exc).__name__}: {exc}"
    state, reason = "pass", "passed"
    if returncode == NO_TESTS_COLLECTED and stage.get("none_ok"):
        reason = "no_tests_opted_in"
    elif returncode:
        state, reason = "fail", f"exit_{returncode}"
    # Gate output ends in a large evidence line; lead with the failing results.
    failures = [line[:300] for line in output.splitlines()
                if re.match(r"^(NATIVE:fail:|DEEP:fail:|CLEANROOM:deps-failed:|[A-Z_]+:FAIL:)", line)]
    return {"id": stage["id"], "state": state, "reason": reason, "failures": failures[:20],
            "duration_ms": round((time.monotonic() - started) * 1000), "detail": output[-1500:]}


def run_deep(root: Path) -> dict[str, Any]:
    """Run the fresh full gate, every deep stage, then clean-env; all of them, even after a failure."""
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=False)
    stages = deep_stages(root)
    if head.stdout.strip() and clean_env_applies(root):
        stages.append(clean_env_stage(head.stdout.strip()))
    env = {**os.environ, "ST_NATIVE_NO_REUSE": "1"}
    gate = {"id": "gate", "argv": [*_st(), "check", "--check"], "cwd": ".",
            "timeout_seconds": GATE_TIMEOUT_SECONDS, "admitted": True}
    outcomes = [_run(root, stage, env) for stage in (gate, *stages)]
    return {"project": root.name, "sha": head.stdout.strip(),
            "state": "pass" if all(row["state"] == "pass" for row in outcomes) else "fail",
            "stages": outcomes}
