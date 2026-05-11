"""Strict compactness heuristics for prompt and memory authoring.

Thresholds are sourced from Agent Hub's DB-backed compactness policy
(GET /api/compactness/policy). The fetch is cached per process and falls
back to local defaults if Agent Hub is unreachable, so CLI usage never
blocks on the policy lookup.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

import httpx
import typer

from app.services.context_gatherer.token_utils import estimate_tokens

from ..config import get_agent_hub_url
from ..lib.credentials import load_credentials
from ..output import output_error, output_warning


@dataclass(frozen=True)
class _PolicyThresholds:
    memory_max_chars: int = 280
    memory_max_lines: int = 4
    prompt_max_tokens: int = 350
    prompt_max_lines: int = 80
    max_sentence_words: int = 24
    max_avg_sentence_words: int = 16
    avg_sentence_min_words: int = 120
    max_article_ratio_permille: int = 85
    article_ratio_min_words: int = 80

    @property
    def max_article_ratio(self) -> float:
        return self.max_article_ratio_permille / 1000.0


_DEFAULT_POLICY = _PolicyThresholds()
_policy_cache: _PolicyThresholds | None = None


def _fetch_policy() -> _PolicyThresholds:
    """One-shot HTTP fetch with a tight timeout; never raises."""
    try:
        client_id, request_source = load_credentials(default_source="st-compactness")
        headers = {
            "X-Client-Id": client_id,
            "X-Request-Source": request_source,
            "X-Source-Client": "st-cli",
            "X-Tool-Name": "st compactness",
        }
        with httpx.Client(timeout=2.0) as client:
            response = client.get(
                f"{get_agent_hub_url()}/api/compactness/policy",
                headers=headers,
            )
            if response.status_code != 200:
                return _DEFAULT_POLICY
            data = response.json()
            return _PolicyThresholds(
                memory_max_chars=int(data.get("memory_max_chars", _DEFAULT_POLICY.memory_max_chars)),
                memory_max_lines=int(data.get("memory_max_lines", _DEFAULT_POLICY.memory_max_lines)),
                prompt_max_tokens=int(data.get("prompt_max_tokens", _DEFAULT_POLICY.prompt_max_tokens)),
                prompt_max_lines=int(data.get("prompt_max_lines", _DEFAULT_POLICY.prompt_max_lines)),
                max_sentence_words=int(data.get("max_sentence_words", _DEFAULT_POLICY.max_sentence_words)),
                max_avg_sentence_words=int(data.get("max_avg_sentence_words", _DEFAULT_POLICY.max_avg_sentence_words)),
                avg_sentence_min_words=int(data.get("avg_sentence_min_words", _DEFAULT_POLICY.avg_sentence_min_words)),
                max_article_ratio_permille=int(data.get("max_article_ratio_permille", _DEFAULT_POLICY.max_article_ratio_permille)),
                article_ratio_min_words=int(data.get("article_ratio_min_words", _DEFAULT_POLICY.article_ratio_min_words)),
            )
    except Exception:
        return _DEFAULT_POLICY


def _get_policy() -> _PolicyThresholds:
    global _policy_cache
    if _policy_cache is None:
        _policy_cache = _fetch_policy()
    return _policy_cache


def _reset_policy_cache_for_tests() -> None:
    global _policy_cache
    _policy_cache = None

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
_HEDGE_PATTERN = re.compile(
    r"\b(?:maybe|probably|likely|might|could|should|usually|generally|try to)\b",
    re.IGNORECASE,
)
_SOFT_TONE_PATTERN = re.compile(
    r"\b(?:be thorough|be objective|be specific|be precise|be natural|be conversational|be helpful|be friendly|be confident)\b",
    re.IGNORECASE,
)
_OFFER_BACK_PATTERN = re.compile(
    r"\b(?:if you want|would you like|happy to help|happy to|let me know if)\b",
    re.IGNORECASE,
)
_PROSE_CODE_BLOCK_PATTERN = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE_PATTERN = re.compile(r"`[^`]*`")
_PLACEHOLDER_PATTERN = re.compile(r"\{[^{}\n]+\}")
_WORD_PATTERN = re.compile(r"[A-Za-z']+")
_ARTICLE_WORDS = {"a", "an", "the"}


@dataclass(frozen=True)
class CompactnessReport:
    kind: ContentKind
    chars: int
    lines: int
    tokens: int
    errors: tuple[str, ...]
    warnings: tuple[str, ...]


def _line_count(content: str) -> int:
    return content.count("\n") + (1 if content and not content.endswith("\n") else 0)


def _detect_fillers(content: str) -> list[str]:
    hits: list[str] = []
    for label, pattern in _FILLER_PATTERNS:
        if pattern.search(content):
            hits.append(label)
    return hits


def _strip_non_prose(content: str) -> str:
    stripped = _PROSE_CODE_BLOCK_PATTERN.sub(" ", content)
    stripped = _INLINE_CODE_PATTERN.sub(" ", stripped)
    stripped = _PLACEHOLDER_PATTERN.sub(" ", stripped)
    stripped = re.sub(r"(?m)^\s{0,3}#+\s*", "", stripped)
    stripped = re.sub(r"(?m)^\s*[-*]\s+", "", stripped)
    stripped = re.sub(r"(?m)^\s*\d+\.\s+", "", stripped)
    return stripped


def _extract_sentences(content: str) -> list[str]:
    prose = _strip_non_prose(content)
    return [
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?])\s+|\n+", prose)
        if _WORD_PATTERN.search(sentence)
    ]


def _article_ratio(words: list[str]) -> float:
    if not words:
        return 0.0
    article_count = sum(1 for word in words if word in _ARTICLE_WORDS)
    return article_count / len(words)


def analyze_compactness(content: str, *, kind: ContentKind) -> CompactnessReport:
    """Estimate authoring size and flag non-Caveman prose.

    Thresholds come from the DB-backed compactness policy via Agent Hub
    so CLI warnings stay aligned with API saves and the UI gate.
    """
    policy = _get_policy()
    chars = len(content)
    lines = _line_count(content)
    tokens = estimate_tokens(content)
    errors: list[str] = []
    warnings: list[str] = []
    filler_hits = _detect_fillers(content)
    sentences = _extract_sentences(content)
    prose_words = _WORD_PATTERN.findall(_strip_non_prose(content).lower())
    article_ratio = _article_ratio(prose_words)

    if kind == "prompt":
        if tokens > policy.prompt_max_tokens:
            warnings.append(
                f"large prompt ({tokens} tok > {policy.prompt_max_tokens}). "
                "Hot-path prompts pay this every turn."
            )
        if lines > policy.prompt_max_lines:
            warnings.append(
                f"long prompt ({lines} lines > {policy.prompt_max_lines}). "
                "Collapse repeated examples and overlap."
            )
    else:
        if chars > policy.memory_max_chars:
            warnings.append(
                f"long memory ({chars} chars > {policy.memory_max_chars}). "
                "Keep one atomic rule; split if needed."
            )
        if lines > policy.memory_max_lines:
            warnings.append(
                f"multi-line memory ({lines} lines > {policy.memory_max_lines}). "
                "Prefer one short rule body."
            )

    if filler_hits:
        errors.append(f"filler terms found: {', '.join(filler_hits[:4])}")

    if _EXAMPLE_PATTERN.search(content):
        errors.append("example markers found. Strip examples; keep direct rules only.")

    if _HEDGE_PATTERN.search(content):
        errors.append("hedging found. Replace maybe/should/could-style phrasing with direct rules.")

    if _SOFT_TONE_PATTERN.search(content):
        errors.append("soft-tone phrasing found. Replace 'be X' guidance with direct action rules.")

    if _OFFER_BACK_PATTERN.search(content):
        errors.append("offer-back phrasing found. Remove optional follow-up or helper language.")

    if prose_words and len(prose_words) >= policy.article_ratio_min_words and article_ratio > policy.max_article_ratio:
        errors.append(
            f"article-heavy prose ({article_ratio:.1%} > {policy.max_article_ratio:.1%}). "
            "Drop articles and compress sentence shape."
        )

    long_sentences = [
        sentence
        for sentence in sentences
        if len(_WORD_PATTERN.findall(sentence)) > policy.max_sentence_words
    ]
    if long_sentences:
        errors.append(
            f"long prose sentences found (> {policy.max_sentence_words} words). "
            "Split into short direct lines or bullets."
        )

    if sentences:
        average_sentence_words = sum(len(_WORD_PATTERN.findall(s)) for s in sentences) / len(sentences)
        if len(prose_words) >= policy.avg_sentence_min_words and average_sentence_words > policy.max_avg_sentence_words:
            errors.append(
                f"average sentence too long ({average_sentence_words:.1f} words "
                f"> {policy.max_avg_sentence_words}). Compress prose."
            )

    return CompactnessReport(
        kind=kind,
        chars=chars,
        lines=lines,
        tokens=tokens,
        errors=tuple(errors),
        warnings=tuple(warnings),
    )


def warn_prompt_compactness(slug: str, content: str) -> CompactnessReport:
    """Emit non-blocking warnings for prompt authoring."""
    report = analyze_compactness(content, kind="prompt")
    for warning in report.warnings:
        output_warning(f"prompt {slug}: {warning}")
    for error in report.errors:
        output_warning(f"prompt {slug}: {error}")
    return report


def warn_memory_compactness(label: str, content: str) -> CompactnessReport:
    """Emit non-blocking warnings for memory authoring."""
    report = analyze_compactness(content, kind="memory")
    for warning in report.warnings:
        output_warning(f"memory {label}: {warning}")
    for error in report.errors:
        output_warning(f"memory {label}: {error}")
    return report


def enforce_prompt_compactness(slug: str, content: str) -> CompactnessReport:
    """Hard-fail prompt authoring when content regresses out of Caveman form."""
    report = analyze_compactness(content, kind="prompt")
    if report.errors:
        output_error(f"prompt {slug}: strict Caveman gate failed")
        for error in report.errors:
            output_error(f"  - {error}")
        raise typer.Exit(1)
    return report


def enforce_memory_compactness(label: str, content: str) -> CompactnessReport:
    """Hard-fail memory authoring when content regresses out of Caveman form."""
    report = analyze_compactness(content, kind="memory")
    if report.errors:
        output_error(f"memory {label}: strict Caveman gate failed")
        for error in report.errors:
            output_error(f"  - {error}")
        raise typer.Exit(1)
    return report
