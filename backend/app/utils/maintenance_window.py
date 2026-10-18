"""The shared maintenance-window format, the same text OmniNull and Nightshift read.

1 to 4 daily ranges "HH:MM-HH:MM" (24-hour, start inclusive, end exclusive, a range may cross midnight, start and end
differ), joined by commas, in the machine's own clock, or in UTC with a trailing "Z". OmniNull's run-parameter syntax
(hub/pkg/scripts/window.go); keep the parsers agreeing. SummitFlow's machine clock is backup_schedule_timezone.
Local times follow wall-clock time, so daylight saving never shifts a window.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, tzinfo

MAX_RANGES = 4
_RANGE = re.compile(r"([01]\d|2[0-3]):([0-5]\d)-([01]\d|2[0-3]):([0-5]\d)")


@dataclass(frozen=True)
class MaintenanceWindow:
    ranges: tuple[tuple[int, int], ...]  # (start_minute, end_minute) of the day
    utc: bool = False

    @classmethod
    def parse(cls, spec: str) -> MaintenanceWindow:
        utc = spec.endswith("Z")
        parts = (spec[:-1] if utc else spec).split(",")
        if not 1 <= len(parts) <= MAX_RANGES:
            raise ValueError(f"A maintenance window is 1 to {MAX_RANGES} HH:MM-HH:MM ranges (24-hour)")
        ranges = []
        for part in parts:
            m = _RANGE.fullmatch(part)
            if not m:
                raise ValueError("Each maintenance window range is HH:MM-HH:MM (24-hour), start and end different")
            start, end = int(m[1]) * 60 + int(m[2]), int(m[3]) * 60 + int(m[4])
            if start == end:
                raise ValueError("Each maintenance window range is HH:MM-HH:MM (24-hour), start and end different")
            ranges.append((start, end))
        return cls(tuple(ranges), utc)

    def _clock(self, tz: tzinfo) -> tzinfo:
        return UTC if self.utc else tz

    def contains(self, now: datetime, tz: tzinfo) -> bool:
        local = now.astimezone(self._clock(tz))
        n = local.hour * 60 + local.minute
        return any(s <= n < e if s < e else n >= s or n < e for s, e in self.ranges)

    def latest_end(self, now: datetime, tz: tzinfo) -> datetime:
        """The most recent moment a range ended, at or before now (UTC)."""
        clock = self._clock(tz)
        local = now.astimezone(clock)
        ends = []
        for _, end in self.ranges:
            t = local.replace(hour=end // 60, minute=end % 60, second=0, microsecond=0, fold=0)
            if t.astimezone(UTC) > now.astimezone(UTC):
                t -= timedelta(days=1)
            ends.append(t.astimezone(UTC))
        return max(ends)

    def align_start(self, target: datetime, now: datetime, tz: tzinfo) -> datetime:
        """The first range start on target's day after now, else the first start the day after (UTC)."""
        clock = self._clock(tz)
        local = target.astimezone(clock)
        starts = sorted(
            local.replace(hour=s // 60, minute=s % 60, second=0, microsecond=0, fold=0) for s, _ in self.ranges
        )
        later = [t for t in starts if t.astimezone(UTC) > now.astimezone(UTC)]
        return (later[0] if later else starts[0] + timedelta(days=1)).astimezone(UTC)
