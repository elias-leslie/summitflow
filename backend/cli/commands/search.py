"""Precision Code Search CLI command."""

from __future__ import annotations

import shutil
import subprocess
import threading
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import urlencode

import typer

from app.services.context_gatherer.token_utils import estimate_tokens, truncate_to_tokens
from app.services.explorer.analyzers import extract_symbols
from app.services.explorer.analyzers.symbol_types import SymbolRecord

from .._output_state import is_compact
from ..client import APIError, STClient
from ..config import get_config_optional
from ..lib.execution_context import (
    canonical_repo_root,
    resolve_checkout_project_id,
    resolve_checkout_root,
)
from ..output import handle_api_error, output_json

app = typer.Typer(help="Precision Code Search")


# ---------------------------------------------------------------------------
# Hint generation
# ---------------------------------------------------------------------------

_HINT_PREFIX = "hint: "
_SEARCH_PROGRESS_DELAY_SECONDS = 1.5
_SEARCH_PROGRESS_MESSAGE = (
    "st search: still working; first precision search may refresh stale Explorer indexes before returning results."
)
_SUPPORTED_SYMBOL_EXTENSIONS = {".py", ".ts", ".tsx"}
_CHECKOUT_EXCLUDE_GLOBS = (
    "!**/.git/**",
    "!**/node_modules/**",
    "!**/.venv/**",
    "!**/.next/**",
    "!**/dist/**",
    "!**/build/**",
    "!**/coverage/**",
)
_CHECKOUT_EXCLUDE_DIRS = {".git", "node_modules", ".venv", ".next", "dist", "build", "coverage", "__pycache__"}
_CHECKOUT_RIPGREP_TIMEOUT_SECONDS = 15
_CHECKOUT_CANDIDATE_LIMIT = 60
_LINE_PREVIEW_LIMIT = 240


class SearchScope(StrEnum):
    """Search scope for st search."""

    AUTO = "auto"
    PROJECT = "project"
    CHECKOUT = "checkout"


@dataclass(frozen=True)
class SearchRoots:
    """Resolved search roots for the current CLI invocation."""

    scope: SearchScope
    effective_scope: str
    project_root: Path | None
    checkout_root: Path | None


def _generate_hint(query: str, mode: str, metadata: dict) -> str | None:
    """Return an actionable refinement hint based on result quality, or None."""
    from app.services.context_gatherer._precision_query import (
        has_path_segments,
        is_short_or_generic,
    )

    queries = [query]

    if mode == "empty":
        used_fallback = metadata.get("used_fallback", False)
        files_searched = metadata.get("text_files_searched", 0)
        if has_path_segments(queries):
            return "path terms reduce symbol precision. Try just the symbol name, or `st search --file <path>` to list symbols in a file."
        if is_short_or_generic(queries):
            return "query is too short/generic for symbol matching. Try a specific function, class, or variable name."
        # Text fallback already ran and found nothing — don't suggest --text again
        if used_fallback or files_searched > 0:
            return f"searched {files_searched} files — no symbol or text matches. Try a shorter/different identifier, or `st search --file <path>` to browse symbols in a known file."
        return "no symbol matches. Try `st search --text <query>` for content search, or refine to a specific identifier."

    if mode == "text-fallback":
        if has_path_segments(queries):
            return "fell back to text search (no symbol match). Path-qualified terms are noisy — try just the symbol name."
        return "fell back to text search (no symbol match). Try a specific identifier like `FunctionName` or `function_name`."

    # Symbol-first with low match quality — check if results look incidental
    symbol_count = metadata.get("symbol_count", 0)
    if mode == "symbol-first" and symbol_count > 0:
        if has_path_segments(queries):
            return "path terms in symbol search may favor incidental mentions. Try `st search --text <query>` for file-content matches."
        if is_short_or_generic(queries):
            return "short/generic query may produce incidental symbol matches. Verify relevance or try a more specific identifier."

    return None


def _emit_status(message: str) -> None:
    """Write a human-oriented status line to stderr without polluting stdout payloads."""
    typer.echo(message, err=True)


