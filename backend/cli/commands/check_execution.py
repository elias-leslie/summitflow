"""Pure tool-execution helpers for st check."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path


def adjusted_tool_args(
    name: str,
    base_args: list[str],
    extra_args: list[str],
) -> tuple[list[str], list[str]]:
    if name == "biome" and any(not arg.startswith("-") for arg in extra_args):
        base_args = [arg for arg in base_args if arg != "."]
    if name != "pytest":
        return base_args, extra_args

    has_path_arg = any(arg and not arg.startswith("-") for arg in extra_args)
    has_cov_control = any(arg == "--no-cov" or arg.startswith("--cov") for arg in extra_args)
    if has_path_arg and not has_cov_control:
        return base_args, ["--no-cov", *extra_args]
    return base_args, extra_args


def tool_env(root: Path, environ: Mapping[str, str], name: str | None = None) -> dict[str, str]:
    env = dict(environ)
    paths = [
        str(candidate)
        for candidate in (
            root / "backend" / ".venv" / "bin",
            root / ".venv" / "bin",
            root / "frontend" / "node_modules" / ".bin",
            root / "node_modules" / ".bin",
        )
        if candidate.exists()
    ]
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
