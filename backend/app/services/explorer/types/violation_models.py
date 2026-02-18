"""Data models for code violation detection."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ViolationType(Enum):
    PARALLEL_IMPLEMENTATION = "parallel_implementation"
    MISSING_INFRASTRUCTURE = "missing_infrastructure"
    DUPLICATE_UTILITY = "duplicate_utility"


@dataclass
class CodeViolation:
    violation_type: ViolationType
    file_path: str
    detail: str
    severity: str = "warning"
    line_start: int | None = None
    line_end: int | None = None
    related_files: list[str] = field(default_factory=list)
