"""Publication-only policy used by synchronous native tool hooks."""

from __future__ import annotations

import re
import shlex
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
    command, shell_bodies, data_bodies = _split_heredocs(command)
    # Heredoc data for non-shell consumers (python, a commit message, ...) is
    # not parsed as commands, but hook-disable text in it stays refused.
    if any(_DISABLE.search(body) for body in data_bodies):
        return _blocked("hook_disable", "Publication hooks must remain enabled.")
    for nested in [*shell_bodies, *_substitutions(command)]:
        decision = evaluate_publication_command(nested)
        if decision.blocked:
            return decision
    for segment in _segments(command):
        args = _unwrap(segment)
        if not args:
            continue
        executable = Path(args[0]).name.lower()
        if executable in _READ_ONLY:
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


_READ_ONLY = frozenset({"rg", "grep", "cat", "less", "head", "tail", "echo", "printf"})
_DATA_SINKS = frozenset({"cat", "tee"})
_HEREDOC = re.compile(r"(?<![<\w])<<(-?)[ \t]*(?:'([^'\n]+)'|\"([^\"\n]+)\"|\\?([A-Za-z_][\w.-]*))")
_SEPARATOR_CHARS = frozenset(";&|\n")
_XARGS_VALUE_OPTIONS = frozenset({"-a", "-d", "-E", "-I", "-L", "-n", "-P", "-s", "--arg-file", "--delimiter", "--max-args", "--max-procs", "--max-lines", "--max-chars", "--process-slot-var"})


def _split_heredocs(command: str) -> tuple[str, list[str], list[str]]:
    """Remove heredoc bodies; return (command, shell bodies, data bodies).

    A body written to a file by ``cat``/``tee`` is inert data and is dropped.
    A body fed to a shell (``bash <<EOF`` or ``cat <<EOF | sh``) is returned for
    evaluation as commands; any other consumer's body is returned as data.
    """
    lines = command.split("\n")
    kept: list[str] = []
    shell_bodies: list[str] = []
    data_bodies: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        kept.append(line)
        index += 1
        operators = list(_HEREDOC.finditer(line))
        if not operators:
            continue
        kind = _heredoc_consumer(line, operators[0])
        for match in operators:
            delimiter = match.group(2) or match.group(3) or match.group(4)
            body: list[str] = []
            while index < len(lines):
                candidate = lines[index]
                index += 1
                if (candidate.lstrip("\t") if match.group(1) else candidate) == delimiter:
                    kept.append(candidate)
                    break
                body.append(candidate)
            text = "\n".join(body)
            if match.group(4) and "\\" not in match.group(0):
                # Unquoted delimiter: the shell still expands $(...) in the body.
                shell_bodies.extend(_substitutions(text))
            if kind == "shell":
                shell_bodies.append(text)
            elif kind == "other":
                data_bodies.append(text)
    return "\n".join(kept), shell_bodies, data_bodies


def _heredoc_consumer(line: str, match: re.Match[str]) -> str:
    before = re.split(r"\$\(|`|\(|;|&&|\|\||\|", line[: match.start()])[-1]
    after = line[match.end():]
    pipeline = re.split(r";|&&|\|\|", after)[0]
    try:
        args = _unwrap(shlex.split(before))
    except ValueError:
        return "other"
    executable = Path(args[0]).name.lower() if args else ""
    downstream = [part.strip() for part in pipeline.split("|")[1:]]
    for part in downstream:
        try:
            piped = _unwrap(shlex.split(part))
        except ValueError:
            return "shell"
        if piped and Path(piped[0]).name.lower() in SHELL_EXECUTABLES:
            return "shell"
    if executable in SHELL_EXECUTABLES and shell_exec_args(args[1:]) is None:
        return "shell"
    if executable in _DATA_SINKS:
        segment = before + " " + pipeline.split("|")[0]
        writes_file = ">" in segment if executable == "cat" else any(
            not arg.startswith("-") for arg in args[1:]
        )
        if writes_file and not downstream:
            return "data"
    return "other"


def _substitutions(command: str) -> list[str]:
    """Innermost ``$(...)`` and backtick bodies, evaluated as commands."""
    return [m.group(1) or m.group(2) or "" for m in re.finditer(r"\$\(([^()]*)\)|`([^`]*)`", command)]


def _segments(command: str) -> list[list[str]]:
    """Split on ``; & && || |`` and unquoted newlines; strip ``( { ) }`` grouping."""
    lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|\n")
    lexer.whitespace = " \t\r"
    lexer.whitespace_split = True
    try:
        tokens = list(lexer)
    except ValueError:
        return split_shell_segments(command)
    segments: list[list[str]] = []
    current: list[str] = []
    for token in tokens:
        if token and set(token) <= _SEPARATOR_CHARS:
            if current:
                segments.append(current)
            current = []
            continue
        current.append(token)
    if current:
        segments.append(current)
    cleaned: list[list[str]] = []
    for segment in segments:
        while segment and segment[0] in {"(", "{", "!"}:
            segment = segment[1:]
        if segment:
            segment = [segment[0].lstrip("({"), *segment[1:]]
            segment[-1] = segment[-1].rstrip(")}")
            cleaned.append([token for token in segment if token] or segment)
    return cleaned


def _unwrap(segment: list[str]) -> list[str]:
    args = unwrap_segment(segment)
    while args and Path(args[0]).name.lower() == "xargs":
        index = 1
        while index < len(args) and args[index].startswith("-"):
            index += 2 if args[index] in _XARGS_VALUE_OPTIONS else 1
        args = unwrap_segment(args[index:])
    return args


def _blocked(code: str, message: str) -> CommandGuardDecision:
    # Do not reflect a command: tool input can include embedded credentials.
    return CommandGuardDecision(True, code, message, "publication", "")
