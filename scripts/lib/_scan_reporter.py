from __future__ import annotations

import json
import sys
from dataclasses import asdict

from _scan_models import Finding


_ALLOWLIST_HINT = (
    "If a finding is intentional, add a narrow regex to .sensitive-scan-allowlist "
    "or ~/.config/git/hooks/sensitive-allowlist.txt after review."
)
_WARN_HINT = (
    "Allow intentional cases with a narrow regex in .sensitive-scan-allowlist "
    "or ~/.config/git/hooks/sensitive-allowlist.txt."
)


def _mode_label(mode: str) -> str:
    return {"runtime": "Write", "staged": "Commit"}.get(mode, "Push")


def summarize(findings: list[Finding], mode: str) -> str:
    label = _mode_label(mode)
    blocked = [f for f in findings if f.severity == "block"]
    warned = [f for f in findings if f.severity == "warn"]
    if blocked:
        return f"{label} blocked: {blocked[0].description}"
    if warned:
        return f"{label} warning: {warned[0].description}"
    return f"{label} clean"


def emit_json(findings: list[Finding], mode: str) -> None:
    status = "block" if any(f.severity == "block" for f in findings) else ("warn" if findings else "ok")
    print(json.dumps({"mode": mode, "status": status, "summary": summarize(findings, mode), "findings": [asdict(f) for f in findings]}))


def _fmt_location(f: Finding) -> str:
    return f"{f.path}:{f.line_no}" if f.line_no else f.path


def _print_finding_line(prefix: str, f: Finding) -> None:
    print(f"  {prefix} {f.rule_id} {_fmt_location(f)}: {f.description}", file=sys.stderr)
    print(f"    {f.excerpt}", file=sys.stderr)


def _print_blocked(blocked: list[Finding], warned: list[Finding], label: str, mode: str) -> int:
    print(f"{label} blocked: sensitive content requires review.", file=sys.stderr)
    for f in blocked:
        _print_finding_line("BLOCK", f)
    if warned:
        print("", file=sys.stderr)
        print("Additional review-only findings:", file=sys.stderr)
        for f in warned:
            _print_finding_line("WARN ", f)
    if mode != "runtime":
        print("", file=sys.stderr)
        print(_ALLOWLIST_HINT, file=sys.stderr)
    return 1


def _print_warned(warned: list[Finding], label: str) -> int:
    print(f"{label} warning: review sensitive content before continuing.", file=sys.stderr)
    for f in warned:
        _print_finding_line("WARN ", f)
    print(_WARN_HINT, file=sys.stderr)
    return 0


def print_findings(findings: list[Finding], mode: str) -> int:
    blocked = [f for f in findings if f.severity == "block"]
    warned = [f for f in findings if f.severity == "warn"]
    if not blocked and not warned:
        return 0
    label = _mode_label(mode)
    print("", file=sys.stderr)
    if blocked:
        return _print_blocked(blocked, warned, label, mode)
    return _print_warned(warned, label)
