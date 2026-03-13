"""Symbol extraction for explorer precision retrieval."""

from __future__ import annotations

import ast
import hashlib
import re
from pathlib import Path
from typing import TypedDict, cast

_FuncNode = ast.FunctionDef | ast.AsyncFunctionDef
_CONSTANT_NAME_RE = re.compile(r"^_?[A-Z][A-Z0-9_]+$")
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
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9]+")


class SymbolRecord(TypedDict):
    """Stored symbol metadata."""

    symbol_id: str
    qualified_name: str
    name: str
    kind: str
    signature: str
    language: str
    start_line: int
    end_line: int
    byte_offset: int
    byte_length: int
    content_hash: str
    summary: str | None
    keywords: list[str]
    decorators: list[str]


def extract_symbols(file_path: Path, rel_path: str) -> list[SymbolRecord]:
    """Extract supported-language symbols for a file."""
    ext = file_path.suffix.lower()
    if ext not in {".py", ".ts", ".tsx"}:
        return []

    try:
        source = file_path.read_text(encoding="utf-8")
        if ext == ".py":
            return _dedupe_symbol_ids(_extract_python_symbols(source, rel_path))
        return _dedupe_symbol_ids(
            _extract_typescript_symbols(source, rel_path, "tsx" if ext == ".tsx" else "typescript")
        )
    except (OSError, UnicodeDecodeError, SyntaxError):
        return []


def _extract_python_symbols(source: str, rel_path: str) -> list[SymbolRecord]:
    tree = ast.parse(source, filename=rel_path)
    lines = source.splitlines(keepends=True)
    offsets = _line_offsets(lines)
    symbols: list[SymbolRecord] = []

    def visit(node: ast.AST, parents: list[str]) -> None:
        for child in getattr(node, "body", []):
            if isinstance(child, ast.ClassDef):
                symbols.append(_python_symbol(child, source, rel_path, offsets, parents, "class"))
                visit(child, [*parents, child.name])
            elif isinstance(child, _FuncNode):
                kind = "method" if parents else "function"
                symbols.append(_python_symbol(child, source, rel_path, offsets, parents, kind))
            elif isinstance(child, (ast.If, ast.With, ast.For, ast.AsyncFor, ast.While, ast.Try, ast.Match)):
                visit(child, parents)
            # Module-level constants (UPPER_CASE or _UPPER_CASE assignments)
            elif not parents and isinstance(child, ast.Assign):
                for target in child.targets:
                    if isinstance(target, ast.Name) and _CONSTANT_NAME_RE.match(target.id):
                        symbols.append(_python_constant(child, target.id, source, rel_path, offsets))

    visit(tree, [])
    return symbols


def _python_symbol(
    node: ast.ClassDef | _FuncNode,
    source: str,
    rel_path: str,
    offsets: list[int],
    parents: list[str],
    kind: str,
) -> SymbolRecord:
    name = node.name
    qualified_name = ".".join([*parents, name]) if parents else name
    start = _byte_index(offsets, node.lineno, node.col_offset)
    end = _byte_index(offsets, node.end_lineno, node.end_col_offset)
    signature = _python_signature(node)
    doc = ast.get_docstring(node)
    segment = source[start:end]
    decorators = _extract_decorators(node)
    return cast(SymbolRecord, {
        "symbol_id": f"{rel_path}::{qualified_name}#{kind}",
        "qualified_name": qualified_name,
        "name": name,
        "kind": kind,
        "signature": signature,
        "language": "python",
        "start_line": node.lineno,
        "end_line": node.end_lineno or node.lineno,
        "byte_offset": start,
        "byte_length": max(0, end - start),
        "content_hash": _content_hash(segment),
        "summary": doc.splitlines()[0].strip() if doc else None,
        "keywords": _keywords(qualified_name, signature, doc, *decorators),
        "decorators": decorators,
    })


def _python_constant(
    node: ast.Assign,
    name: str,
    source: str,
    rel_path: str,
    offsets: list[int],
) -> SymbolRecord:
    start = _byte_index(offsets, node.lineno, node.col_offset)
    end = _byte_index(offsets, node.end_lineno, node.end_col_offset)
    segment = source[start:end]
    # Use the first line as signature
    first_line = segment.split("\n", 1)[0].strip()
    return cast(SymbolRecord, {
        "symbol_id": f"{rel_path}::{name}#constant",
        "qualified_name": name,
        "name": name,
        "kind": "constant",
        "signature": first_line,
        "language": "python",
        "start_line": node.lineno,
        "end_line": node.end_lineno or node.lineno,
        "byte_offset": start,
        "byte_length": max(0, end - start),
        "content_hash": _content_hash(segment),
        "summary": None,
        "keywords": _keywords(name, first_line, None),
        "decorators": [],
    })


def _extract_decorators(node: ast.ClassDef | _FuncNode) -> list[str]:
    """Extract decorator names from a class or function node."""
    decorators: list[str] = []
    for decorator in node.decorator_list:
        try:
            # Handle @name, @module.name, @module.name(args)
            if isinstance(decorator, ast.Call):
                decorators.append(ast.unparse(decorator.func))
            else:
                decorators.append(ast.unparse(decorator))
        except Exception:
            continue
    return decorators


def _python_signature(node: ast.ClassDef | _FuncNode) -> str:
    if isinstance(node, ast.ClassDef):
        if node.bases:
            bases = ", ".join(ast.unparse(base) for base in node.bases)
            return f"class {node.name}({bases})"
        return f"class {node.name}"
    prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
    args = ast.unparse(node.args)
    returns = f" -> {ast.unparse(node.returns)}" if node.returns else ""
    return f"{prefix} {node.name}({args}){returns}"


def _extract_typescript_symbols(source: str, rel_path: str, language: str) -> list[SymbolRecord]:
    symbols: list[SymbolRecord] = []
    for match in _TS_DECL_RE.finditer(source):
        name, kind = _match_name_and_kind(match)
        if not name or not kind:
            continue
        start = match.start("signature")
        end = _ts_symbol_end(source, match.end("signature"), kind)
        start_line = source.count("\n", 0, start) + 1
        end_line = source.count("\n", 0, end) + 1
        signature = source[start:source.find("\n", start, end) if "\n" in source[start:end] else end].strip()
        segment = source[start:end]
        symbols.append(
            cast(SymbolRecord, {
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
                "content_hash": _content_hash(segment),
                "summary": None,
                "keywords": _keywords(name, signature, None),
                "decorators": [],
            })
        )
    return symbols


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
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == in_string:
                in_string = None
            continue
        if char in {"'", '"', "`"}:
            in_string = char
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index
    return None


def _line_offsets(lines: list[str]) -> list[int]:
    offsets = [0]
    total = 0
    for line in lines:
        total += len(line)
        offsets.append(total)
    return offsets


def _byte_index(offsets: list[int], lineno: int | None, col_offset: int | None) -> int:
    if lineno is None or col_offset is None:
        return 0
    return offsets[max(0, lineno - 1)] + col_offset


def _content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _dedupe_symbol_ids(symbols: list[SymbolRecord]) -> list[SymbolRecord]:
    seen: set[str] = set()
    for symbol in symbols:
        symbol_id = symbol["symbol_id"]
        if symbol_id in seen:
            symbol["symbol_id"] = f"{symbol_id}@{symbol['start_line']}"
        seen.add(symbol["symbol_id"])
    return symbols


def _keywords(*parts: str | None) -> list[str]:
    values: set[str] = set()
    for part in parts:
        if not part:
            continue
        for word in _WORD_RE.findall(part):
            values.add(word.lower())
    return sorted(values)
