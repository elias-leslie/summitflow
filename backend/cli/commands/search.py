"""Precision Code Search CLI command."""

from __future__ import annotations

import re
import threading
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import urlencode

import typer

from .._output_state import is_compact
from ..client import APIError, STClient
from ..config import get_config_optional, get_project_root_path
from ..lib.execution_context import (
    canonical_repo_root,
    resolve_checkout_project_id,
    resolve_checkout_root,
)
from ..lib.search_checkout import (
    _build_checkout_precision_result,
    _checkout_has_local_changes,
    _normalize_path_prefix,
    _search_checkout_file_symbols,
    _search_checkout_symbols,
    _search_checkout_text,
)
from ..lib.search_models import SearchRoots, SearchScope
from ..lib.search_output import (
    _print_file_symbols_compact,
    _print_precision_compact,
    _print_symbols_compact,
    _print_text_compact,
)
from ..lib.search_results import _merge_precision_results
from ..lib.usage import usage
from ..output import handle_api_error, output_json

app = typer.Typer(help="Precision Code Search")

ProjectOption = Annotated[str | None, typer.Option("--project", "-P", help="Project ID (overrides auto-detection for this search)")]
QueryArgument = Annotated[list[str] | None, typer.Argument(help="Search query (symbol name, function, class, endpoint)")]
BudgetOption = Annotated[int, typer.Option("--budget", "-b", help="Token budget for prompt context")]
LimitOption = Annotated[int, typer.Option("--limit", "-l", help="Maximum primitive results")]
TextOption = Annotated[bool, typer.Option("--text", help="Use the text/content search primitive")]
SymbolsOption = Annotated[bool, typer.Option("--symbols", help="Use the symbol search primitive")]
JsonOption = Annotated[bool, typer.Option("--json", "-j", help="Emit full JSON payload")]
FileOption = Annotated[str | None, typer.Option("--file", "-f", help="List all symbols in a specific file")]
PathOption = Annotated[str | None, typer.Option("--path", help="Restrict search to a relative file/subtree prefix")]
HintOption = Annotated[bool, typer.Option("--hint/--no-hint", help="Show refinement hints when results are poor")]
ScopeOption = Annotated[
    SearchScope,
    typer.Option(
        "--scope",
        help="Search scope: canonical project index, current checkout, or auto-detect both when needed",
        case_sensitive=False,
    ),
]

_SEARCH_PROGRESS_DELAY_SECONDS = 1.5
_MAX_RESULT_LIMIT = 20
_SEARCH_PROGRESS_MESSAGE = (
    "st search: still working; first precision search may refresh stale Explorer indexes before returning results."
)


def _emit_status(message: str) -> None:
    """Write a human-oriented status line to stderr without polluting stdout payloads."""
    typer.echo(message, err=True)


def _start_delayed_status_timer(message: str) -> threading.Timer:
    """Start a delayed stderr status note for slow precision searches."""
    timer = threading.Timer(_SEARCH_PROGRESS_DELAY_SECONDS, _emit_status, args=(message,))
    timer.daemon = True
    timer.start()
    return timer


def _normalize_limit(limit: int) -> int:
    if limit <= _MAX_RESULT_LIMIT:
        return limit
    _emit_status(f"st search: --limit {limit} capped at {_MAX_RESULT_LIMIT}.")
    return _MAX_RESULT_LIMIT


def _run_precision_search(
    client: STClient,
    query: str,
    budget: int,
    limit: int,
    *,
    path_prefix: str | None = None,
) -> dict[str, Any]:
    """Run precision search with a delayed status line so stale refreshes don't look hung."""
    params = _params(q=query, budget=budget, limit=limit, path_prefix=path_prefix)
    timer = _start_delayed_status_timer(_SEARCH_PROGRESS_MESSAGE)
    try:
        return client.get(client._url(f"/explorer/precision-search?{params}"))
    finally:
        timer.cancel()


def _emit_precision_search_metadata_note(metadata: dict[str, Any]) -> None:
    """Explain stale-index behavior after the search completes when relevant."""
    if metadata.get("refreshed_index"):
        _emit_status("st search: refreshed stale Explorer indexes before returning results.")
        return
    has_usable_results = any(
        int(metadata.get(key) or 0) > 0
        for key in ("final_tokens", "symbol_count", "text_match_count")
    )
    if metadata.get("stale_hit") and not has_usable_results:
        reasons = {str(reason) for reason in (metadata.get("refresh_reasons") or [])}
        if reasons - {"stale_file_index", "stale_symbol_index"}:
            # Missing index or timestamp triggers an inline refresh; reaching here means it failed.
            _emit_status(
                "st search: Explorer indexes are stale and refresh did not complete; verify results carefully or rerun after scan."
            )
        else:
            age = metadata.get("symbol_index_age_minutes")
            age_note = f" ({age}m old)" if isinstance(age, int) and age > 0 else ""
            _emit_status(
                f"st search: no matches; the symbol index{age_note} predates the latest scheduled scan — "
                "brand-new identifiers may not be indexed yet."
            )
    if metadata.get("checkout_overlay_applied"):
        _emit_status("st search: prepended current checkout results ahead of indexed project context.")


