"""Data models and enums for AI review task."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any


class ReviewVerdict(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    NEEDS_FIX = "NEEDS_FIX"


class RiskLevel(str, Enum):
    """Risk classification for changes."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass
class ReviewResult:
    """Result of the AI review process."""

    verdict: ReviewVerdict
    summary: str
    checks: dict[str, Any] = field(default_factory=dict)
    issues: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    reviewed_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    risk_level: RiskLevel = RiskLevel.LOW

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict.value,
            "summary": self.summary,
            "checks": self.checks,
            "issues": self.issues,
            "suggestions": self.suggestions,
            "reviewed_at": self.reviewed_at,
            "risk_level": self.risk_level.value,
        }
