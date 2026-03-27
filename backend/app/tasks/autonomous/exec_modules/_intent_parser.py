"""Response parser and data models for the completion gate."""

from __future__ import annotations

from dataclasses import dataclass, field

CONFIDENCE_THRESHOLD = 90


@dataclass
class DoneWhenResult:
    text: str
    status: str  # "MET", "NOT_MET", "PARTIAL"
    evidence: str  # file:line citations


@dataclass
class IntentCheckResult:
    passed: bool
    objective_met: bool
    spirit_violated: bool
    confidence: int = 0
    done_when_results: list[DoneWhenResult] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    summary: str = ""


@dataclass
class _ParseState:
    done_when_results: list[DoneWhenResult] = field(default_factory=list)
    confidence: int = 0
    gaps: list[str] = field(default_factory=list)
    anti_check: str = "CLEAR"
    has_not_met: bool = False


def _parse_confidence(line: str) -> int:
    """Extract integer confidence from a CONFIDENCE: line."""
    try:
        return int(line.split(":", 1)[1].strip().split()[0])
    except (ValueError, IndexError):
        return 0


def _parse_gaps(line: str) -> list[str]:
    """Extract gap list from a GAPS: line; returns [] when NONE."""
    gaps_text = line.split(":", 1)[1].strip()
    if gaps_text.upper() == "NONE":
        return []
    return [g.strip() for g in gaps_text.split(",") if g.strip()]


def _parse_criterion_line(
    line: str, done_when: list[str], state: _ParseState,
) -> None:
    """Parse a CRITERION_N line into state."""
    try:
        parts = line.split(":", 1)
        if len(parts) != 2:
            return
        idx = int(parts[0].replace("CRITERION_", "")) - 1
        if not (0 <= idx < len(done_when)):
            return
        remainder = parts[1].strip()
        if " - " in remainder:
            status_str, evidence = remainder.split(" - ", 1)
        else:
            status_str = remainder
            evidence = ""
        status_str = status_str.strip().upper()
        if status_str not in ("MET", "NOT_MET", "PARTIAL"):
            status_str = "NOT_MET"
        if status_str == "NOT_MET":
            state.has_not_met = True
        state.done_when_results.append(
            DoneWhenResult(text=done_when[idx], status=status_str, evidence=evidence.strip())
        )
    except (ValueError, IndexError):
        pass


def _build_summary(state: _ParseState, passed: bool) -> str:
    """Build a human-readable summary."""
    met = sum(1 for r in state.done_when_results if r.status == "MET")
    total = len(state.done_when_results)
    parts = [f"Confidence: {state.confidence}/100, {met}/{total} criteria met"]
    if state.gaps:
        parts.append(f"Gaps: {', '.join(state.gaps)}")
    if state.anti_check.upper() != "CLEAR":
        parts.append(f"Anti-pattern violation: {state.anti_check}")
    if not passed:
        parts.append("BLOCKED — does not meet completion threshold")
    return ". ".join(parts)


def parse_gate_response(content: str, done_when: list[str]) -> IntentCheckResult:
    """Parse structured completion gate response."""
    state = _ParseState()
    for raw in content.strip().split("\n"):
        line = raw.strip()
        if not line:
            continue
        if line.startswith("CRITERION_"):
            _parse_criterion_line(line, done_when, state)
        elif line.startswith("CONFIDENCE:"):
            state.confidence = _parse_confidence(line)
        elif line.startswith("GAPS:"):
            state.gaps = _parse_gaps(line)
        elif line.startswith("ANTI_CHECK:"):
            state.anti_check = line.split(":", 1)[1].strip()

    spirit_violated = state.anti_check.upper() != "CLEAR"
    passed = (
        state.confidence >= CONFIDENCE_THRESHOLD
        and not state.has_not_met
        and not spirit_violated
    )
    return IntentCheckResult(
        passed=passed,
        objective_met=not state.has_not_met,
        spirit_violated=spirit_violated,
        confidence=state.confidence,
        done_when_results=state.done_when_results,
        gaps=state.gaps,
        summary=_build_summary(state, passed),
    )
