"""Python AST-based symbol extraction."""

from __future__ import annotations

import ast
import re
from typing import cast

from ._helpers import byte_index, content_hash, keywords, line_offsets
from .symbol_types import SymbolRecord

_FuncNode = ast.FunctionDef | ast.AsyncFunctionDef
_CONSTANT_NAME_RE = re.compile(r"^_?[A-Z][A-Z0-9_]+$")
_CONTROL_FLOW = (
    ast.If, ast.With, ast.For, ast.AsyncFor, ast.While, ast.Try, ast.Match
)


def extract_python_symbols(source: str, rel_path: str) -> list[SymbolRecord]:
    """Parse *source* and return all Python symbols."""
    tree = ast.parse(source, filename=rel_path)
    lines = source.splitlines(keepends=True)
    offsets = line_offsets(lines)
    symbols: list[SymbolRecord] = []
    _visit(tree, [], source, rel_path, offsets, symbols)
    return symbols


def _visit(
    node: ast.AST,
    parents: list[str],
    source: str,
    rel_path: str,
    offsets: list[int],
    symbols: list[SymbolRecord],
) -> None:
    for child in getattr(node, "body", []):
        if isinstance(child, ast.ClassDef):
            symbols.append(_class_symbol(child, source, rel_path, offsets, parents))
            _visit(child, [*parents, child.name], source, rel_path, offsets, symbols)
        elif isinstance(child, _FuncNode):
            kind = "method" if parents else "function"
            symbols.append(_func_symbol(child, source, rel_path, offsets, parents, kind))
        elif isinstance(child, _CONTROL_FLOW):
            _visit(child, parents, source, rel_path, offsets, symbols)
        elif not parents and isinstance(child, ast.Assign):
            _collect_constants(child, source, rel_path, offsets, symbols)


def _class_symbol(
    node: ast.ClassDef,
    source: str,
    rel_path: str,
    offsets: list[int],
    parents: list[str],
) -> SymbolRecord:
    return _build_symbol(node, source, rel_path, offsets, parents, "class")


def _func_symbol(
    node: _FuncNode,
    source: str,
    rel_path: str,
    offsets: list[int],
    parents: list[str],
    kind: str,
) -> SymbolRecord:
    return _build_symbol(node, source, rel_path, offsets, parents, kind)


def _build_symbol(
    node: ast.ClassDef | _FuncNode,
    source: str,
    rel_path: str,
    offsets: list[int],
    parents: list[str],
    kind: str,
) -> SymbolRecord:
    name = node.name
    qualified_name = ".".join([*parents, name]) if parents else name
    start = byte_index(offsets, node.lineno, node.col_offset)
    end = byte_index(offsets, node.end_lineno, node.end_col_offset)
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
        "content_hash": content_hash(segment),
        "summary": doc.splitlines()[0].strip() if doc else None,
        "keywords": keywords(qualified_name, signature, doc, *decorators),
        "decorators": decorators,
    })


def _collect_constants(
    node: ast.Assign,
    source: str,
    rel_path: str,
    offsets: list[int],
    symbols: list[SymbolRecord],
) -> None:
    for target in node.targets:
        if isinstance(target, ast.Name) and _CONSTANT_NAME_RE.match(target.id):
            symbols.append(_constant_symbol(node, target.id, source, rel_path, offsets))


def _constant_symbol(
    node: ast.Assign,
    name: str,
    source: str,
    rel_path: str,
    offsets: list[int],
) -> SymbolRecord:
    start = byte_index(offsets, node.lineno, node.col_offset)
    end = byte_index(offsets, node.end_lineno, node.end_col_offset)
    segment = source[start:end]
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
        "content_hash": content_hash(segment),
        "summary": None,
        "keywords": keywords(name, first_line, None),
        "decorators": [],
    })


def _extract_decorators(node: ast.ClassDef | _FuncNode) -> list[str]:
    decorators: list[str] = []
    for decorator in node.decorator_list:
        try:
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
