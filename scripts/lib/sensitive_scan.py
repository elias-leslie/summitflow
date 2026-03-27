#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


INLINE_ALLOW_MARKER = "sensitive-scan:allow"
GLOBAL_ALLOWLIST = Path.home() / ".config" / "git" / "hooks" / "sensitive-allowlist.txt"
REPO_ALLOWLIST = ".sensitive-scan-allowlist"
PATTERN_FILE = Path(__file__).with_name("sensitive-patterns.json")


@dataclass(frozen=True)
class Rule:
    rule_id: str
    description: str
    pattern: re.Pattern[str]
    severity: str
    runtime_block: bool = False


@dataclass(frozen=True)
class Finding:
    severity: str
    rule_id: str
    description: str
    path: str
    line_no: int | None
    excerpt: str


def load_rules(pattern_file: Path) -> list[Rule]:
    data = json.loads(pattern_file.read_text(encoding="utf-8"))
    rules: list[Rule] = []
    for severity_key in ("block_rules", "warn_rules"):
        severity = "block" if severity_key == "block_rules" else "warn"
        for item in data.get(severity_key, []):
            rules.append(Rule(
                rule_id=item["id"],
                description=item["description"],
                pattern=re.compile(item["pattern"]),
                severity=severity,
                runtime_block=bool(item.get("runtime_block", False)),
            ))
    return rules


def load_allowlist(repo_root: Path | None) -> list[re.Pattern[str]]:
    paths = [GLOBAL_ALLOWLIST] + ([repo_root / REPO_ALLOWLIST] if repo_root else [])
    patterns: list[re.Pattern[str]] = []
    for path in paths:
        if not path.exists():
            continue
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if line and not line.startswith("#"):
                patterns.append(re.compile(line))
    return patterns


def run_git(repo_root: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo_root), *args],
        check=True,
        capture_output=True,
    )
    return proc.stdout.decode("utf-8", errors="replace")


def staged_diff(repo_root: Path) -> str:
    return run_git(repo_root, "diff", "--cached", "--unified=0", "--no-color", "--no-ext-diff", "--text")


def commit_diffs(repo_root: Path, commits: list[str]) -> str:
    chunks = [run_git(repo_root, "show", "--unified=0", "--no-color", "--no-ext-diff", "--format=medium", "--text", c) for c in commits]
    return "\n".join(chunks)


def read_content(path: str | None) -> str:
    if not path:
        return ""
    if path == "-":
        return sys.stdin.read()
    return Path(path).read_text(encoding="utf-8")


def allowed(path: str, line: str, allowlist: list[re.Pattern[str]]) -> bool:
    if INLINE_ALLOW_MARKER in line:
        return True
    candidate = f"{path}\t{line}"
    return any(p.search(candidate) for p in allowlist)


def parse_added_lines(diff_text: str) -> Iterable[tuple[str, int | None, str]]:
    current_path = "<unknown>"
    current_line_no: int | None = None
    hunk_re = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")
    path_re = re.compile(r"^\+\+\+ b/(.+)$")
    diff_path_re = re.compile(r"^diff --git a/(.+) b/(.+)$")

    for raw in diff_text.splitlines():
        m = path_re.match(raw)
        if m:
            current_path = m.group(1)
            continue
        m = diff_path_re.match(raw)
        if m:
            current_path = m.group(2)
            continue
        m = hunk_re.match(raw)
        if m:
            current_line_no = int(m.group(1))
            continue
        if raw.startswith(("+++", "@@")):
            continue
        if raw.startswith("+"):
            yield current_path, current_line_no, raw[1:]
            if current_line_no is not None:
                current_line_no += 1
            continue
        if raw.startswith(" ") and current_line_no is not None:
            current_line_no += 1


def parse_runtime_lines(path: str, content: str) -> Iterable[tuple[str, int | None, str]]:
    if path:
        yield path, None, path
    for line_no, line in enumerate(content.splitlines(), start=1):
        yield path or "<runtime>", line_no, line


def scan_lines(
    items: Iterable[tuple[str, int | None, str]],
    rules: list[Rule],
    allowlist: list[re.Pattern[str]],
) -> list[Finding]:
    findings: list[Finding] = []
    seen: set[tuple[str, str, int | None, str]] = set()
    for path, line_no, line in items:
        if not line.strip() or allowed(path, line, allowlist):
            continue
        for rule in rules:
            if not rule.pattern.search(line):
                continue
            key = (rule.rule_id, path, line_no, line)
            if key in seen:
                continue
            seen.add(key)
            findings.append(Finding(
                severity=rule.severity,
                rule_id=rule.rule_id,
                description=rule.description,
                path=path,
                line_no=line_no,
                excerpt=line.strip()[:200],
            ))
    return findings


def run_runtime_gitleaks(content: str, path: str) -> list[Finding]:
    if not content.strip() or shutil.which("gitleaks") is None:
        return []
    proc = subprocess.run(
        ["gitleaks", "stdin", "--no-banner", "--no-color", "--redact"],
        input=content, capture_output=True, text=True, check=False,
    )
    if proc.returncode == 0:
        return []
    return [Finding(
        severity="block",
        rule_id="gitleaks-secret",
        description="Secret-like credential detected by gitleaks",
        path=path or "<runtime>",
        line_no=None,
        excerpt="Content matched a high-confidence secret detector",
    )]


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


_ALLOWLIST_HINT = (
    "If a finding is intentional, add a narrow regex to .sensitive-scan-allowlist "
    "or ~/.config/git/hooks/sensitive-allowlist.txt after review."
)
_WARN_HINT = (
    "Allow intentional cases with a narrow regex in .sensitive-scan-allowlist "
    "or ~/.config/git/hooks/sensitive-allowlist.txt."
)


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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root")
    parser.add_argument("--mode", choices=("staged", "push", "runtime"), required=True)
    parser.add_argument("--path", default="")
    parser.add_argument("--tool-name", default="")
    parser.add_argument("--content-file")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("commits", nargs="*")
    return parser.parse_args()


def _require_repo_root(args: argparse.Namespace) -> Path:
    if not args.repo_root:
        raise SystemExit(f"--repo-root is required for {args.mode} mode")
    return Path(args.repo_root).resolve()


def main() -> int:
    args = parse_args()
    repo_root = Path(args.repo_root).resolve() if args.repo_root else None
    rules = load_rules(PATTERN_FILE)
    allowlist = load_allowlist(repo_root)

    if args.mode in ("staged", "push"):
        root = _require_repo_root(args)
        diff_text = staged_diff(root) if args.mode == "staged" else commit_diffs(root, args.commits)
        findings = scan_lines(parse_added_lines(diff_text), rules, allowlist)
    else:
        content = read_content(args.content_file)
        runtime_rules = [r for r in rules if r.runtime_block]
        findings = scan_lines(parse_runtime_lines(args.path, content), runtime_rules, allowlist)
        findings.extend(run_runtime_gitleaks(content, args.path))

    if args.json:
        emit_json(findings, args.mode)
    return print_findings(findings, args.mode)


if __name__ == "__main__":
    sys.exit(main())
