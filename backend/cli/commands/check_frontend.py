"""Resolve aggregate frontend tests from the project's package manifest."""

from __future__ import annotations

import json
import shlex
from pathlib import Path
from typing import cast


def _manifest(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must contain an object")
    return value


def frontend_test_config(
    root: Path, cwd: Path, config: dict[str, object]
) -> tuple[str, dict[str, object]] | None:
    """Return a bounded declared suite, or None only when no suite is declared."""
    package = _manifest(cwd / "package.json")
    scripts = package.get("scripts", {})
    if not isinstance(scripts, dict):
        raise ValueError("package.json scripts must be an object")
    scripts = cast(dict[str, object], scripts)
    script_name = "test:ci" if "test:ci" in scripts else "test"
    script = scripts.get(script_name)
    if script is None and script_name not in scripts:
        for field in ("dependencies", "devDependencies"):
            dependencies = package.get(field, {})
            if not isinstance(dependencies, dict):
                raise ValueError(f"package.json {field} must be an object")
            if "vitest" in dependencies:
                return "vitest", config
        return None
    if not isinstance(script, str) or not script.strip():
        raise ValueError(f"package.json {script_name} must be a nonempty command")
    tokens = shlex.split(script)
    if any(token.split("=", 1)[0] in {"--watch", "--watchAll", "--ui", "-w"} for token in tokens) or (
        tokens[:2] == ["vitest", "watch"]
    ):
        raise ValueError("Interactive test script: declare a non-watch test:ci script")
    hooks = any(f"{prefix}{script_name}" in scripts for prefix in ("pre", "post"))
    if tokens in (["vitest"], ["vitest", "run"]) and not hooks:
        return "vitest", config
    manager = package.get("packageManager")
    if manager is None and cwd != root:
        manager = _manifest(root / "package.json").get("packageManager")
    if manager is not None:
        if not isinstance(manager, str) or manager.split("@", 1)[0] not in {"pnpm", "npm", "yarn", "bun"}:
            raise ValueError("Unsupported packageManager for frontend tests")
        binary = manager.split("@", 1)[0]
    else:
        binary = "npm"
        for directory in dict.fromkeys((cwd, root)):
            found = next((name for lock, name in (
                ("pnpm-lock.yaml", "pnpm"), ("yarn.lock", "yarn"),
                ("bun.lock", "bun"), ("bun.lockb", "bun"), ("package-lock.json", "npm"),
            ) if (directory / lock).exists()), None)
            if found:
                binary = found
                break
    args = f"run {script_name}"
    # Bare Vitest defaults to watch outside CI; retain package hooks while forcing run.
    if tokens == ["vitest"]:
        args += " -- --run" if binary == "npm" else " --run"
    return "frontend-test", {**config, "binary": binary, "args": args, "label": "TEST"}
