"""Shared shell command guard for managed agent runtimes."""

from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from .destructive_path_guard import (
    DestructivePathGuardError,
    check_destructive_paths,
    format_guard_report,
    staged_destructive_paths,
)

_ROOT = Path(__file__).resolve().parents[3]
_REGISTRY_PATH = _ROOT / "scripts" / "lib" / "tool-registry.json"
_GIT_REPO_CHECK = ["git", "rev-parse", "--is-inside-work-tree"]
_BASH_INTERCEPT_WORDS = (
    "git",
    "python",
    "python3",
    "pytest",
    "mypy",
    "ty",
    "ruff",
    "biome",
    "npx",
    "pnpm",
    "npm",
    "vitest",
    "sqlfluff",
    "squawk",
    "coderabbit",
    "cr",
    "docker",
    "env",
    "nohup",
    "nice",
    "stdbuf",
    "timeout",
    "bash",
    "sh",
    "systemctl",
    "pkill",
    "killall",
    "uvicorn",
    "gunicorn",
    "next",
    "psql",
    "rm",
    "rmdir",
    "find",
)
_SHELL_SEPARATORS = frozenset({";", "&&", "||", "|"})
_ASSIGNMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=.*$")
_COMMAND_WRAPPERS = frozenset({"command", "builtin", "nohup"})
_OPTION_WRAPPERS = frozenset({"nice", "stdbuf", "timeout"})
_GIT_ABORT_ACTIONS = frozenset({"--abort", "--continue", "--quit", "--skip"})
_SHELL_EXECUTABLES = frozenset({"bash", "sh", "zsh", "ksh"})
_DANGEROUS_PATTERNS = (
    (
        re.compile(r"^rm\s+-[^\n]*r[^\n]*\s+(/\*?|\\\*)($|\s)"),
        "BLOCKED:rm -r /:Recursive root deletion is never allowed.",
    ),
    (
        re.compile(r"^mkfs(\.\S+)?(\s|$)"),
        "BLOCKED:mkfs:Formatting filesystems is never allowed.",
    ),
    (
        re.compile(r"^dd\b.*\bif=/dev/zero\b"),
        "BLOCKED:dd if=/dev/zero:Raw disk overwrite is never allowed.",
    ),
    (
        re.compile(r"^systemctl\s+(stop|disable)\b"),
        "BLOCKED:systemctl stop/disable:Do not stop or disable services directly.",
    ),
)


class CommandGuardError(RuntimeError):
    """Raised when the shared command guard cannot evaluate safely."""


@dataclass(frozen=True)
class CommandGuardDecision:
    """Result of evaluating one shell command."""

    blocked: bool
    code: str | None
    message: str | None
    source: str | None
    command: str

    def to_dict(self) -> dict[str, object]:
        return {
            "blocked": self.blocked,
            "code": self.code,
            "message": self.message,
            "source": self.source,
            "command": self.command,
        }


def _normalize_segment(segment: Sequence[str]) -> str:
    return shlex.join(list(segment))


def _split_shell_segments(command: str) -> list[list[str]]:
    lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|")
    lexer.whitespace_split = True
    segments: list[list[str]] = []
    current: list[str] = []
    try:
        tokens = list(lexer)
    except ValueError:
        return [[command]]
    for token in tokens:
        if token in _SHELL_SEPARATORS:
            if current:
                segments.append(current)
                current = []
            continue
        current.append(token)
    if current:
        segments.append(current)
    return segments


def _unwrap_segment(segment: Sequence[str]) -> list[str]:
    tokens = list(segment)
    idx = 0
    while idx < len(tokens) and _ASSIGNMENT_RE.match(tokens[idx]):
        idx += 1
    tokens = tokens[idx:]
    while tokens:
        lead = tokens[0]
        if lead == "env":
            idx = 1
            while idx < len(tokens):
                token = tokens[idx]
                if token == "-u" and idx + 1 < len(tokens):
                    idx += 2
                    continue
                if token.startswith("-"):
                    idx += 1
                    continue
                if _ASSIGNMENT_RE.match(token):
                    idx += 1
                    continue
                break
            tokens = tokens[idx:]
            continue
        if lead in _COMMAND_WRAPPERS:
            tokens = tokens[1:]
            continue
        if lead in _OPTION_WRAPPERS:
            idx = 1
            while idx < len(tokens) and tokens[idx].startswith("-"):
                option = tokens[idx]
                idx += 1
                if option in {"-n", "--adjustment", "-s", "--signal", "-k"} and idx < len(tokens):
                    idx += 1
            tokens = tokens[idx:]
            continue
        break
    return tokens