def _resolve_search_roots(project_override: str | None, scope: SearchScope) -> SearchRoots:
    """Resolve canonical project and current-checkout roots for this search."""
    checkout_root = resolve_checkout_root()
    canonical_root = canonical_repo_root()
    config = get_config_optional()
    selected_project_id = project_override or config.project_id or None
    checkout_project_id = resolve_checkout_project_id()
    if selected_project_id and checkout_project_id and selected_project_id != checkout_project_id:
        return _resolve_cross_project_roots(selected_project_id, scope)

    checkout_has_changes = _checkout_has_local_changes(checkout_root)
    if scope == SearchScope.CHECKOUT:
        return SearchRoots(scope, "checkout" if checkout_root else "project", None, checkout_root, checkout_has_changes)

    project_root = _project_root(config.project_root, selected_project_id, checkout_project_id, canonical_root)
    effective_scope = _effective_scope(scope, selected_project_id, checkout_project_id, checkout_root, project_root, checkout_has_changes)
    checkout_is_project = bool(
        checkout_root is not None
        and checkout_project_id is not None
        and (selected_project_id is None or selected_project_id == checkout_project_id)
    )
    return SearchRoots(scope, effective_scope, project_root, checkout_root, checkout_has_changes, checkout_is_project)


def _resolve_cross_project_roots(selected_project_id: str, scope: SearchScope) -> SearchRoots:
    """The cwd checkout belongs to a different project than the one being
    searched, so it must never be used as the live tree — the only valid
    live tree is the selected project's registered root."""
    if scope == SearchScope.CHECKOUT:
        target_root = _registered_project_root(selected_project_id)
        if target_root is None:
            typer.echo(
                f"Error: --scope checkout needs a local root for project `{selected_project_id}`, but none is "
                "registered or present on this host — drop --scope checkout to search its index, or rescan the project.",
                err=True,
            )
            raise typer.Exit(1)
        return SearchRoots(scope, "checkout", target_root, target_root, _checkout_has_local_changes(target_root), True)
    # Defer the root lookup: AUTO/PROJECT searches only need it if an
    # identifier miss escalates to a live parse of the target tree.
    return SearchRoots(scope, "project", None, None, False, False, selected_project_id)


def _registered_project_root(project_id: str) -> Path | None:
    root_path = get_project_root_path(project_id)
    if not root_path:
        return None
    root = Path(root_path).resolve()
    return root if root.is_dir() else None


def _project_root(
    configured_root: str | None,
    selected_project_id: str | None,
    checkout_project_id: str | None,
    canonical_root: Path | None,
) -> Path | None:
    if configured_root:
        return Path(configured_root).resolve()
    if selected_project_id and checkout_project_id and selected_project_id == checkout_project_id:
        return canonical_root
    return None


def _effective_scope(
    scope: SearchScope,
    selected_project_id: str | None,
    checkout_project_id: str | None,
    checkout_root: Path | None,
    project_root: Path | None,
    checkout_has_changes: bool,
) -> str:
    if scope == SearchScope.PROJECT or (selected_project_id and checkout_project_id and selected_project_id != checkout_project_id):
        return "project"
    if checkout_root and project_root and checkout_root != project_root and checkout_has_changes:
        return "combined"
    if checkout_root and project_root is None and selected_project_id is None:
        return "checkout"
    return "project"


def _search_client(project: str | None) -> STClient:
    return STClient(project_id=project) if project else STClient()


def _params(**values: Any) -> str:
    return urlencode({key: value for key, value in values.items() if value is not None})


def _remote_result(project: str | None, endpoint: str, **params: Any) -> dict[str, Any]:
    client = _search_client(project)
    return client.get(client._url(f"{endpoint}?{_params(**params)}"))


def _file_result(roots: SearchRoots, project: str | None, file_path: str, limit: int) -> dict[str, Any]:
    if roots.effective_scope in {"checkout", "combined"} and roots.checkout_root is not None:
        return _search_checkout_file_symbols(roots.checkout_root, file_path, limit=limit)
    return _remote_result(project, "/explorer/symbols/by-file", file_path=file_path, limit=limit)


def _text_result(roots: SearchRoots, project: str | None, query: str, limit: int, path_prefix: str | None) -> dict[str, Any]:
    if roots.effective_scope in {"checkout", "combined"} and roots.checkout_root is not None:
        return _search_checkout_text(roots.checkout_root, query, limit=limit, path_prefix=path_prefix)
    return _remote_result(project, "/explorer/text/search", q=query, limit=limit, path_prefix=path_prefix)


def _symbols_result(roots: SearchRoots, project: str | None, query: str, limit: int, path_prefix: str | None) -> dict[str, Any]:
    if roots.effective_scope not in {"checkout", "combined"} or roots.checkout_root is None:
        return _remote_result(project, "/explorer/symbols/search", q=query, limit=limit, path_prefix=path_prefix)

    local_result = _search_checkout_symbols(roots.checkout_root, query, limit=limit, path_prefix=path_prefix)
    if local_result.get("count") or roots.effective_scope == "checkout":
        return local_result
    return _remote_result(project, "/explorer/symbols/search", q=query, limit=limit, path_prefix=path_prefix)


