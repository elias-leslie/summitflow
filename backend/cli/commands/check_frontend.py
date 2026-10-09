"""Resolve aggregate frontend tests from the project's package manifest."""

from __future__ import annotations

import json
import re
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


def _vitest_config(cwd: Path, config: dict[str, object]) -> dict[str, object]:
    """Select cache-free config loading only when the installed tools support it.

    The full receipt binds these installed CLI/runtime bytes. Inspect the
    actual local option and Vite dispatch, rather than guessing from a fleet
    version or invoking a package manager to discover a tool.
    """
    if config.get("binary", "vitest") != "vitest" or shlex.split(str(config.get("args") or "")) != ["run"]:
        return config
    modules = cwd / "node_modules"
    executable = modules / ".bin" / "vitest"
    try:
        package = (modules / "vitest").resolve(strict=True)
        if not package.is_relative_to(modules.resolve()) or _manifest(package / "package.json").get("name") != "vitest":
            return config
        launcher = package / "vitest.mjs"
        if executable.resolve(strict=True) != launcher.resolve(strict=True):
            # pnpm launches through either the package link or its versioned
            # virtual store. Both must resolve to this inspected local launcher.
            shim = re.compile(
                r'\bexec[^\n]*"\$basedir(?:_win)?/(\.\./(?:vitest|\.pnpm/vitest@[^/"\n]+/node_modules/vitest)/vitest\.mjs)"\s+"\$@"'
            )
            targets = shim.findall(executable.read_text(encoding="utf-8"))
            if (executable.is_symlink() or not targets
                    or any((executable.parent / target).resolve(strict=True) != launcher.resolve(strict=True) for target in targets)):
                return config
        option = re.compile(r"\bconfigLoader:\s*\{[^}]*\brunner\b[^}]*\}")
        cache = re.compile(r"\bcache:\s*\{\s*description:\s*['\"]Enable cache['\"]")
        declarations = [path.read_text(encoding="utf-8") for path in (package / "dist" / "chunks").glob("cac*.js")]
        if not any(option.search(text) and cache.search(text) for text in declarations):
            return config
        # Follow Node's nearest package-directory lookup, including nested and
        # pnpm sibling dependencies, without resolving a different global Vite.
        vite = next((path for ancestor in (package, *package.parents)
                     if (path := ancestor / "node_modules" / "vite" / "package.json").is_file()), None)
        if vite is None or not vite.resolve().is_relative_to(modules.resolve()) or _manifest(vite).get("name") != "vite":
            return config
        loader = re.compile(r"configLoader\s*===\s*['\"]runner['\"]\s*\?\s*runnerImportConfigFile\b")
        if not any(loader.search(path.read_text(encoding="utf-8")) for path in (vite.parent / "dist" / "node" / "chunks").glob("*.js")):
            return config
    except (OSError, UnicodeError, ValueError):
        return config
    return {**config, "args": "run --configLoader runner --cache=false"}


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
                return "vitest", _vitest_config(cwd, config)
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
        return "vitest", _vitest_config(cwd, config)
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