@lru_cache(maxsize=1)
def _load_registry() -> dict[str, Any]:
    try:
        return json.loads(_REGISTRY_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CommandGuardError(f"Failed to load tool registry {_REGISTRY_PATH}: {exc}") from exc


@lru_cache(maxsize=1)
def _compiled_registry() -> dict[str, Any]:
    registry = _load_registry()
    wrapper_patterns = [re.compile(f"^{pattern}") for pattern in registry.get("wrapper_allowlist", [])]
    tool_patterns = [
        (
            re.compile(f"^{pattern}"),
            entry.get("redirect_message"),
            entry.get("component_id"),
        )
        for entry in registry.get("tools", [])
        for pattern in entry.get("redirect_patterns", [])
    ]
    docker_patterns = [
        (
            re.compile(f"^{entry.get('pattern', '')}"),
            entry.get("message"),
            entry.get("component_id"),
        )
        for entry in registry.get("docker_redirects", [])
    ]
    service_patterns = [
        (
            re.compile(f"^{entry.get('pattern', '')}"),
            entry.get("message"),
            entry.get("component_id"),
        )
        for entry in registry.get("service_redirects", [])
    ]
    return {
        "wrapper_patterns": tuple(wrapper_patterns),
        "tool_patterns": tuple(tool_patterns),
        "docker_patterns": tuple(docker_patterns),
        "service_patterns": tuple(service_patterns),
    }


def get_bash_intercept_words() -> tuple[str, ...]:
    """Return the bash command words that should delegate to the shared guard."""
    return _BASH_INTERCEPT_WORDS


def _is_wrapper_command(segment_text: str) -> bool:
    return any(pattern.search(segment_text) for pattern in _compiled_registry()["wrapper_patterns"])


def _is_inside_git_repo(path: Path) -> bool:
    try:
        result = subprocess.run(
            _GIT_REPO_CHECK,
            cwd=path,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return False
    return result.returncode == 0 and result.stdout.strip() == "true"


def _explicit_repo_target(tokens: Sequence[str], cwd: Path) -> bool:
    if not tokens:
        return False
    command = tokens[0]
    if command in {"rm", "rmdir"}:
        for token in tokens[1:]:
            if token.startswith("-"):
                continue
            target = Path(token).expanduser()
            if not target.is_absolute():
                target = (cwd / target).resolve()
            return _is_inside_git_repo(target.parent if not target.exists() else target)
        return False
    if command == "find":
        for token in tokens[1:]:
            if token == "-delete":
                break
            if token.startswith("-"):
                continue
            target = Path(token).expanduser()
            if not target.is_absolute():
                target = (cwd / target).resolve()
            if _is_inside_git_repo(target):
                return True
        return False
    return False


def _registry_redirect_decision(segment: Sequence[str], cwd: Path) -> CommandGuardDecision | None:
    segment_text = _normalize_segment(segment)
    if not segment_text:
        return None
    unwrapped = _unwrap_segment(segment)
    match_text = _normalize_segment(unwrapped or segment)
    if _is_wrapper_command(match_text):
        return None

    registry = _compiled_registry()
    for pattern, message, component_id in (
        *registry["tool_patterns"],
        *registry["docker_patterns"],
    ):
        if pattern.search(match_text):
            return CommandGuardDecision(
                blocked=True,
                code="redirect",
                message=str(message or "").strip() or "Use the canonical shared wrapper.",
                source=str(component_id or "registry"),
                command=segment_text,
            )

    for pattern, message, component_id in registry["service_patterns"]:
        if not pattern.search(match_text):
            continue
        first = unwrapped[0] if unwrapped else (segment[0] if segment else "")
        if (
            first in {"rm", "rmdir", "find"}
            and not _is_inside_git_repo(cwd)
            and not _explicit_repo_target(unwrapped or segment, cwd)
        ):
            continue
        return CommandGuardDecision(
            blocked=True,
            code="redirect",
            message=str(message or "").strip() or "Use the canonical shared wrapper.",
            source=str(component_id or "registry"),
            command=segment_text,
        )
    return None


def _git_has_flag(args: Sequence[str], *flags: str) -> bool:
    return any(arg in flags or any(arg.startswith(f"{flag}=") for flag in flags) for arg in args)


def _dangerous_decision(segment: Sequence[str]) -> CommandGuardDecision | None:
    normalized = _normalize_segment(_unwrap_segment(segment) or segment)
    lowered = normalized.lower()
    for pattern, message in _DANGEROUS_PATTERNS:
        if pattern.search(lowered):
            return CommandGuardDecision(
                blocked=True,
                code="dangerous",
                message=message,
                source="dangerous",
                command=_normalize_segment(segment),
            )
    return None


def _shell_exec_args(args: Sequence[str]) -> str | None:
    idx = 0
    while idx < len(args):
        arg = args[idx]
        if arg == "-c" and idx + 1 < len(args):
            return args[idx + 1]
        if arg.startswith("-") and "c" in arg[1:] and idx + 1 < len(args):
            return args[idx + 1]
        idx += 1
    return None


def _nested_shell_decision(segment: Sequence[str], cwd: Path) -> CommandGuardDecision | None:
    unwrapped = _unwrap_segment(segment)
    if not unwrapped or unwrapped[0] not in _SHELL_EXECUTABLES:
        return None
    nested = _shell_exec_args(unwrapped[1:])
    if not nested:
        return None
    return evaluate_shell_command(nested, cwd)


def _repo_root(cwd: Path) -> Path | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    root = result.stdout.strip()
    return Path(root).resolve() if root else None


def _normalize_repo_paths(repo_root: Path, raw_paths: Sequence[str]) -> list[str]:
    normalized: list[str] = []
    for raw in raw_paths:
        path = raw.strip()
        if not path:
            continue
        target = Path(path).expanduser()
        if target.is_absolute():
            try:
                target = target.resolve().relative_to(repo_root)
            except (OSError, ValueError):
                continue
            normalized.append(target.as_posix())
            continue
        normalized.append(path)
    return normalized


def _check_path_conflicts(repo_root: Path, raw_paths: Sequence[str], command: str) -> CommandGuardDecision | None:
    paths = _normalize_repo_paths(repo_root, raw_paths)
    if not paths:
        return None
    try:
        decision = check_destructive_paths(repo_root, paths)
    except DestructivePathGuardError as exc:
        return CommandGuardDecision(
            blocked=True,
            code="ownership_error",
            message=str(exc),
            source="ownership",
            command=command,
        )
    if not decision.blocked:
        return None
    return CommandGuardDecision(
        blocked=True,
        code="ownership_conflict",
        message=format_guard_report(decision),
        source="ownership",
        command=command,
    )


def _git_paths_after_double_dash(args: Sequence[str]) -> list[str]:
    if "--" in args:
        idx = args.index("--")
        return [token for token in args[idx + 1 :] if not token.startswith("-")]
    return []


def _strip_git_option_values(args: Sequence[str], *, value_flags: set[str]) -> list[str]:
    stripped: list[str] = []
    idx = 0
    while idx < len(args):
        token = args[idx]
        if token in value_flags:
            idx += 2
            continue
        if any(token.startswith(f"{flag}=") for flag in value_flags):
            idx += 1
            continue
        stripped.append(token)
        idx += 1
    return stripped


def _git_restore_paths(args: Sequence[str]) -> tuple[list[str], bool]:
    has_staged = _git_has_flag(args, "--staged")
    has_worktree = _git_has_flag(args, "--worktree")
    if has_staged and not has_worktree:
        return [], True
    cleaned = _strip_git_option_values(args, value_flags={"--source", "--pathspec-from-file"})
    explicit = _git_paths_after_double_dash(cleaned)
    if explicit:
        return explicit, False
    paths: list[str] = []
    for token in cleaned:
        if token.startswith("-"):
            continue
        paths.append(token)
    return paths, False


def _git_rm_paths(args: Sequence[str]) -> list[str]:
    explicit = _git_paths_after_double_dash(args)
    if explicit:
        return explicit
    return [token for token in args if token and not token.startswith("-")]


def _git_revert_paths(repo_root: Path, args: Sequence[str]) -> list[str]:
    cleaned = _strip_git_option_values(
        args,
        value_flags={"-m", "--mainline", "-X", "--strategy-option", "--strategy"},
    )
    revisions = [arg for arg in cleaned if arg and not arg.startswith("-")]
    if not revisions:
        return []
    try:
        result = subprocess.run(
            ["git", "show", "--format=", "--name-only", "--no-renames", *revisions],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise CommandGuardError(f"Failed to inspect git revert paths for {' '.join(revisions)}: {exc}") from exc
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _force_pushes_shared_main(args: Sequence[str]) -> bool:
    force = _git_has_flag(args, "-f", "--force")
    if not force:
        return False
    return any(
        arg in {"main", "master", "origin/main", "origin/master"}
        or arg.endswith(":main")
        or arg.endswith(":master")
        for arg in args
    )


def _git_decision(segment: Sequence[str], cwd: Path) -> CommandGuardDecision | None:
    unwrapped = _unwrap_segment(segment)
    if len(unwrapped) < 2 or unwrapped[0] != "git":
        return None
    subcommand = unwrapped[1]
    args = unwrapped[2:]
    segment_text = _normalize_segment(segment)
    repo_root = _repo_root(cwd)

    if subcommand == "reset" and _git_has_flag(args, "--hard"):
        return CommandGuardDecision(
            blocked=True,
            code="git_reset_hard",
            message="BLOCKED:git reset --hard:Destroys uncommitted work without recovery. Commit or stash first.",
            source="git",
            command=segment_text,
        )
    if subcommand == "clean" and (
        any(set(token) >= {"f", "d"} for token in args if token.startswith("-"))
        or ("-f" in args and "-d" in args)
        or ("-d" in args and "-f" in args)
    ):
        return CommandGuardDecision(
            blocked=True,
            code="git_clean_fd",
            message="BLOCKED:git clean -fd:Permanently deletes untracked files. Preview with 'git clean -n' first.",
            source="git",
            command=segment_text,
        )
    if subcommand == "push" and _force_pushes_shared_main(args):
        return CommandGuardDecision(
            blocked=True,
            code="git_force_push_main",
            message="BLOCKED:git push --force main:Force push to main/master destroys shared history.",
            source="git",
            command=segment_text,
        )
    if subcommand == "commit":
        return CommandGuardDecision(
            blocked=True,
            code="git_commit_redirect",
            message="BLOCKED:git commit:Use 'commit.sh --push --msg \"...\"' instead of raw git commit.",
            source="git",
            command=segment_text,
        )
    if subcommand == "checkout":
        if args[:1] == ["."] or args[:2] == ["--", "."]:
            return CommandGuardDecision(
                blocked=True,
                code="git_checkout_all",
                message="BLOCKED:git checkout .:Discards all uncommitted changes at once.",
                source="git",
                command=segment_text,
            )
        paths = _git_paths_after_double_dash(args)
        if paths:
            if "." in paths:
                return CommandGuardDecision(
                    blocked=True,
                    code="git_checkout_all",
                    message="BLOCKED:git checkout .:Discards all uncommitted changes at once.",
                    source="git",
                    command=segment_text,
                )
            if repo_root:
                return _check_path_conflicts(repo_root, paths, segment_text)
        return None
    if subcommand == "restore":
        if args[:1] == ["."]:
            return CommandGuardDecision(
                blocked=True,
                code="git_restore_all",
                message="BLOCKED:git restore .:Discards all uncommitted changes at once.",
                source="git",
                command=segment_text,
            )
        paths, staging_only = _git_restore_paths(args)
        if staging_only:
            return None
        if "." in paths:
            return CommandGuardDecision(
                blocked=True,
                code="git_restore_all",
                message="BLOCKED:git restore .:Discards all uncommitted changes at once.",
                source="git",
                command=segment_text,
            )
        if repo_root:
            return _check_path_conflicts(repo_root, paths, segment_text)
        return None
    if subcommand == "rm":
        if repo_root:
            return _check_path_conflicts(repo_root, _git_rm_paths(args), segment_text)
        return None
    if subcommand == "revert":
        if any(flag in args for flag in _GIT_ABORT_ACTIONS):
            return None
        if repo_root:
            paths = _git_revert_paths(repo_root, args)
            return _check_path_conflicts(repo_root, paths, segment_text)
        return None
    return None


def evaluate_shell_command(command: str, cwd: str | Path | None = None) -> CommandGuardDecision:
    """Evaluate a shell command string against shared redirects and git safety rules."""
    working_dir = Path(cwd or ".").expanduser().resolve()
    for segment in _split_shell_segments(command):
        dangerous_decision = _dangerous_decision(segment)
        if dangerous_decision:
            return dangerous_decision
        registry_decision = _registry_redirect_decision(segment, working_dir)
        if registry_decision:
            return registry_decision
        nested_decision = _nested_shell_decision(segment, working_dir)
        if nested_decision and nested_decision.blocked:
            return nested_decision
        git_decision = _git_decision(segment, working_dir)
        if git_decision:
            return git_decision
    return CommandGuardDecision(
        blocked=False,
        code=None,
        message=None,
        source=None,
        command=command,
    )


def staged_destructive_decision(repo_root: str | Path | None = None) -> CommandGuardDecision:
    """Evaluate staged git deletes/renames against live ownership."""
    target_root = Path(repo_root or ".").resolve()
    try:
        destructive_paths = staged_destructive_paths(target_root)
    except DestructivePathGuardError as exc:
        return CommandGuardDecision(
            blocked=True,
            code="ownership_error",
            message=str(exc),
            source="ownership",
            command=str(target_root),
        )
    if not destructive_paths:
        return CommandGuardDecision(False, None, None, None, str(target_root))
    try:
        decision = check_destructive_paths(target_root, destructive_paths)
    except DestructivePathGuardError as exc:
        return CommandGuardDecision(
            blocked=True,
            code="ownership_error",
            message=str(exc),
            source="ownership",
            command=str(target_root),
        )
    if not decision.blocked:
        return CommandGuardDecision(False, None, None, None, str(target_root))
    return CommandGuardDecision(
        blocked=True,
        code="ownership_conflict",
        message=format_guard_report(decision),
        source="ownership",
        command=str(target_root),
    )


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shell-command", help="Shell command string to inspect")
    parser.add_argument("--cwd", default=".", help="Working directory for command evaluation")
    parser.add_argument("--staged-git", action="store_true", help="Inspect staged destructive git paths")
    parser.add_argument("--emit-intercept-words", action="store_true", help="Print bash intercept words")
    parser.add_argument("--json", action="store_true", help="Emit JSON output")
    args = parser.parse_args(argv)
    enabled = sum(bool(value) for value in (args.shell_command, args.staged_git, args.emit_intercept_words))
    if enabled != 1:
        parser.error("pass exactly one of --shell-command, --staged-git, or --emit-intercept-words")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.emit_intercept_words:
        print(" ".join(get_bash_intercept_words()))
        return 0
    try:
        decision = (
            staged_destructive_decision(args.cwd)
            if args.staged_git
            else evaluate_shell_command(str(args.shell_command), args.cwd)
        )
    except CommandGuardError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(decision.to_dict(), sort_keys=True))
    elif decision.blocked and decision.message:
        print(decision.message)
    return 2 if decision.blocked else 0


if __name__ == "__main__":
    raise SystemExit(main())