def _start_delayed_status_timer(message: str) -> threading.Timer:
    """Start a delayed stderr status note for slow precision searches."""
    timer = threading.Timer(_SEARCH_PROGRESS_DELAY_SECONDS, _emit_status, args=(message,))
    timer.daemon = True
    timer.start()
    return timer


def _run_precision_search(client: STClient, query: str, budget: int, limit: int) -> dict:
    """Run precision search with a delayed status line so stale refreshes don't look hung."""
    params = urlencode({"q": query, "budget": budget, "limit": limit})
    timer = _start_delayed_status_timer(_SEARCH_PROGRESS_MESSAGE)
    try:
        return client.get(client._url(f"/explorer/precision-search?{params}"))
    finally:
        timer.cancel()


def _emit_precision_search_metadata_note(metadata: dict) -> None:
    """Explain stale-index behavior after the search completes when relevant."""
    if metadata.get("refreshed_index"):
        _emit_status("st search: refreshed stale Explorer indexes before returning results.")
        return
    if metadata.get("stale_hit"):
        _emit_status(
            "st search: Explorer indexes are stale and refresh did not complete; verify results carefully or rerun after scan."
        )
    if metadata.get("checkout_overlay_applied"):
        _emit_status("st search: prepended current checkout results ahead of indexed project context.")


def _resolve_search_roots(project_override: str | None, scope: SearchScope) -> SearchRoots:
    """Resolve canonical project and current-checkout roots for this search."""
    checkout_root = resolve_checkout_root()
    canonical_root = canonical_repo_root()
    if scope == SearchScope.CHECKOUT:
        return SearchRoots(
            scope=scope,
            effective_scope="checkout" if checkout_root else "project",
            project_root=None,
            checkout_root=checkout_root,
        )

    config = get_config_optional()
    selected_project_id = project_override or config.project_id or None
    checkout_project_id = resolve_checkout_project_id()

    project_root = Path(config.project_root).resolve() if config.project_root else None
    if project_root is None and selected_project_id and checkout_project_id and selected_project_id == checkout_project_id:
        project_root = canonical_root

    if scope == SearchScope.PROJECT or (selected_project_id and checkout_project_id and selected_project_id != checkout_project_id):
        effective_scope = "project"
    elif checkout_root is not None and project_root is not None and checkout_root != project_root:
        effective_scope = "combined"
    elif checkout_root is not None and project_root is None and selected_project_id is None:
        effective_scope = "checkout"
    else:
        effective_scope = "project"

    return SearchRoots(
        scope=scope,
        effective_scope=effective_scope,
        project_root=project_root,
        checkout_root=checkout_root,
    )


def _normalize_rel_path(root: Path, path: Path) -> str | None:
    """Return a posix path relative to root, or None if path escapes root."""
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return None


def _iter_checkout_files(root: Path, *, allowed_suffixes: set[str] | None = None) -> list[Path]:
    """Return candidate files under a checkout root with common junk directories excluded."""
    results: list[Path] = []
    for dirpath, dirnames, filenames in root.walk(top_down=True):
        dirnames[:] = [name for name in dirnames if name not in _CHECKOUT_EXCLUDE_DIRS]
        for filename in filenames:
            path = dirpath / filename
            if allowed_suffixes is not None and path.suffix.lower() not in allowed_suffixes:
                continue
            results.append(path)
    return results


