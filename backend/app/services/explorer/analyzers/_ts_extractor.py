"""TypeScript/TSX symbol extraction via regex."""

from __future__ import annotations

import re
from typing import cast

from ._helpers import content_hash, keywords
from .symbol_types import SymbolRecord

_TS_DECL_RE = re.compile(
    r"(?P<signature>"
    r"(?:export\s+)?interface\s+(?P<interface>[A-Z]\w*)"
    r"|(?:export\s+)?type\s+(?P<type>[A-Z]\w*)\s*="
    r"|(?:export\s+)?class\s+(?P<class>[A-Z]\w*)"
    r"|(?:export\s+)?function\s+(?P<function>[A-Z_a-z]\w*)\s*\("
    r"|(?:export\s+)?const\s+(?P<const>[A-Z_a-z]\w*)\s*=\s*(?:async\s*)?(?:<[^>]+>\s*)?(?:\([^)]*\)|[A-Z_a-z]\w*)\s*=>"
    r")",
    re.MULTILINE,
)


def extract_typescript_symbols(
    source: str, rel_path: str, language: str
) -> list[SymbolRecord]:
    """Return all TypeScript/TSX symbols found in *source*."""
    symbols: list[SymbolRecord] = []
    for match in _TS_DECL_RE.finditer(source):
        name, kind = _match_name_and_kind(match)
        if not name or not kind:
            continue
        symbols.append(_build_ts_symbol(source, match, name, kind, rel_path, language))
    return symbols


def _build_ts_symbol(
    source: str,
    match: re.Match[str],
    name: str,
    kind: str,
    rel_path: str,
    language: str,
) -> SymbolRecord:
    start = match.start("signature")
    end = _ts_symbol_end(source, match.end("signature"), kind)
    start_line = source.count("\n", 0, start) + 1
    end_line = source.count("\n", 0, end) + 1
    first_newline = source.find("\n", start, end)
    sig_end = first_newline if (first_newline != -1 and "\n" in source[start:end]) else end
    signature = source[start:sig_end].strip()
    segment = source[start:end]
    return cast(SymbolRecord, {
        "symbol_id": f"{rel_path}::{name}#{kind}",
        "qualified_name": name,
        "name": name,
        "kind": kind,
        "signature": signature,
        "language": language,
        "start_line": start_line,
        "end_line": end_line,
        "byte_offset": start,
        "byte_length": max(0, end - start),
        "content_hash": content_hash(segment),
        "summary": None,
        "keywords": keywords(name, signature, None),
        "decorators": [],
    })


def _match_name_and_kind(match: re.Match[str]) -> tuple[str | None, str | None]:
    if match.group("interface"):
        return match.group("interface"), "type"
    if match.group("type"):
        return match.group("type"), "type"
    if match.group("class"):
        return match.group("class"), "class"
    if match.group("function"):
        return match.group("function"), "function"
    if match.group("const"):
        return match.group("const"), "function"
    return None, None


def _ts_symbol_end(source: str, start: int, kind: str) -> int:
    brace_index = source.find("{", start)
    if kind in {"function", "class"} and brace_index != -1:
        end = _find_matching_brace(source, brace_index)
        if end is not None:
            return end + 1
    if kind == "type" and brace_index != -1:
        end = _find_matching_brace(source, brace_index)
        if end is not None:
            semi = source.find(";", end)
            return semi + 1 if semi != -1 else end + 1
    semi = source.find(";", start)
    newline = source.find("\n", start)
    candidates = [pos for pos in (semi, newline) if pos != -1]
    return min(candidates) + 1 if candidates else len(source)


def _find_matching_brace(source: str, open_index: int) -> int | None:
    depth = 0
    in_string: str | None = None
    escape = False
    for index in range(open_index, len(source)):
        char = source[index]
        if in_string:
            escape, in_string = _advance_string_state(char, escape, in_string)
            continue
        if char in {"'", '"', "`"}:
            in_string = char
        elif char == "{":
            depth += 1
        elif char == "}" and depth > 1:
            depth -= 1
        elif char == "}":
            return index
    return None


def _advance_string_state(
    char: str, escape: bool, in_string: str
) -> tuple[bool, str | None]:
    if escape:
        return False, in_string
    if char == "\\":
        return True, in_string
    if char == in_string:
        return False, None
    return False, in_string
