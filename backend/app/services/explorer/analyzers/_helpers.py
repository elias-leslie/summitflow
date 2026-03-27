"""Shared low-level helpers for symbol extraction."""

from __future__ import annotations

import hashlib
import re

_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9]+")


def line_offsets(lines: list[str]) -> list[int]:
    """Build cumulative byte offsets for each line."""
    offsets = [0]
    total = 0
    for line in lines:
        total += len(line)
        offsets.append(total)
    return offsets


def byte_index(offsets: list[int], lineno: int | None, col_offset: int | None) -> int:
    """Convert (line, col) to an absolute byte index using precomputed offsets."""
    if lineno is None or col_offset is None:
        return 0
    return offsets[max(0, lineno - 1)] + col_offset


def content_hash(content: str) -> str:
    """Return a SHA-256 hex digest of *content*."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def keywords(*parts: str | None) -> list[str]:
    """Extract and de-duplicate lower-cased word tokens from *parts*."""
    values: set[str] = set()
    for part in parts:
        if not part:
            continue
        for word in _WORD_RE.findall(part):
            values.add(word.lower())
    return sorted(values)
