"""AST analyzer for extracting Python code metrics.

Parses Python source files to extract function and class metadata
for code quality analysis.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import TypedDict

from ....logging_config import get_logger

logger = get_logger(__name__)

_FuncNode = ast.FunctionDef | ast.AsyncFunctionDef
_NESTING_TYPES = (ast.If, ast.For, ast.While, ast.With, ast.Try, ast.Match, ast.AsyncFor, ast.AsyncWith)


class FunctionEntry(TypedDict):
    """Metadata for a function or method."""

    name: str
    lines: int
    start_line: int
    params: list[str]
    has_docstring: bool


class ClassEntry(TypedDict):
    """Metadata for a class."""

    name: str
    methods: list[str]
    lines: int
    start_line: int
    has_docstring: bool


class ParseResult(TypedDict):
    """Result of parsing a Python file."""

    functions: list[FunctionEntry]
    classes: list[ClassEntry]
    max_nesting: int


def _count_lines(node: ast.AST) -> int:
    """Count lines spanned by an AST node."""
    end = getattr(node, "end_lineno", None)
    start = getattr(node, "lineno", None)
    return int(end - start + 1) if end is not None and start is not None else 0


def _has_docstring(node: _FuncNode | ast.ClassDef) -> bool:
    """Check if a function or class has a docstring."""
    first = node.body[0] if node.body else None
    return (
        isinstance(first, ast.Expr)
        and isinstance(first.value, ast.Constant)
        and isinstance(first.value.value, str)
    )


def _get_param_names(node: _FuncNode) -> list[str]:
    """Extract parameter names from a function definition."""
    args = node.args
    params = [a.arg for a in args.posonlyargs + args.args + args.kwonlyargs]
    if args.vararg:
        params.append(f"*{args.vararg.arg}")
    if args.kwarg:
        params.append(f"**{args.kwarg.arg}")
    return params


def _max_nesting(tree: ast.AST, depth: int = 0) -> int:
    """Recursively compute maximum nesting depth."""
    if isinstance(tree, _NESTING_TYPES):
        depth += 1
    return max(
        (_max_nesting(child, depth) for child in ast.iter_child_nodes(tree)),
        default=depth,
    )


def _make_function_entry(node: _FuncNode) -> FunctionEntry:
    """Build a FunctionEntry from a function AST node."""
    return FunctionEntry(
        name=node.name,
        lines=_count_lines(node),
        start_line=node.lineno,
        params=_get_param_names(node),
        has_docstring=_has_docstring(node),
    )


def _make_class_entry(node: ast.ClassDef) -> ClassEntry:
    """Build a ClassEntry from a class AST node."""
    methods = [item.name for item in node.body if isinstance(item, _FuncNode)]
    return ClassEntry(
        name=node.name,
        methods=methods,
        lines=_count_lines(node),
        start_line=node.lineno,
        has_docstring=_has_docstring(node),
    )


def parse_python_file(file_path: str | Path) -> ParseResult:
    """Parse a Python file and extract function/class metrics.

    Args:
        file_path: Path to Python source file

    Returns:
        ParseResult with functions, classes, and max_nesting

    Raises:
        FileNotFoundError: If file doesn't exist
        SyntaxError: If file has invalid Python syntax
    """
    path = Path(file_path)
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))

    functions: list[FunctionEntry] = []
    classes: list[ClassEntry] = []

    for node in tree.body:
        if isinstance(node, _FuncNode):
            functions.append(_make_function_entry(node))
        elif isinstance(node, ast.ClassDef):
            classes.append(_make_class_entry(node))

    return ParseResult(
        functions=functions,
        classes=classes,
        max_nesting=_max_nesting(tree),
    )
