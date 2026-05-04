"""Precision search result composition helpers."""

from __future__ import annotations

from typing import Any

from app.services.context_gatherer.token_utils import estimate_tokens

from .search_budget import truncate_prompt_to_budget
from .search_models import SearchRoots


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
    combined_prompt = _combined_prompt(checkout_prompt, project_prompt)
    combined_prompt = truncate_prompt_to_budget(combined_prompt, budget)

    project_metadata = dict(project_result.get("metadata", {}))
    checkout_metadata = dict(checkout_result.get("metadata", {}))
    scope = "combined" if project_prompt else "checkout"
    combined_metadata = _merged_metadata(project_metadata, checkout_metadata, roots, combined_prompt, scope)
    return {
        "query": query,
        "prompt_context": combined_prompt,
        "metadata": combined_metadata,
    }


def _combined_prompt(checkout_prompt: str, project_prompt: str) -> str:
    if project_prompt:
        return f"{checkout_prompt}\n\n## Indexed Project Context\n\n{project_prompt}"
    return checkout_prompt


def _merged_metadata(
    project_metadata: dict[str, Any],
    checkout_metadata: dict[str, Any],
    roots: SearchRoots,
    combined_prompt: str,
    scope: str,
) -> dict[str, Any]:
    combined_metadata = {**project_metadata}
    combined_metadata.update(
        {
            "scope": scope,
            "checkout_root": checkout_metadata.get("checkout_root"),
            "project_root": str(roots.project_root) if roots.project_root else None,
            "path_prefix": checkout_metadata.get("path_prefix") or project_metadata.get("path_prefix"),
            "checkout_overlay_applied": True,
            "checkout_symbol_count": checkout_metadata.get("symbol_count", 0),
            "checkout_text_match_count": checkout_metadata.get("text_match_count", 0),
            "symbol_count": max(_metadata_int(project_metadata, "symbol_count"), _metadata_int(checkout_metadata, "symbol_count")),
            "text_match_count": _metadata_int(project_metadata, "text_match_count") + _metadata_int(checkout_metadata, "text_match_count"),
            "used_symbol_first": bool(checkout_metadata.get("used_symbol_first", False)),
            "used_fallback": bool(checkout_metadata.get("used_fallback", False)),
            "estimated_tokens_saved": max(
                _metadata_int(project_metadata, "estimated_tokens_saved"),
                _metadata_int(checkout_metadata, "estimated_tokens_saved"),
            ),
            "final_tokens": estimate_tokens(combined_prompt),
        }
    )
    return combined_metadata


def _metadata_int(metadata: dict[str, Any], key: str) -> int:
    return int(metadata.get(key, 0) or 0)
