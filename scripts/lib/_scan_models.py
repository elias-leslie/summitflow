from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


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
