#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Iterable

from _scan_models import (
    GLOBAL_ALLOWLIST,
    INLINE_ALLOW_MARKER,
    PATTERN_FILE,
    REPO_ALLOWLIST,
    Finding,
    Rule,
)
from _scan_parser import parse_added_lines, parse_runtime_lines
from _scan_reporter import emit_json, print_findings, summarize


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


def main() -> int:
    args = parse_args()
    repo_root = Path(args.repo_root).resolve() if args.repo_root else None
    rules = load_rules(PATTERN_FILE)
    allowlist = load_allowlist(repo_root)

    if args.mode in ("staged", "push"):
        if not args.repo_root:
            raise SystemExit(f"--repo-root is required for {args.mode} mode")
        root = Path(args.repo_root).resolve()
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
