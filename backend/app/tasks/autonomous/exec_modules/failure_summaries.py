"""Helpers for concise but actionable autonomous failure summaries."""

from __future__ import annotations

from typing import Any

_MAX_DETAIL_CHARS = 220


def _clean_text(value: object, *, limit: int = _MAX_DETAIL_CHARS) -> str:
    """Normalize whitespace and trim verbose command output for summaries."""
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _summarize_failed_step(step: dict[str, Any]) -> str:
    """Summarize a single failed step using reason plus useful detail when present."""
    reason = _clean_text(step.get("reason") or step.get("error") or "unknown", limit=80)
    output = _clean_text(step.get("output") or step.get("detail") or step.get("message"))

    if output:
        output_lower = output.lower()
        reason_lower = reason.lower()
        if reason_lower and reason_lower in output_lower:
            return output
        return f"{reason}: {output}" if reason else output
    return reason or "unknown"


def summarize_failed_steps(step_results: list[dict[str, Any]], *, max_items: int = 2) -> str:
    """Return an actionable summary for the first few failed steps."""
    failed = [step for step in step_results if not step.get("passed")]
    if not failed:
        return "no failure details"

    parts = [_summarize_failed_step(step) for step in failed[:max_items]]
    return "; ".join(part for part in parts if part) or "unknown"
