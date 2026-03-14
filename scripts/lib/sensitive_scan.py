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
            rules.append(
                Rule(
                    rule_id=item["id"],
                    description=item["description"],
                    pattern=re.compile(item["pattern"]),
                    severity=severity,
                    runtime_block=bool(item.get("runtime_block", False)),
                )
            )
    return rules


def load_allowlist(repo_root: Path | None) -> list[re.Pattern[str]]:
    patterns: list[re.Pattern[str]] = []
    candidate_paths = [GLOBAL_ALLOWLIST]
    if repo_root is not None:
        candidate_paths.append(repo_root / REPO_ALLOWLIST)

    for path in candidate_paths:
        if not path.exists():
            continue
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            patterns.append(re.compile(line))
    return patterns


def run_git(repo_root: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo_root), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return proc.stdout


def staged_diff(repo_root: Path) -> str:
    return run_git(
        repo_root,
        "diff",
        "--cached",
        "--unified=0",
        "--no-color",
        "--no-ext-diff",
        "--text",
    )


def commit_diffs(repo_root: Path, commits: list[str]) -> str:
    chunks: list[str] = []
    for commit in commits:
        chunks.append(
            run_git(
                repo_root,
                "show",
                "--unified=0",
                "--no-color",
                "--no-ext-diff",
                "--format=medium",
                "--text",
                commit,
            )
        )
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
    return any(pattern.search(candidate) for pattern in allowlist)


def parse_added_lines(diff_text: str) -> Iterable[tuple[str, int | None, str]]:
    current_path = "<unknown>"
    current_line_no: int | None = None

    hunk_re = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")
    path_re = re.compile(r"^\+\+\+ b/(.+)$")
    diff_path_re = re.compile(r"^diff --git a/(.+) b/(.+)$")

    for raw_line in diff_text.splitlines():
        path_match = path_re.match(raw_line)
        if path_match:
            current_path = path_match.group(1)
            continue

        diff_path_match = diff_path_re.match(raw_line)
        if diff_path_match:
            current_path = diff_path_match.group(2)
            continue

        hunk_match = hunk_re.match(raw_line)
        if hunk_match:
            current_line_no = int(hunk_match.group(1))
            continue

        if raw_line.startswith("+++"):
            continue
        if raw_line.startswith("@@"):
            continue
        if raw_line.startswith("+"):
            yield current_path, current_line_no, raw_line[1:]
            if current_line_no is not None:
                current_line_no += 1
            continue
        if raw_line.startswith(" "):
            if current_line_no is not None:
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
        if not line.strip():
            continue
        if allowed(path, line, allowlist):
            continue
        for rule in rules:
            if rule.pattern.search(line):
                key = (rule.rule_id, path, line_no, line)
                if key in seen:
                    continue
                seen.add(key)
                findings.append(
                    Finding(
                        severity=rule.severity,
                        rule_id=rule.rule_id,
                        description=rule.description,
                        path=path,
                        line_no=line_no,
                        excerpt=line.strip()[:200],
                    )
                )
    return findings


def run_runtime_gitleaks(content: str, path: str) -> list[Finding]:
    if not content.strip():
        return []
    if shutil.which("gitleaks") is None:
        return []

    proc = subprocess.run(
        ["gitleaks", "stdin", "--no-banner", "--no-color", "--redact"],
        input=content,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode == 0:
        return []
    return [
        Finding(
            severity="block",
            rule_id="gitleaks-secret",
            description="Secret-like credential detected by gitleaks",
            path=path or "<runtime>",
            line_no=None,
            excerpt="Content matched a high-confidence secret detector",
        )
    ]


def summarize(findings: list[Finding], mode: str) -> str:
    blocked = [finding for finding in findings if finding.severity == "block"]
    warned = [finding for finding in findings if finding.severity == "warn"]
    label = "write" if mode == "runtime" else ("commit" if mode == "staged" else "push")
    if blocked:
        return f"{label.capitalize()} blocked: {blocked[0].description}"
    if warned:
        return f"{label.capitalize()} warning: {warned[0].description}"
    return f"{label.capitalize()} clean"


def emit_json(findings: list[Finding], mode: str) -> None:
    status = "block" if any(f.severity == "block" for f in findings) else ("warn" if findings else "ok")
    payload = {
        "mode": mode,
        "status": status,
        "summary": summarize(findings, mode),
        "findings": [asdict(finding) for finding in findings],
    }
    print(json.dumps(payload))


def print_findings(findings: list[Finding], mode: str) -> int:
    blocked = [finding for finding in findings if finding.severity == "block"]
    warned = [finding for finding in findings if finding.severity == "warn"]
    label = "Write" if mode == "runtime" else ("Commit" if mode == "staged" else "Push")

    if blocked:
        print("", file=sys.stderr)
        print(f"{label} blocked: sensitive content requires review.", file=sys.stderr)
        for finding in blocked:
            location = f"{finding.path}:{finding.line_no}" if finding.line_no else finding.path
            print(
                f"  BLOCK {finding.rule_id} {location}: {finding.description}",
                file=sys.stderr,
            )
            print(f"    {finding.excerpt}", file=sys.stderr)
        if warned:
            print("", file=sys.stderr)
            print("Additional review-only findings:", file=sys.stderr)
            for finding in warned:
                location = f"{finding.path}:{finding.line_no}" if finding.line_no else finding.path
                print(
                    f"  WARN  {finding.rule_id} {location}: {finding.description}",
                    file=sys.stderr,
                )
        if mode != "runtime":
            print("", file=sys.stderr)
            print(
                "If a finding is intentional, add a narrow regex to .sensitive-scan-allowlist "
                "or ~/.config/git/hooks/sensitive-allowlist.txt after review.",
                file=sys.stderr,
            )
        return 1

    if warned:
        print("", file=sys.stderr)
        print(f"{label} warning: review sensitive content before continuing.", file=sys.stderr)
        for finding in warned:
            location = f"{finding.path}:{finding.line_no}" if finding.line_no else finding.path
            print(
                f"  WARN  {finding.rule_id} {location}: {finding.description}",
                file=sys.stderr,
            )
            print(f"    {finding.excerpt}", file=sys.stderr)
        print(
            "Allow intentional cases with a narrow regex in .sensitive-scan-allowlist "
            "or ~/.config/git/hooks/sensitive-allowlist.txt.",
            file=sys.stderr,
        )
    return 0


def resolve_repo_root(value: str | None) -> Path | None:
    if not value:
        return None
    return Path(value).resolve()


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
    repo_root = resolve_repo_root(args.repo_root)
    rules = load_rules(PATTERN_FILE)
    allowlist = load_allowlist(repo_root)

    if args.mode == "staged":
        if repo_root is None:
            raise SystemExit("--repo-root is required for staged mode")
        diff_text = staged_diff(repo_root)
        findings = scan_lines(parse_added_lines(diff_text), rules, allowlist)
    elif args.mode == "push":
        if repo_root is None:
            raise SystemExit("--repo-root is required for push mode")
        diff_text = commit_diffs(repo_root, args.commits)
        findings = scan_lines(parse_added_lines(diff_text), rules, allowlist)
    else:
        content = read_content(args.content_file)
        runtime_rules = [rule for rule in rules if rule.runtime_block]
        findings = scan_lines(parse_runtime_lines(args.path, content), runtime_rules, allowlist)
        findings.extend(run_runtime_gitleaks(content, args.path))

    if args.json:
        emit_json(findings, args.mode)
    return print_findings(findings, args.mode)


if __name__ == "__main__":
    sys.exit(main())
