"""The shared maintenance-window format; same vectors as OmniNull's window_test.go and Nightshift's test_window.py."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from app.utils.maintenance_window import MaintenanceWindow

NY = ZoneInfo("America/New_York")


def at(h: int, m: int = 0) -> datetime:
    return datetime(2026, 10, 12, h, m, tzinfo=UTC)


@pytest.mark.parametrize(
    ("spec", "h", "m", "expected"),
    [
        ("01:00-05:00Z", 1, 0, True), ("01:00-05:00Z", 4, 59, True), ("01:00-05:00Z", 5, 0, False),
        ("01:00-05:00Z", 0, 59, False), ("22:00-02:00Z", 23, 30, True), ("22:00-02:00Z", 1, 59, True),
        ("22:00-02:00Z", 2, 0, False), ("22:00-02:00Z", 12, 0, False),
        ("01:00-02:00,12:00-12:30Z", 12, 29, True), ("01:00-02:00,12:00-12:30Z", 12, 30, False),
    ],
)
def test_contains_utc(spec: str, h: int, m: int, expected: bool) -> None:
    assert MaintenanceWindow.parse(spec).contains(at(h, m), NY) is expected


def test_machine_time_uses_the_given_clock() -> None:
    w = MaintenanceWindow.parse("11:30-12:30")
    assert w.contains(at(16, 0), NY)  # 12:00 in New York (EDT)
    assert not w.contains(at(12, 0), NY)


@pytest.mark.parametrize(
    "bad",
    ["", "01:00", "1:00-5:00", "25:00-26:00", "01:00-01:00", "01:60-02:00", ",", "01:00-02:00,", "Z",
     "01:00-02:00,03:00-04:00,05:00-06:00,07:00-08:00,09:00-10:00"],
)
def test_parse_rejects(bad: str) -> None:
    with pytest.raises(ValueError):
        MaintenanceWindow.parse(bad)


def test_parse_shape() -> None:
    assert MaintenanceWindow.parse("22:00-02:00,12:00-12:30Z") == MaintenanceWindow(((1320, 120), (720, 750)), True)


def test_latest_end_and_alignment_with_two_ranges() -> None:
    w = MaintenanceWindow.parse("02:00-06:00,13:30-14:15")
    now = datetime(2026, 7, 1, 16, 0, tzinfo=UTC)  # 12:00 New York
    assert w.latest_end(now, NY) == datetime(2026, 7, 1, 10, 0, tzinfo=UTC)
    now = datetime(2026, 7, 1, 19, 0, tzinfo=UTC)  # 15:00 New York
    assert w.latest_end(now, NY) == datetime(2026, 7, 1, 18, 15, tzinfo=UTC)
    target = datetime(2026, 7, 2, 16, 0, tzinfo=UTC)
    assert w.align_start(target, datetime(2026, 7, 1, 16, 0, tzinfo=UTC), NY) == datetime(2026, 7, 2, 6, 0, tzinfo=UTC)
    # Past the early start on that day, the later range's start is next.
    assert w.align_start(target, datetime(2026, 7, 2, 7, 0, tzinfo=UTC), NY) == datetime(2026, 7, 2, 17, 30, tzinfo=UTC)
    assert w.align_start(target, datetime(2026, 7, 2, 18, 0, tzinfo=UTC), NY) == datetime(2026, 7, 3, 6, 0, tzinfo=UTC)
