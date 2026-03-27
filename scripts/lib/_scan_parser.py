from __future__ import annotations

import re
import sys
from typing import Iterable


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