def _ripgrep_candidate_paths(
    root: Path,
    query: str,
    *,
    limit: int,
    suffixes: set[str] | None = None,
) -> list[Path]:
    """Return file candidates containing the query under the current checkout."""
    rg_path = shutil.which("rg")
    if not rg_path:
        return []

    args = [
        rg_path,
        "-l",
        "--ignore-case",
        "--fixed-strings",
        "--hidden",
    ]
    if suffixes:
        for suffix in sorted(suffixes):
            args.extend(["--glob", f"*{suffix}"])
    for glob in _CHECKOUT_EXCLUDE_GLOBS:
        args.extend(["--glob", glob])
    args.extend([query, "."])

    try:
        proc = subprocess.run(
            args,
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_CHECKOUT_RIPGREP_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []

    if proc.returncode not in (0, 1):
        return []

    results: list[Path] = []
    for raw_line in proc.stdout.splitlines():
        rel_path = raw_line.strip()
        if not rel_path:
            continue
        candidate = (root / rel_path).resolve()
        if candidate.is_file():
            results.append(candidate)
        if len(results) >= limit:
            break
    return results


def _search_checkout_text(root: Path, query: str, *, limit: int) -> dict[str, Any]:
    """Search the current checkout directly from the filesystem."""
    query_value = query.strip()
    if not query_value:
        return {"query": query, "count": 0, "files_searched": 0, "items": [], "truncated": False, "scope": "checkout"}

    all_checkout_files = _iter_checkout_files(root)
    rg_path = shutil.which("rg")
    if rg_path:
        args = [
            rg_path,
            "--line-number",
            "--ignore-case",
            "--fixed-strings",
            "--hidden",
        ]
        for glob in _CHECKOUT_EXCLUDE_GLOBS:
            args.extend(["--glob", glob])
        args.extend([query_value, "."])
        try:
            proc = subprocess.run(
                args,
                cwd=root,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=_CHECKOUT_RIPGREP_TIMEOUT_SECONDS,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            proc = None
        else:
            if proc.returncode in (0, 1):
                items: list[dict[str, Any]] = []
                matched_files: set[str] = set()
                for raw_line in proc.stdout.splitlines():
                    path_part, sep, remainder = raw_line.partition(":")
                    if not sep:
                        continue
                    line_part, sep, content = remainder.partition(":")
                    if not sep:
                        continue
                    rel_path = path_part[2:] if path_part.startswith("./") else path_part
                    try:
                        line_number = int(line_part)
                    except ValueError:
                        continue
                    matched_files.add(rel_path)
                    if len(items) < limit:
                        items.append(
                            {
                                "path": rel_path,
                                "line": line_number,
                                "content": content[:_LINE_PREVIEW_LIMIT],
                                "language": None,
                                "truncated_file": False,
                            }
                        )
                return {
                    "query": query,
                    "count": len(items),
                    "files_searched": len(matched_files) or len(all_checkout_files),
                    "items": items,
                    "truncated": proc.returncode == 0 and len(items) >= limit,
                    "strategy": "checkout_ripgrep",
                    "scope": "checkout",
                    "root_path": str(root),
                }

    query_lower = query_value.lower()
    items: list[dict[str, Any]] = []
    files_searched = 0
    truncated = False
    for path in all_checkout_files:
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        files_searched += 1
        rel_path = _normalize_rel_path(root, path)
        if rel_path is None:
            continue
        for line_number, line in enumerate(content.splitlines(), start=1):
            if query_lower not in line.lower():
                continue
            if len(items) >= limit:
                truncated = True
                break
            items.append(
                {
                    "path": rel_path,
                    "line": line_number,
                    "content": line[:_LINE_PREVIEW_LIMIT],
                    "language": path.suffix.lower().lstrip("."),
                    "truncated_file": False,
                }
            )
        if truncated:
            break

    return {
        "query": query,
        "count": len(items),
        "files_searched": files_searched,
        "items": items,
        "truncated": truncated,
        "strategy": "checkout_fallback",
        "scope": "checkout",
        "root_path": str(root),
    }


def _expand_symbol_queries(query: str) -> list[str]:
    """Expand natural-language symbol queries the same way indexed precision search does."""
    from app.services.context_gatherer._precision_query import (
        is_natural_language_query,
        nl_to_symbol_terms,
        normalize_queries,
        split_path_and_symbol_terms,
    )

    normalized_queries = normalize_queries([query])
    if not normalized_queries:
        return []
    if is_natural_language_query(normalized_queries):
        expanded = nl_to_symbol_terms(normalized_queries)
        queries = expanded or normalized_queries
    else:
        _path_terms, symbol_terms = split_path_and_symbol_terms(normalized_queries)
        queries = symbol_terms or normalized_queries
    raw_query = query.strip()
    if raw_query and raw_query not in queries:
        queries.append(raw_query)
    return queries


def _symbol_score(symbol: SymbolRecord, rel_path: str, queries: list[str]) -> int:
    """Score a local symbol match using the same rough ordering as indexed search."""
    best_score = 0
    for query in queries:
        exact = query.strip().lower()
        if not exact:
            continue
        name = symbol["name"].lower()
        qualified_name = symbol["qualified_name"].lower()
        signature = (symbol.get("signature") or "").lower()
        summary = (symbol.get("summary") or "").lower()
        keywords = " ".join(symbol.get("keywords", [])).lower()
        rel_path_lower = rel_path.lower()

        if name == exact:
            best_score = max(best_score, 100)
        elif qualified_name == exact:
            best_score = max(best_score, 95)
        elif exact in name:
            best_score = max(best_score, 80)
        elif exact in qualified_name:
            best_score = max(best_score, 70)
        elif exact in rel_path_lower:
            best_score = max(best_score, 60)
        elif exact in summary:
            best_score = max(best_score, 50)
        elif exact in signature:
            best_score = max(best_score, 40)
        elif exact in keywords:
            best_score = max(best_score, 30)
    return best_score


def _symbol_record_to_item(symbol: SymbolRecord, rel_path: str) -> dict[str, Any]:
    """Convert a local symbol record to the CLI result shape."""
    return {
        "symbol_id": symbol["symbol_id"],
        "qualified_name": symbol["qualified_name"],
        "name": symbol["name"],
        "kind": symbol["kind"],
        "signature": symbol["signature"],
        "summary": symbol.get("summary"),
        "language": symbol["language"],
        "start_line": symbol["start_line"],
        "end_line": symbol["end_line"],
        "file_path": rel_path,
    }


def _search_checkout_symbols(root: Path, query: str, *, limit: int) -> dict[str, Any]:
    """Search current-checkout symbols by extracting supported files locally."""
    query_terms = _expand_symbol_queries(query)
    candidate_paths: list[Path] = []
    seen_candidate_paths: set[Path] = set()
    for query_term in query_terms:
        for candidate in _ripgrep_candidate_paths(
            root,
            query_term,
            limit=max(limit * 3, _CHECKOUT_CANDIDATE_LIMIT),
            suffixes=_SUPPORTED_SYMBOL_EXTENSIONS,
        ):
            if candidate in seen_candidate_paths:
                continue
            seen_candidate_paths.add(candidate)
            candidate_paths.append(candidate)
    if not candidate_paths:
        candidate_paths = _iter_checkout_files(root, allowed_suffixes=_SUPPORTED_SYMBOL_EXTENSIONS)

    seen: set[tuple[str, str, int]] = set()
    scored_items: list[tuple[int, dict[str, Any]]] = []
    for path in candidate_paths:
        rel_path = _normalize_rel_path(root, path)
        if rel_path is None:
            continue
        for symbol in extract_symbols(path, rel_path):
            score = _symbol_score(symbol, rel_path, query_terms)
            if score <= 0:
                continue
            key = (rel_path, symbol["symbol_id"], symbol["start_line"])
            if key in seen:
                continue
            seen.add(key)
            scored_items.append((score, _symbol_record_to_item(symbol, rel_path)))

    scored_items.sort(
        key=lambda item: (
            -item[0],
            str(item[1].get("file_path", "")),
            int(item[1].get("start_line", 0) or 0),
            str(item[1].get("qualified_name", "")),
        )
    )
    items = [item for _, item in scored_items[:limit]]
    return {
        "query": query,
        "count": len(items),
        "items": items,
        "scope": "checkout",
        "root_path": str(root),
    }


def _search_checkout_file_symbols(root: Path, file_path: str, *, limit: int) -> dict[str, Any]:
    """List symbols for a specific file from the current checkout."""
    absolute_path = (root / file_path).resolve()
    rel_path = _normalize_rel_path(root, absolute_path)
    if rel_path is None or not absolute_path.is_file():
        return {"file_path": file_path, "count": 0, "items": [], "scope": "checkout", "root_path": str(root)}

    items = [_symbol_record_to_item(symbol, rel_path) for symbol in extract_symbols(absolute_path, rel_path)[:limit]]
    return {
        "file_path": rel_path,
        "count": len(items),
        "items": items,
        "scope": "checkout",
        "root_path": str(root),
    }


def _read_checkout_snippet(root: Path, rel_path: str, start_line: int, end_line: int | None) -> str:
    """Read a compact source snippet for a local symbol hit."""
    absolute_path = (root / rel_path).resolve()
    try:
        lines = absolute_path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return ""

    line_start = max(1, start_line - 1)
    line_end = min(len(lines), max(end_line or start_line, start_line) + 1)
    return "\n".join(lines[line_start - 1:line_end]).rstrip()


def _build_checkout_symbol_prompt(root: Path, items: list[dict[str, Any]]) -> str:
    """Build prompt-ready symbol context from current checkout files."""
    lines = ["## Current Checkout Overrides", ""]
    for item in items:
        detail = item.get("summary") or item.get("signature") or ""
        suffix = f" - {detail}" if detail else ""
        lines.append(
            f"- `{item.get('qualified_name', item.get('name', 'unknown'))}` "
            f"({item.get('kind', 'unknown')}) in {item.get('file_path', 'unknown')}:{item.get('start_line', '?')}{suffix}"
        )

    slice_items = items[: min(len(items), 5)]
    if slice_items:
        lines.append("")
        for item in slice_items:
            snippet = _read_checkout_snippet(
                root,
                str(item.get("file_path", "")),
                int(item.get("start_line", 1) or 1),
                int(item.get("end_line", 0) or 0) or None,
            )
            if not snippet:
                continue
            lines.extend(
                [
                    f"### `{item.get('qualified_name', item.get('name', 'unknown'))}` "
                    f"({item.get('file_path', 'unknown')}:{item.get('start_line', '?')}-{item.get('end_line', '?')})",
                    "```",
                    snippet,
                    "```",
                    "",
                ]
            )
    return "\n".join(lines).strip()


def _build_checkout_text_prompt(result: dict[str, Any]) -> str:
    """Build prompt-ready text context from current checkout files."""
    lines = ["## Current Checkout Matches", ""]
    for item in result.get("items", []):
        if not isinstance(item, dict):
            continue
        lines.append(f"- {item.get('path', 'unknown')}:{item.get('line', '?')} - {item.get('content', '')}")
    return "\n".join(lines).strip()


def _build_checkout_precision_result(query: str, checkout_root: Path, budget: int, limit: int) -> dict[str, Any]:
    """Build a prompt-ready precision result from the current checkout only."""
    symbol_result = _search_checkout_symbols(checkout_root, query, limit=limit)
    if symbol_result.get("items"):
        body = _build_checkout_symbol_prompt(checkout_root, symbol_result["items"])
        prompt_context = _truncate_prompt_to_budget(body, budget)
        return {
            "query": query,
            "prompt_context": prompt_context,
            "metadata": {
                "scope": "checkout",
                "checkout_root": str(checkout_root),
                "symbol_count": symbol_result.get("count", 0),
                "text_match_count": 0,
                "text_files_searched": 0,
                "used_symbol_first": True,
                "used_fallback": False,
                "estimated_tokens_saved": 0,
                "final_tokens": estimate_tokens(prompt_context),
            },
        }

    text_result = _search_checkout_text(checkout_root, query, limit=limit)
    if text_result.get("items"):
        body = _build_checkout_text_prompt(text_result)
        prompt_context = _truncate_prompt_to_budget(body, budget)
        return {
            "query": query,
            "prompt_context": prompt_context,
            "metadata": {
                "scope": "checkout",
                "checkout_root": str(checkout_root),
                "symbol_count": 0,
                "text_match_count": text_result.get("count", 0),
                "text_files_searched": text_result.get("files_searched", 0),
                "used_symbol_first": False,
                "used_fallback": True,
                "estimated_tokens_saved": 0,
                "final_tokens": estimate_tokens(prompt_context),
            },
        }

    return {
        "query": query,
        "prompt_context": "",
        "metadata": {
            "scope": "checkout",
            "checkout_root": str(checkout_root),
            "symbol_count": 0,
            "text_match_count": 0,
            "text_files_searched": text_result.get("files_searched", 0),
            "used_symbol_first": False,
            "used_fallback": False,
            "estimated_tokens_saved": 0,
            "final_tokens": 0,
        },
    }


def _merge_precision_results(
    query: str,
    project_result: dict[str, Any],
    checkout_result: dict[str, Any],
    roots: SearchRoots,
    budget: int,
) -> dict[str, Any]:
    """Merge local checkout context ahead of canonical indexed project context."""
    checkout_prompt = str(checkout_result.get("prompt_context", "") or "")
    if not checkout_prompt:
        return project_result

    project_prompt = str(project_result.get("prompt_context", "") or "")
    combined_prompt = checkout_prompt
    scope = "checkout"
    if project_prompt:
        combined_prompt = f"{checkout_prompt}\n\n## Indexed Project Context\n\n{project_prompt}"
        scope = "combined"
    combined_prompt = _truncate_prompt_to_budget(combined_prompt, budget)

    project_metadata = dict(project_result.get("metadata", {}))
    checkout_metadata = dict(checkout_result.get("metadata", {}))
    combined_metadata = {**project_metadata}
    combined_metadata.update(
        {
            "scope": scope,
            "checkout_root": checkout_metadata.get("checkout_root"),
            "project_root": str(roots.project_root) if roots.project_root else None,
            "checkout_overlay_applied": True,
            "checkout_symbol_count": checkout_metadata.get("symbol_count", 0),
            "checkout_text_match_count": checkout_metadata.get("text_match_count", 0),
            "symbol_count": max(
                int(project_metadata.get("symbol_count", 0) or 0),
                int(checkout_metadata.get("symbol_count", 0) or 0),
            ),
            "text_match_count": int(project_metadata.get("text_match_count", 0) or 0)
            + int(checkout_metadata.get("text_match_count", 0) or 0),
            "used_symbol_first": bool(checkout_metadata.get("used_symbol_first", False)),
            "used_fallback": bool(checkout_metadata.get("used_fallback", False)),
            "estimated_tokens_saved": max(
                int(project_metadata.get("estimated_tokens_saved", 0) or 0),
                int(checkout_metadata.get("estimated_tokens_saved", 0) or 0),
            ),
            "final_tokens": estimate_tokens(combined_prompt),
        }
    )
    return {
        "query": query,
        "prompt_context": combined_prompt,
        "metadata": combined_metadata,
    }


@app.command()
def search(
    project: Annotated[
        str | None,
        typer.Option("--project", "-P", help="Project ID (overrides auto-detection for this search)"),
    ] = None,
    query: Annotated[
        list[str] | None,
        typer.Argument(help="Search query (symbol name, function, class, endpoint)"),
    ] = None,
    budget: Annotated[
        int,
        typer.Option("--budget", "-b", help="Token budget for prompt context"),
    ] = 1200,
    limit: Annotated[
        int,
        typer.Option("--limit", "-l", help="Maximum primitive results"),
    ] = 20,
    text: Annotated[
        bool,
        typer.Option("--text", help="Use the text/content search primitive"),
    ] = False,
    symbols: Annotated[
        bool,
        typer.Option("--symbols", help="Use the symbol search primitive"),
    ] = False,
    raw_json: Annotated[
        bool,
        typer.Option("--json", "-j", help="Emit full JSON payload"),
    ] = False,
    file: Annotated[
        str | None,
        typer.Option("--file", "-f", help="List all symbols in a specific file"),
    ] = None,
    hint: Annotated[
        bool,
        typer.Option("--hint/--no-hint", help="Show refinement hints when results are poor"),
    ] = True,
    scope: Annotated[
        SearchScope,
        typer.Option(
            "--scope",
            help="Search scope: canonical project index, current checkout/worktree, or auto-detect both when needed",
            case_sensitive=False,
        ),
    ] = SearchScope.AUTO,
) -> None:
    """Search codebase symbols, endpoints, and tables with Precision Code Search.

    Returns prompt-ready context with symbol source slices, related endpoints,
    and database tables. Uses indexed symbols first, falls back to file/endpoint
    matching when no symbols match.

    Examples:
        st search collect_precision_code_search_context
        st search "TaskOperationsMixin"
        st search router endpoint --budget 2000
        st search scan_history --json
    """
    q = " ".join(query).strip() if query else ""
    if not q and not file:
        typer.echo("Error: empty query", err=True)
        raise typer.Exit(1)
    if text and symbols:
        typer.echo("Error: choose at most one primitive mode", err=True)
        raise typer.Exit(1)

    roots = _resolve_search_roots(project, scope)
    if scope == SearchScope.CHECKOUT and roots.checkout_root is None:
        typer.echo("Error: --scope checkout requires a git checkout", err=True)
        raise typer.Exit(1)

    client: STClient | None = None

    if file:
        if roots.effective_scope in {"checkout", "combined"} and roots.checkout_root is not None:
            result = _search_checkout_file_symbols(roots.checkout_root, file, limit=limit)
        else:
            client = STClient(project_id=project) if project else STClient()
            params = urlencode({"file_path": file, "limit": limit})
            try:
                result = client.get(client._url(f"/explorer/symbols/by-file?{params}"))
            except APIError as e:
                handle_api_error(e)
                return
        if raw_json:
            output_json(result)
            return
        if is_compact():
            _print_file_symbols_compact(str(result.get("file_path", file)), result)
        else:
            output_json(result)
        return

    try:
        if text:
            if roots.effective_scope in {"checkout", "combined"} and roots.checkout_root is not None:
                result = _search_checkout_text(roots.checkout_root, q, limit=limit)
            else:
                client = STClient(project_id=project) if project else STClient()
                params = urlencode({"q": q, "limit": limit})
                result = client.get(client._url(f"/explorer/text/search?{params}"))
        elif symbols:
            if roots.effective_scope in {"checkout", "combined"} and roots.checkout_root is not None:
                local_result = _search_checkout_symbols(roots.checkout_root, q, limit=limit)
                if local_result.get("count") or roots.effective_scope == "checkout":
                    result = local_result
                else:
                    client = STClient(project_id=project) if project else STClient()
                    params = urlencode({"q": q, "limit": limit})
                    result = client.get(client._url(f"/explorer/symbols/search?{params}"))
            else:
                client = STClient(project_id=project) if project else STClient()
                params = urlencode({"q": q, "limit": limit})
                result = client.get(client._url(f"/explorer/symbols/search?{params}"))
        else:
            if roots.effective_scope == "checkout" and roots.checkout_root is not None:
                result = _build_checkout_precision_result(q, roots.checkout_root, budget, limit)
            else:
                client = STClient(project_id=project) if project else STClient()
                project_result = _run_precision_search(client, q, budget, limit)
                if roots.effective_scope == "combined" and roots.checkout_root is not None:
                    checkout_result = _build_checkout_precision_result(q, roots.checkout_root, budget, limit)
                    result = _merge_precision_results(q, project_result, checkout_result, roots, budget)
                else:
                    result = project_result
    except APIError as e:
        handle_api_error(e)
        return

    if not raw_json and not text and not symbols:
        _emit_precision_search_metadata_note(result.get("metadata", {}))

    if raw_json:
        output_json(result)
        return

    if is_compact():
        if text:
            _print_text_compact(q, result)
        elif symbols:
            _print_symbols_compact(q, result)
        else:
            _print_precision_compact(q, result.get("prompt_context", ""), result.get("metadata", {}), show_hint=hint)
    else:
        output_json(result)


def _scope_suffix(scope: str | None) -> str:
    """Return a compact scope suffix when results are not canonical-project only."""
    if not scope or scope == "project":
        return ""
    return f"|scope={scope}"


def _truncate_prompt_to_budget(text: str, budget: int) -> str:
    """Trim prompt text until the local token estimator is within the requested budget."""
    truncated = truncate_to_tokens(text, budget)
    if estimate_tokens(truncated) <= budget:
        return truncated

    best = ""
    low = 0
    high = len(truncated)
    while low <= high:
        midpoint = (low + high) // 2
        candidate = truncated[:midpoint].rstrip()
        if estimate_tokens(candidate) <= budget:
            best = candidate
            low = midpoint + 1
        else:
            high = midpoint - 1
    return best.rstrip()


def _print_precision_compact(
    query: str, prompt_context: str, metadata: dict, *, show_hint: bool = True
) -> None:
    """Print TOON-style compact output for agent consumption."""
    symbol_count = metadata.get("symbol_count", 0)
    mode = "symbol-first" if metadata.get("used_symbol_first") else "text-fallback"
    tokens_saved = metadata.get("estimated_tokens_saved", 0)
    final_tokens = metadata.get("final_tokens", 0)
    scope_suffix = _scope_suffix(metadata.get("scope"))

    if not prompt_context:
        print(f"SEARCH:{query}|mode=empty|symbols=0|tokens=0{scope_suffix}")
        if show_hint:
            hint_text = _generate_hint(query, "empty", metadata)
            if hint_text:
                print(f"{_HINT_PREFIX}{hint_text}")
        return

    print(
        f"SEARCH:{query}|mode={mode}|symbols={symbol_count}"
        f"|tokens={final_tokens}|saved={tokens_saved}{scope_suffix}"
    )
    if show_hint:
        hint_text = _generate_hint(query, mode, metadata)
        if hint_text:
            print(f"{_HINT_PREFIX}{hint_text}")
    print()
    print(prompt_context)


def _print_text_compact(query: str, result: dict) -> None:
    """Print TOON-style compact text search output."""
    items = result.get("items", [])
    count = result.get("count", len(items) if isinstance(items, list) else 0)
    files_searched = result.get("files_searched", 0)
    scope_suffix = _scope_suffix(result.get("scope"))

    if not items:
        print(f"SEARCH:{query}|mode=empty|symbols=0|tokens=0{scope_suffix}")
        return

    print(f"SEARCH:{query}|mode=text|matches={count}|files={files_searched}{scope_suffix}")
    print()
    for item in items:
        if not isinstance(item, dict):
            continue
        print(f"- {item.get('path', 'unknown')}:{item.get('line', '?')} | {item.get('content', '')}")


def _print_symbols_compact(query: str, result: dict) -> None:
    """Print TOON-style compact symbol search output."""
    items = result.get("items", [])
    count = result.get("count", len(items) if isinstance(items, list) else 0)
    scope_suffix = _scope_suffix(result.get("scope"))

    if not items:
        print(f"SEARCH:{query}|mode=empty|symbols=0|tokens=0{scope_suffix}")
        return

    print(f"SEARCH:{query}|mode=symbols|symbols={count}{scope_suffix}")
    print()
    for item in items:
        if not isinstance(item, dict):
            continue
        print(
            f"- `{item.get('qualified_name', item.get('name', 'unknown'))}` "
            f"({item.get('kind', 'unknown')}) {item.get('file_path', 'unknown')}:{item.get('start_line', '?')}"
        )


def _print_file_symbols_compact(file_path: str, result: dict) -> None:
    """Print TOON-style compact output for file symbol listing."""
    items = result.get("items", [])
    count = result.get("count", len(items) if isinstance(items, list) else 0)
    scope_suffix = _scope_suffix(result.get("scope"))

    if not items:
        print(f"SEARCH:--file {file_path}|mode=empty|symbols=0|tokens=0{scope_suffix}")
        return

    print(f"SEARCH:--file {file_path}|mode=file-symbols|symbols={count}{scope_suffix}")
    print()
    for item in items:
        if not isinstance(item, dict):
            continue
        kind = item.get("kind", "unknown")
        name = item.get("qualified_name", item.get("name", "unknown"))
        line = item.get("start_line", "?")
        sig = item.get("signature", "")
        summary = item.get("summary", "")
        detail = sig or summary
        suffix = f" - {detail}" if detail else ""
        print(f"- `{name}` ({kind}) :{line}{suffix}")
