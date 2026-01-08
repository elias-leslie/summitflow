"""Base class and types for capture strategies."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, TypedDict

EvidenceType = Literal[
    "screenshot",
    "console_log",
    "api_response",
    "test_result",
    "schema_snapshot",
    "task_execution",
    "performance",
    "accessibility",
]

EntryType = Literal["page", "endpoint", "file", "table", "task"]


class ExplorerEntry(TypedDict, total=False):
    """Explorer entry passed to capture strategies."""

    id: int
    project_id: str
    entry_type: str
    path: str
    name: str
    health_status: str
    metadata: dict[str, Any]


class CaptureConfig(TypedDict, total=False):
    """Configuration for a capture operation."""

    viewports: list[dict[str, Any]]
    timeout_ms: int
    full_page: bool
    wait_for_selector: str | None
    auth_headers: dict[str, str]
    environment: str


@dataclass
class EvidenceResult:
    """Result from a capture operation."""

    success: bool
    evidence_type: str
    file_path: str | None = None
    file_size_bytes: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    console_errors: int = 0
    console_warnings: int = 0
    duration_ms: int = 0

    @classmethod
    def failure(cls, evidence_type: str, error: str) -> EvidenceResult:
        """Create a failure result."""
        return cls(
            success=False,
            evidence_type=evidence_type,
            errors=[error],
        )


class CaptureStrategy(ABC):
    """Abstract base class for evidence capture strategies.

    Each strategy handles a specific entry type and produces
    appropriate evidence types for that entry.
    """

    @abstractmethod
    async def capture(
        self,
        entry: ExplorerEntry,
        config: CaptureConfig,
    ) -> list[EvidenceResult]:
        """Capture evidence for an explorer entry.

        Args:
            entry: The explorer entry to capture evidence for
            config: Capture configuration

        Returns:
            List of EvidenceResult objects (one per evidence type captured)
        """
        ...

    @abstractmethod
    def supports_entry_type(self, entry_type: str) -> bool:
        """Check if this strategy supports a given entry type.

        Args:
            entry_type: The entry type to check (e.g., 'page', 'endpoint')

        Returns:
            True if this strategy can capture evidence for the entry type
        """
        ...

    @abstractmethod
    def get_evidence_types(self) -> list[EvidenceType]:
        """Get the evidence types this strategy can produce.

        Returns:
            List of evidence type identifiers
        """
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable name for this strategy."""
        ...


class CaptureStrategyRegistry(Protocol):
    """Protocol for strategy registry (for dependency injection)."""

    def get_strategy(self, entry_type: str) -> CaptureStrategy | None:
        """Get the appropriate strategy for an entry type."""
        ...

    def register(self, strategy: CaptureStrategy) -> None:
        """Register a capture strategy."""
        ...
