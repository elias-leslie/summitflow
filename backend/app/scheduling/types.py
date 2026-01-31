"""Schedule type definitions for flexible task scheduling.

Based on moltbot's CronSchedule discriminated union pattern.
Supports three schedule kinds:
- at: One-shot execution at specific timestamp
- every: Fixed interval with optional anchor for phase alignment
- cron: Standard cron expressions with optional timezone
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from croniter import croniter


@dataclass(frozen=True)
class OnceSchedule:
    """One-shot schedule - run once at specific time.

    Attributes:
        kind: Discriminator, always "at"
        timestamp: When to run (UTC datetime)
        delete_after_run: Remove schedule entry after execution
    """

    kind: Literal["at"] = "at"
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    delete_after_run: bool = True

    def next_run(self, after: datetime | None = None) -> datetime | None:
        """Get next run time, or None if already passed."""
        ref = after or datetime.now(UTC)
        if self.timestamp > ref:
            return self.timestamp
        return None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for storage/transmission."""
        return {
            "kind": self.kind,
            "timestamp": self.timestamp.isoformat(),
            "delete_after_run": self.delete_after_run,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> OnceSchedule:
        """Deserialize from dict."""
        timestamp_str = str(data["timestamp"])
        delete_after = bool(data.get("delete_after_run", True))
        return cls(
            timestamp=datetime.fromisoformat(timestamp_str),
            delete_after_run=delete_after,
        )


@dataclass(frozen=True)
class EverySchedule:
    """Interval schedule - run every N seconds/minutes/hours.

    Attributes:
        kind: Discriminator, always "every"
        interval_seconds: Interval between runs in seconds
        anchor: Optional anchor timestamp for phase alignment
               (ensures runs at predictable times like 0, 6, 12, 18 UTC)
    """

    kind: Literal["every"] = "every"
    interval_seconds: int = 3600
    anchor: datetime | None = None

    def next_run(self, after: datetime | None = None) -> datetime:
        """Get next run time based on interval and optional anchor."""
        ref = after or datetime.now(UTC)

        if self.anchor is None:
            return ref + timedelta(seconds=self.interval_seconds)

        anchor_ts = self.anchor.timestamp()
        ref_ts = ref.timestamp()
        interval = self.interval_seconds

        periods_since_anchor = (ref_ts - anchor_ts) / interval
        next_period = int(periods_since_anchor) + 1
        next_ts = anchor_ts + (next_period * interval)

        return datetime.fromtimestamp(next_ts, tz=UTC)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for storage/transmission."""
        return {
            "kind": self.kind,
            "interval_seconds": self.interval_seconds,
            "anchor": self.anchor.isoformat() if self.anchor else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EverySchedule:
        """Deserialize from dict."""
        anchor = None
        anchor_str = data.get("anchor")
        if anchor_str:
            anchor = datetime.fromisoformat(str(anchor_str))
        return cls(
            interval_seconds=int(data["interval_seconds"]),
            anchor=anchor,
        )


@dataclass(frozen=True)
class CronSchedule:
    """Cron expression schedule with optional timezone.

    Attributes:
        kind: Discriminator, always "cron"
        expr: Standard 5-field cron expression (minute hour day month weekday)
        tz: IANA timezone name (e.g., "US/Eastern", "Europe/London")
             Defaults to UTC if not specified
    """

    kind: Literal["cron"] = "cron"
    expr: str = "0 * * * *"
    tz: str | None = None

    def next_run(self, after: datetime | None = None) -> datetime:
        """Get next run time based on cron expression."""
        import pytz

        ref = after or datetime.now(UTC)

        if self.tz:
            tz = pytz.timezone(self.tz)
            ref_local = ref.astimezone(tz)
            cron = croniter(self.expr, ref_local)
            next_local: datetime = cron.get_next(datetime)
            return next_local.astimezone(UTC)
        else:
            cron = croniter(self.expr, ref)
            next_utc: datetime = cron.get_next(datetime)
            return next_utc.replace(tzinfo=UTC)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for storage/transmission."""
        return {
            "kind": self.kind,
            "expr": self.expr,
            "tz": self.tz,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CronSchedule:
        """Deserialize from dict."""
        return cls(
            expr=str(data["expr"]),
            tz=str(data["tz"]) if data.get("tz") else None,
        )


TaskSchedule = OnceSchedule | EverySchedule | CronSchedule


def parse_schedule(data: dict[str, Any]) -> TaskSchedule:
    """Parse a schedule dict into the appropriate schedule type."""
    kind = data.get("kind")
    if kind == "at":
        return OnceSchedule.from_dict(data)
    elif kind == "every":
        return EverySchedule.from_dict(data)
    elif kind == "cron":
        return CronSchedule.from_dict(data)
    else:
        raise ValueError(f"Unknown schedule kind: {kind}")


def parse_at_time(time_str: str) -> datetime:
    """Parse a user-provided time string into a datetime.

    Supports:
    - ISO format: "2025-02-01T22:00:00"
    - Date + time: "2025-02-01 22:00"
    - Relative: "in 30m", "in 2h", "in 1d"
    - Time only (assumes today/tomorrow): "22:00", "10:30"

    Returns:
        UTC datetime
    """
    time_str = time_str.strip()

    if time_str.startswith("in "):
        return _parse_relative_time(time_str[3:])

    for fmt in [
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
    ]:
        try:
            dt = datetime.strptime(time_str, fmt)
            return dt.replace(tzinfo=UTC)
        except ValueError:
            continue

    if ":" in time_str and len(time_str) <= 5:
        try:
            hour, minute = map(int, time_str.split(":"))
            now = datetime.now(UTC)
            target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if target <= now:
                target += timedelta(days=1)
            return target
        except ValueError:
            pass

    raise ValueError(f"Cannot parse time string: {time_str}")


def _parse_relative_time(duration_str: str) -> datetime:
    """Parse relative duration like '30m', '2h', '1d'."""
    duration_str = duration_str.strip().lower()
    now = datetime.now(UTC)

    if duration_str.endswith("m"):
        minutes = int(duration_str[:-1])
        return now + timedelta(minutes=minutes)
    elif duration_str.endswith("h"):
        hours = int(duration_str[:-1])
        return now + timedelta(hours=hours)
    elif duration_str.endswith("d"):
        days = int(duration_str[:-1])
        return now + timedelta(days=days)
    else:
        raise ValueError(f"Unknown duration format: {duration_str}")
