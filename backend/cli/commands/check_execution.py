"""Pure tool-execution helpers for st check."""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from pathlib import Path


def adjusted_tool_args(
    name: str,
    base_args: list[str],
    extra_args: list[str],
    root: Path | None = None,
) -> tuple[list[str], list[str]]:
    if name == "biome" and any(not arg.startswith("-") for arg in extra_args):
        base_args = [arg for arg in base_args if arg != "."]
    if name != "pytest":
        return base_args, extra_args

    has_path_arg = any(arg and not arg.startswith("-") for arg in extra_args)
    has_cov_control = any(arg == "--no-cov" or arg.startswith("--cov") for arg in extra_args)
    should_inject = has_path_arg and not has_cov_control
    if should_inject and (root is None or read_pytest_no_cov(root)):
        return base_args, ["--no-cov", *extra_args]
    return base_args, extra_args


# Conventions st check tries when a project has not declared a venv path in
# .st-check.toml. Ordered from project-root to backend/; surviving entries are
# prepended to PATH so a project-local tool wins over any system-wide install.
_DEFAULT_TOOL_PATH_CANDIDATES: dict[str, tuple[Path, ...]] = {
    "pytest": (Path("backend/.venv/bin"), Path(".venv/bin")),
    "ruff": (Path("backend/.venv/bin"), Path(".venv/bin")),
    "tsc": (Path("frontend/node_modules/.bin"), Path("node_modules/.bin")),
    "biome": (Path("frontend/node_modules/.bin"), Path("node_modules/.bin")),
    "vitest": (Path("frontend/node_modules/.bin"), Path("node_modules/.bin")),
}


def read_tool_paths(root: Path) -> dict[str, str]:
    """Read `<root>/.st-check.toml` and return its `[paths]` table.

    Returns an empty dict if the file is missing, malformed, or has no
    `[paths]` table. Degrade silently: a missing or broken config must not
    block `st check`; the caller falls back to the default candidate list.
    """
    config_path = root / ".st-check.toml"
    if not config_path.is_file():
        return {}
    try:
        data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return {}
    paths = data.get("paths")
    if not isinstance(paths, dict):
        return {}
    return {str(key): str(value) for key, value in paths.items() if isinstance(value, str)}


def tool_not_installed(name: str, root: Path) -> bool:
    """True when the repo has no environment that could contain the tool.

    A declared path in `.st-check.toml` or an existing default candidate dir
    (e.g. backend/.venv/bin for pytest) means the project intends to have the
    tool — a missing binary there is a broken env and stays a failure. With
    neither present (e.g. pytest in a repo with no Python venv), the tool was
    never installable and the gate should skip instead of fail.
    """
    if name in read_tool_paths(root):
        return False
    candidates = _DEFAULT_TOOL_PATH_CANDIDATES.get(name, ())
    return not any((root / candidate).exists() for candidate in candidates)


def read_pytest_no_cov(root: Path) -> bool:
    """Return the project's preference for `--no-cov` auto-injection.

    True (default) preserves the historic behavior: when `st check pytest`
    is given a path argument, `--no-cov` is prepended so coverage does not
    slow the targeted run. False disables the auto-injection for projects
    that do not install pytest-cov and therefore cannot accept the flag.

    Configured via `.st-check.toml`:
        [pytest]
        no_cov = false
    """
    config_path = root / ".st-check.toml"
    if not config_path.is_file():
        return True
    try:
        data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return True
    section = data.get("pytest")
    if not isinstance(section, dict):
        return True
    value = section.get("no_cov")
    if isinstance(value, bool):
        return value
    return True


def tool_env(root: Path, environ: Mapping[str, str], name: str | None = None) -> dict[str, str]:
    env = dict(environ)
    declared = read_tool_paths(root)
    candidates: list[Path] = []
    if name and name in declared:
        # Project has named its tool path. Trust it; do not also try defaults,
        # or a stale .venv/ would silently win over the declared location.
        candidates.append(root / declared[name])
    else:
        for default in _DEFAULT_TOOL_PATH_CANDIDATES.get(name or "", ()):
            candidates.append(root / default)
    paths = [str(candidate) for candidate in candidates if candidate.exists()]
    if paths:
        env["PATH"] = ":".join([*paths, env.get("PATH", "")])
    # Vitest only defaults NODE_ENV to "test" when it is unset; an inherited
    # NODE_ENV=production (e.g. launched from an electron-vite/npm prod context)
    # makes it load the production React build, where React.act is undefined and
    # @testing-library throws "React.act is not a function". Force the value the
    # test runner would otherwise pick itself.
    if name == "vitest":
        env["NODE_ENV"] = "test"
    return env


def tool_output(stdout: str, stderr: str) -> str:
    return "\n".join(part for part in (stdout, stderr) if part)


def tool_result_line(
    label: str,
    name: str,
    returncode: int,
    details: str,
    hint: str,
) -> str:
    status = "OK" if returncode == 0 else "FAIL"
    return f"{label}:{status}:{returncode}|details:{details}|hint:{hint}"
