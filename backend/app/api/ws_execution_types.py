"""WebSocket execution message types and data structures.

Defines the core message types and data structures used for
WebSocket communication in execution streaming.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


class MessageType(StrEnum):
    """WebSocket message types."""

    LOG = "log"
    PROGRESS = "progress"
    MODEL_CHANGE = "model_change"
    CHAT_MESSAGE = "chat_message"
    STOP_SIGNAL = "stop_signal"
    CONNECTED = "connected"
    ERROR = "error"


@dataclass
class Message:
    """A message in the execution stream."""

    type: MessageType
    task_id: str
    data: dict[str, object]
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    sequence: int = 0

    def to_dict(self) -> dict[str, object]:
        """Convert to dictionary for JSON serialization."""
        return {
            "type": self.type.value,
            "task_id": self.task_id,
            "data": self.data,
            "timestamp": self.timestamp.isoformat(),
            "sequence": self.sequence,
        }