def _precision_result(
    roots: SearchRoots,
    project: str | None,
    query: str,
    budget: int,
    limit: int,
    path_prefix: str | None,
) -> dict[str, Any]:
    if roots.effective_scope == "checkout" and roots.checkout_root is not None:
        return _build_checkout_precision_result(query, roots.checkout_root, budget, limit, path_prefix=path_prefix)

    project_result = _run_precision_search(_search_client(project), query, budget, limit, path_prefix=path_prefix)
    if roots.effective_scope == "combined" and roots.checkout_root is not None:
        checkout_result = _build_checkout_precision_result(query, roots.checkout_root, budget, limit, path_prefix=path_prefix)
        return _merge_precision_results(query, project_result, checkout_result, roots, budget)
    if _should_escalate_to_checkout(roots, query, project_result):
        live_root = roots.checkout_root if roots.checkout_is_project else _registered_project_root(roots.cross_project_id or "")
        if live_root is not None:
            checkout_result = _build_checkout_precision_result(query, live_root, budget, limit, path_prefix=path_prefix)
            if int((checkout_result.get("metadata") or {}).get("symbol_count") or 0) > 0:
                return _merge_precision_results(query, project_result, checkout_result, roots, budget)
    return project_result


def _should_escalate_to_checkout(roots: SearchRoots, query: str, project_result: dict[str, Any]) -> bool:
    """Escalate to live symbol parsing when the canonical symbol index
    returned nothing for an identifier-shaped query — the index may simply
    be stale for fresh code. The live tree is the cwd checkout when it backs
    the searched project, or the target project's registered root for
    cross-project searches. Prose queries stay out: checkout symbol search
    fuzzy-matches individual words and would amplify junk."""
    if roots.scope != SearchScope.AUTO or not (roots.checkout_is_project or roots.cross_project_id):
        return False
    if not _has_identifier_shaped_term(query):
        return False
    metadata = project_result.get("metadata") or {}
    return int(metadata.get("symbol_count") or 0) == 0


def _has_identifier_shaped_term(query: str) -> bool:
    return any("_" in term or re.search(r"[a-z][A-Z]", term) for term in query.split())


def _emit_file_output(file_path: str, result: dict[str, Any], raw_json: bool) -> None:
    if raw_json:
        output_json(result)
    elif is_compact():
        _print_file_symbols_compact(str(result.get("file_path", file_path)), result)
    else:
        output_json(result)


def _emit_query_output(query: str, result: dict[str, Any], text: bool, symbols: bool, hint: bool) -> None:
    if is_compact():
        if text:
            _print_text_compact(query, result)
        elif symbols:
            _print_symbols_compact(query, result)
        else:
            _print_precision_compact(query, result.get("prompt_context", ""), result.get("metadata", {}), show_hint=hint)
        return
    output_json(result)


@app.command()
@usage(
    surface="st.search",
    cmd='st search "query"',
    when="repo/code discovery; before adding any function/endpoint/command/component — search first and extend a close match instead of writing new",
    precautions=(
        "prefer over rg/grep/find/st memory search",
        "best with 1-4 identifier-shaped terms (CamelCase/snake_case/filenames); for prose questions use --text with a literal phrase",
        "if mode=text-fallback or empty, reshape the query (different identifier, --text phrase, or --file/--path) — never retry verbatim; if the hint says a definition was missed, the symbol index is stale — follow the hint (--scope checkout or rescan), do not reshape",
        "on a close match, extend/reuse it rather than adding a near-duplicate",
    ),
    tier="mandate",
)
def search(
    project: ProjectOption = None,
    query: QueryArgument = None,
    budget: BudgetOption = 1200,
    limit: LimitOption = 20,
    text: TextOption = False,
    symbols: SymbolsOption = False,
    raw_json: JsonOption = False,
    file: FileOption = None,
    path: PathOption = None,
    hint: HintOption = True,
    scope: ScopeOption = SearchScope.AUTO,
) -> None:
    """Search codebase symbols, endpoints, and tables with Precision Code Search."""
    q = " ".join(query).strip() if query else ""
    limit = _normalize_limit(limit)
    normalized_path = _normalize_path_prefix(path)
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

    try:
        if file:
            _emit_file_output(file, _file_result(roots, project, file, limit), raw_json)
            return
        result = _text_result(roots, project, q, limit, normalized_path) if text else _query_result(roots, project, q, budget, limit, normalized_path, symbols)
    except APIError as e:
        handle_api_error(e)
        return

    if raw_json:
        output_json(result)
        return
    if not text and not symbols:
        _emit_precision_search_metadata_note(result.get("metadata", {}))
    _emit_query_output(q, result, text, symbols, hint)


def _query_result(
    roots: SearchRoots,
    project: str | None,
    query: str,
    budget: int,
    limit: int,
    path_prefix: str | None,
    symbols: bool,
) -> dict[str, Any]:
    if symbols:
        return _symbols_result(roots, project, query, limit, path_prefix)
    return _precision_result(roots, project, query, budget, limit, path_prefix)
