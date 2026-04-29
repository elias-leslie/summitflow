"""Shared shell command guard for managed agent runtimes."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Sequence
from functools import lru_cache
from pathlib import Path
from typing import Any

from ._command_guard_helpers import (
    BASH_INTERCEPT_WORDS as _BASH_INTERCEPT_WORDS,
)
from ._command_guard_helpers import (
    DANGEROUS_PATTERNS as _DANGEROUS_PATTERNS,
)
from ._command_guard_helpers import (
    SHELL_EXECUTABLES as _SHELL_EXECUTABLES,
)
from ._command_guard_helpers import (
    CommandGuardDecision,
    explicit_repo_target,
    force_pushes_shared_main,
    git_checkout_decision,
    git_has_flag,
    git_restore_decision,
    git_revert_decision,
    is_inside_git_repo,
    is_managed_repo_root,
    normalize_repo_paths,
    normalize_segment,
    shell_exec_args,
    split_shell_segments,
    unwrap_segment,
)
from ._command_guard_helpers import (
    repo_root as _repo_root,
)
from .destructive_path_guard import (
    DestructivePathGuardError,
    check_destructive_paths,
    format_guard_report,
    staged_destructive_paths,
)

_ROOT = Path(__file__).resolve().parents[3]
_REGISTRY_PATH = _ROOT / "scripts" / "lib" / "tool-registry.json"
_GIT_GLOBAL_OPTIONS_WITH_VALUE = {
    "-c",
    "--config-env",
    "--exec-path",
    "--git-dir",
    "--namespace",
    "--super-prefix",
    "--work-tree",
}
_GIT_GLOBAL_FLAGS = {
    "--bare",
    "--glob-pathspecs",
    "--icase-pathspecs",
    "--literal-pathspecs",
    "--no-optional-locks",
    "--no-pager",
    "--noglob-pathspecs",
    "--paginate",
    "-p",
}
_GIT_MANAGED_REDIRECTS = {
    "status": ("git_status_redirect", "BLOCKED:git status:Use 'st jj status' or 'st vcs doctor'."),
    "diff": ("git_diff_redirect", "BLOCKED:git diff:Use 'st jj diff'."),
    "log": ("git_log_redirect", "BLOCKED:git log:Use 'st jj log'."),
    "fetch": ("git_fetch_redirect", "BLOCKED:git fetch:Use 'st vcs reconcile' or 'st jj sync'."),
    "pull": ("git_pull_redirect", "BLOCKED:git pull:Use 'st vcs reconcile'."),
    "push": ("git_push_redirect", "BLOCKED:git push:Use 'st commit --push' or 'st jj push'."),
}


class CommandGuardError(RuntimeError):
    """Raised when the shared command guard cannot evaluate safely."""


def get_bash_intercept_words() -> tuple[str, ...]:
    """Return the bash command words that should delegate to the shared guard."""
    return _BASH_INTERCEPT_WORDS


@lru_cache(maxsize=1)
def _load_registry() -> dict[str, Any]:
    try:
        return json.loads(_REGISTRY_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CommandGuardError(f"Failed to load tool registry {_REGISTRY_PATH}: {exc}") from exc


@lru_cache(maxsize=1)
def _compiled_registry() -> dict[str, Any]:
    registry = _load_registry()
    return {
        "wrapper_patterns": tuple(
            re.compile(f"^{p}") for p in registry.get("wrapper_allowlist", [])
        ),
        "tool_patterns": tuple(
            (re.compile(f"^{pat}"), entry.get("redirect_message"), entry.get("component_id"))
            for entry in registry.get("tools", [])
            for pat in entry.get("redirect_patterns", [])
        ),
        "docker_patterns": tuple(
            (re.compile(f"^{e.get('pattern', '')}"), e.get("message"), e.get("component_id"))
            for e in registry.get("docker_redirects", [])
        ),
        "service_patterns": tuple(
            (re.compile(f"^{e.get('pattern', '')}"), e.get("message"), e.get("component_id"))
            for e in registry.get("service_redirects", [])
        ),
    }


def _check_path_conflicts(repo_root: Path, raw_paths: Sequence[str], command: str) -> CommandGuardDecision | None:
    paths = normalize_repo_paths(repo_root, raw_paths)
    if not paths:
        return None
    try:
        decision = check_destructive_paths(repo_root, paths)
    except DestructivePathGuardError as exc:
        return CommandGuardDecision(
            blocked=True, code="ownership_error", message=str(exc), source="ownership", command=command,
        )
    if not decision.blocked:
        return None
    return CommandGuardDecision(
        blocked=True, code="ownership_conflict", message=format_guard_report(decision),
        source="ownership", command=command,
    )


def _registry_redirect_decision(segment: Sequence[str], cwd: Path) -> CommandGuardDecision | None:
    segment_text = normalize_segment(segment)
    if not segment_text:
        return None
    unwrapped = unwrap_segment(segment)
    match_text = normalize_segment(unwrapped or list(segment))
    reg = _compiled_registry()
    if any(p.search(match_text) for p in reg["wrapper_patterns"]):
        return None
    for pattern, message, component_id in (*reg["tool_patterns"], *reg["docker_patterns"]):
        if pattern.search(match_text):
            return CommandGuardDecision(
                blocked=True, code="redirect",
                message=str(message or "").strip() or "Use the canonical shared wrapper.",
                source=str(component_id or "registry"), command=segment_text,
            )
    for pattern, message, component_id in reg["service_patterns"]:
        if not pattern.search(match_text):
            continue
        first = unwrapped[0] if unwrapped else (next(iter(segment)) if segment else "")
        if (
            first in {"rm", "rmdir", "find"}
            and not is_inside_git_repo(cwd)
            and not explicit_repo_target(unwrapped or list(segment), cwd)
        ):
            continue
        return CommandGuardDecision(
            blocked=True, code="redirect",
            message=str(message or "").strip() or "Use the canonical shared wrapper.",
            source=str(component_id or "registry"), command=segment_text,
        )
    return None


def _dangerous_decision(segment: Sequence[str]) -> CommandGuardDecision | None:
    normalized = normalize_segment(unwrap_segment(segment) or list(segment))
    for pattern, message in _DANGEROUS_PATTERNS:
        if pattern.search(normalized.lower()):
            return CommandGuardDecision(
                blocked=True, code="dangerous", message=message,
                source="dangerous", command=normalize_segment(segment),
            )
    return None


def _nested_shell_decision(segment: Sequence[str], cwd: Path) -> CommandGuardDecision | None:
    unwrapped = unwrap_segment(segment)
    if not unwrapped or unwrapped[0] not in _SHELL_EXECUTABLES:
        return None
    nested = shell_exec_args(unwrapped[1:])
    return evaluate_shell_command(nested, cwd) if nested else None


def _make_path_conflict_fn(root: Path | None) -> Any:
    def check(paths: Sequence[str], command: str) -> CommandGuardDecision | None:
        return _check_path_conflicts(root, paths, command) if root else None
    return check


def _git_invocation(segment: Sequence[str], cwd: Path) -> tuple[str, list[str], Path] | None:
    unwrapped = unwrap_segment(segment)
    if len(unwrapped) < 2 or unwrapped[0] != "git":
        return None

    index = 1
    git_cwd = cwd
    while index < len(unwrapped):
        token = unwrapped[index]
        if token == "-C" and index + 1 < len(unwrapped):
            target = Path(unwrapped[index + 1]).expanduser()
            git_cwd = (target if target.is_absolute() else git_cwd / target).resolve()
            index += 2
            continue
        if token.startswith("-C") and token != "-C":
            target = Path(token[2:]).expanduser()
            git_cwd = (target if target.is_absolute() else git_cwd / target).resolve()
            index += 1
            continue
        if token in _GIT_GLOBAL_OPTIONS_WITH_VALUE and index + 1 < len(unwrapped):
            index += 2
            continue
        if any(token.startswith(f"{option}=") for option in _GIT_GLOBAL_OPTIONS_WITH_VALUE):
            index += 1
            continue
        if token in _GIT_GLOBAL_FLAGS:
            index += 1
            continue
        if token.startswith("-"):
            index += 1
            continue
        return token, unwrapped[index + 1 :], git_cwd
    return None


def _git_decision(segment: Sequence[str], cwd: Path) -> CommandGuardDecision | None:
    parsed = _git_invocation(segment, cwd)
    if parsed is None:
        return None
    subcommand, args, git_cwd = parsed
    segment_text = normalize_segment(segment)
    root = _repo_root(git_cwd)
    check_fn = _make_path_conflict_fn(root)

    if subcommand == "reset" and git_has_flag(args, "--hard"):
        return CommandGuardDecision(
            blocked=True, code="git_reset_hard",
            message="BLOCKED:git reset --hard:Destroys uncommitted work without recovery. Commit or stash first.",
            source="git", command=segment_text,
        )
    if subcommand == "clean" and (
        any(set(token) >= {"f", "d"} for token in args if token.startswith("-"))
        or ("-f" in args and "-d" in args)
        or ("-d" in args and "-f" in args)
    ):
        return CommandGuardDecision(
            blocked=True, code="git_clean_fd",
            message="BLOCKED:git clean -fd:Permanently deletes untracked files. Preview with 'git clean -n' first.",
            source="git", command=segment_text,
        )
    if subcommand == "push" and force_pushes_shared_main(args):
        return CommandGuardDecision(
            blocked=True, code="git_force_push_main",
            message="BLOCKED:git push --force main:Force push to main/master destroys shared history.",
            source="git", command=segment_text,
        )
    if subcommand == "commit":
        return CommandGuardDecision(
            blocked=True, code="git_commit_redirect",
            message="BLOCKED:git commit:Use 'st commit --push --message \"...\"' instead of raw git commit.",
            source="git", command=segment_text,
        )
    if is_managed_repo_root(root) and subcommand in _GIT_MANAGED_REDIRECTS:
        code, message = _GIT_MANAGED_REDIRECTS[subcommand]
        return CommandGuardDecision(
            blocked=True, code=code, message=message,
            source="git", command=segment_text,
        )
    if subcommand == "checkout":
        return git_checkout_decision(args, segment_text, root, check_fn)
    if subcommand == "restore":
        return git_restore_decision(args, segment_text, root, check_fn)
    if subcommand == "rm":
        explicit = [token for token in args[args.index("--") + 1:] if token and not token.startswith("-")] if "--" in args else []
        paths = [token for token in args if token and not token.startswith("-")]
        return check_fn(explicit or paths, segment_text)
    if subcommand == "revert":
        return git_revert_decision(args, segment_text, root, check_fn, CommandGuardError)
    return None


def _jj_decision(segment: Sequence[str], cwd: Path) -> CommandGuardDecision | None:
    unwrapped = unwrap_segment(segment)
    if not unwrapped or unwrapped[0] != "jj":
        return None
    root = _repo_root(cwd)
    if not is_managed_repo_root(root):
        return None
    return CommandGuardDecision(
        blocked=True,
        code="jj_redirect",
        message="BLOCKED:jj:Use 'st jj ...' so no-pager, check, and publish policy applies.",
        source="jj",
        command=normalize_segment(segment),
    )


def evaluate_shell_command(command: str, cwd: str | Path | None = None) -> CommandGuardDecision:
    """Evaluate a shell command string against shared redirects and git safety rules."""
    working_dir = Path(cwd or ".").expanduser().resolve()
    for segment in split_shell_segments(command):
        decision = _dangerous_decision(segment)
        if decision:
            return decision
        decision = _registry_redirect_decision(segment, working_dir)
        if decision:
            return decision
        decision = _nested_shell_decision(segment, working_dir)
        if decision and decision.blocked:
            return decision
        decision = _git_decision(segment, working_dir)
        if decision:
            return decision
        decision = _jj_decision(segment, working_dir)
        if decision:
            return decision
    return CommandGuardDecision(blocked=False, code=None, message=None, source=None, command=command)


def staged_destructive_decision(repo_root: str | Path | None = None) -> CommandGuardDecision:
    """Evaluate staged git deletes/renames against live ownership."""
    target_root = Path(repo_root or ".").resolve()
    try:
        destructive_paths = staged_destructive_paths(target_root)
    except DestructivePathGuardError as exc:
        return CommandGuardDecision(
            blocked=True, code="ownership_error", message=str(exc),
            source="ownership", command=str(target_root),
        )
    if not destructive_paths:
        return CommandGuardDecision(False, None, None, None, str(target_root))
    try:
        decision = check_destructive_paths(target_root, destructive_paths)
    except DestructivePathGuardError as exc:
        return CommandGuardDecision(
            blocked=True, code="ownership_error", message=str(exc),
            source="ownership", command=str(target_root),
        )
    if not decision.blocked:
        return CommandGuardDecision(False, None, None, None, str(target_root))
    return CommandGuardDecision(
        blocked=True, code="ownership_conflict", message=format_guard_report(decision),
        source="ownership", command=str(target_root),
    )


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shell-command", help="Shell command string to inspect")
    parser.add_argument("--cwd", default=".", help="Working directory for command evaluation")
    parser.add_argument("--staged-git", action="store_true", help="Inspect staged destructive git paths")
    parser.add_argument("--emit-intercept-words", action="store_true", help="Print bash intercept words")
    parser.add_argument("--json", action="store_true", help="Emit JSON output")
    args = parser.parse_args(argv)
    enabled = sum(bool(v) for v in (args.shell_command, args.staged_git, args.emit_intercept_words))
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
