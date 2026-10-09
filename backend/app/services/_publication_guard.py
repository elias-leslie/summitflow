"""Publication-only policy used by synchronous native tool hooks."""

from __future__ import annotations

import re
from pathlib import Path

from ._command_guard_helpers import (
    SHELL_EXECUTABLES,
    CommandGuardDecision,
    normalize_segment,
    shell_exec_args,
    split_shell_segments,
    unwrap_segment,
)

_DISABLE = re.compile(
    r"(?:--no-verify|--dangerously-bypass-hook-trust|--disable-hooks)\b"
    r"|(?:SF_COMMAND_GUARD_DISABLE|GIT_ALLOW_SECRET|SECRETGUARD_DISABLE)\s*=\s*[\"']?1"
    r"|(?:core\.hookspath|hooks\.enabled)\s*="
    r"|(?:--disable\s+hooks|features\.hooks\s*=\s*false)\b"
    r"|(?:git\s+config\b[^\n]*(?:--unset|--remove-section)[^\n]*(?:core\.hooks|hooks))",
    re.IGNORECASE,
)


def evaluate_publication_command(command: str, cwd: str | Path | None = None) -> CommandGuardDecision:
    """Reject ordinary direct publication without redirecting local/read commands.

    This is an accidental-bypass guard, not a security boundary against a user
    who can rewrite hooks or execute arbitrary code under the same UID.
    """
    del cwd
    for segment in split_shell_segments(command):
        args = unwrap_segment(segment)
        if not args:
            continue
        executable = Path(args[0]).name.lower()
        if executable in {"rg", "grep", "cat", "less", "head", "tail", "echo", "printf"}:
            continue
        if _DISABLE.search(normalize_segment(segment)):
            return _blocked("hook_disable", "Publication hooks must remain enabled.")
        if executable == "git" and "config" in args and any(arg.lower() == "core.hookspath" for arg in args) and not any(arg in args for arg in ("--get", "--get-all", "--get-regexp")):
            return _blocked("hook_disable", "Publication hooks must remain enabled.")
        if executable in SHELL_EXECUTABLES:
            nested = shell_exec_args(args[1:])
            if nested:
                decision = evaluate_publication_command(nested)
                if decision.blocked:
                    return decision
        if executable == "git":
            index = 1
            while index < len(args) and args[index].startswith("-"):
                token = args[index]
                index += 2 if token in {"-C", "-c", "--git-dir", "--work-tree", "--config-env", "--namespace", "--exec-path"} else 1
            if index < len(args) and args[index] in {"push", "send-pack"}:
                return _blocked("direct_publication", "Use the canonical ST publication workflow.")
        # Retired tools must still not bypass publication protection when installed.
        if executable == "jj" and "push" in args[1:]:
            return _blocked("direct_publication", "Use the canonical ST publication workflow.")
        if executable == "gh" and len(args) > 2:
            blocked = (
                args[1:3] == ["pr", "merge"]
                or (args[1] == "release" and args[2] in {"create", "edit", "delete", "upload"})
                or (args[1] == "repo" and args[2] in {"create", "delete", "archive", "unarchive", "rename"})
                or (args[1:3] == ["repo", "edit"] and "--visibility" in args)
            )
            if args[1] == "api":
                text = normalize_segment(args[2:]).lower()
                mutation = any(flag in args for flag in ("-f", "-F", "--field", "--raw-field", "--input"))
                mutation = mutation or bool(re.search(r"(?:-X(?:=|\s*)|--method(?:=|\s+))(?:POST|PUT|PATCH|DELETE)\b", normalize_segment(args), re.IGNORECASE))
                publication_endpoint = bool(re.search(r"/(?:git/(?:refs|commits|trees|blobs)|contents|releases|pulls/[^\s]+/merge)\b", text))
                publication_endpoint = publication_endpoint or bool(re.search(r"/(?:branches/[^\s]+/protection|rulesets|(?:[^\s]+/)?archive)\b", text))
                publication_endpoint = publication_endpoint or bool(re.search(r"\b(?:archived|visibility|public)\s*=", text))
                blocked = blocked or (mutation and publication_endpoint) or ("mutation" in text and "graphql" in text)
            if blocked:
                return _blocked("direct_publication", "Use the canonical ST publication workflow.")
    return CommandGuardDecision(False, None, None, None, "")


def _blocked(code: str, message: str) -> CommandGuardDecision:
    # Do not reflect a command: tool input can include embedded credentials.
    return CommandGuardDecision(True, code, message, "publication", "")
