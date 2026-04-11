"""Low-friction compactness heuristics for prompt and memory authoring."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Literal

from app.services.context_gatherer.token_utils import estimate_tokens

from ..output import output_warning

ContentKind = Literal["prompt", "memory"]

_FILLER_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("just", re.compile(r"\bjust\b", re.IGNORECASE)),
    ("really", re.compile(r"\breally\b", re.IGNORECASE)),
    ("basically", re.compile(r"\bbasically\b", re.IGNORECASE)),
    ("please", re.compile(r"\bplease\b", re.IGNORECASE)),
    ("let me know", re.compile(r"\blet me know\b", re.IGNORECASE)),
    ("feel free", re.compile(r"\bfeel free\b", re.IGNORECASE)),
    ("i recommend", re.compile(r"\bi recommend\b", re.IGNORECASE)),
    ("i suggest", re.compile(r"\bi suggest\b", re.IGNORECASE)),
    ("you should", re.compile(r"\byou should\b", re.IGNORECASE)),
    ("make sure", re.compile(r"\bmake sure\b", re.IGNORECASE)),
)
_EXAMPLE_PATTERN = re.compile(r"\bfor example\b|\be\.g\.\b|example:", re.IGNORECASE)


@dataclass(frozen=True)
class CompactnessReport:
    kind: ContentKind
    chars: int
    lines: int
    tokens: int
    warnings: tuple[str, ...]


def _line_count(content: str) -> int:
    return content.count("\n") + (1 if content and not content.endswith("\n") else 0)


def _detect_fillers(content: str) -> list[str]:
    hits: list[str] = []
    for label, pattern in _FILLER_PATTERNS:
        if pattern.search(content):
            hits.append(label)
    return hits


def analyze_compactness(content: str, *, kind: ContentKind) -> CompactnessReport:
    """Estimate authoring size and flag obvious filler-heavy prose."""
    chars = len(content)
    lines = _line_count(content)
    tokens = estimate_tokens(content)
    warnings: list[str] = []
    filler_hits = _detect_fillers(content)

    if kind == "prompt":
        if tokens > 350:
            warnings.append(
                f"large prompt ({tokens} tok). Hot-path prompts pay this every turn."
            )
        if lines > 80:
            warnings.append(
                f"long prompt ({lines} lines). Collapse repeated examples and overlap."
            )
    else:
        if chars > 280:
            warnings.append(
                f"long memory ({chars} chars). Keep one atomic rule; split if needed."
            )
        if lines > 4:
            warnings.append(
                f"multi-line memory ({lines} lines). Prefer one short rule body."
            )

    if filler_hits:
        warnings.append(f"filler terms found: {', '.join(filler_hits[:4])}")

    if len(_EXAMPLE_PATTERN.findall(content)) > 1:
        warnings.append("repeated example markers found. Keep only examples that earn tokens.")

    return CompactnessReport(
        kind=kind,
        chars=chars,
        lines=lines,
        tokens=tokens,
        warnings=tuple(warnings),
    )


def warn_prompt_compactness(slug: str, content: str) -> CompactnessReport:
    """Emit non-blocking warnings for prompt authoring."""
    report = analyze_compactness(content, kind="prompt")
    for warning in report.warnings:
        output_warning(f"prompt {slug}: {warning}")
    return report


def warn_memory_compactness(label: str, content: str) -> CompactnessReport:
    """Emit non-blocking warnings for memory authoring."""
    report = analyze_compactness(content, kind="memory")
    for warning in report.warnings:
        output_warning(f"memory {label}: {warning}")
    return report
