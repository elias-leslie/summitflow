"""Focused checks for managed collector commit accounting."""

from __future__ import annotations

import importlib.util
import io
import json
import unittest
from pathlib import Path
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location(
    "profile_managed", Path(__file__).with_name("profile-managed.py")
)
assert SPEC is not None and SPEC.loader is not None
profile = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(profile)


class FakeChannel:
    def __init__(self, status: dict[str, object]):
        self.status = status

    def __enter__(self) -> FakeChannel:
        return self

    def __exit__(self, *_: object) -> None:
        pass

    def settimeout(self, _: float) -> None:
        pass

    def connect(self, _: str) -> None:
        pass

    def sendall(self, _: bytes) -> None:
        pass

    def makefile(self, _: str) -> io.BytesIO:
        return io.BytesIO(json.dumps(self.status).encode() + b"\n")


def row(at: float, count: int, last_ns: int) -> dict[str, float | int]:
    return {
        "at": at,
        "cpu_usec": 0,
        "memory_bytes": 2**20,
        "io_read_bytes": 0,
        "io_write_bytes": 0,
        "store_bytes": 0,
        "commit_count": count,
        "commit_last_ns": last_ns,
    }


class CommitAccountingTests(unittest.TestCase):
    def test_status_uses_monotonic_total_after_window_fills(self) -> None:
        status = {
            "ok": True,
            "sample_commit_count": 256,
            "sample_commit_total": 260,
            "sample_commit_last_ns": 12_000_000,
        }
        with patch.object(profile.socket, "socket", return_value=FakeChannel(status)):
            self.assertEqual(profile.collector_latency(Path("/unused")), (260, 12_000_000))

    def test_old_status_fails_instead_of_silently_reporting_no_commits(self) -> None:
        status = {"ok": True, "sample_commit_count": 256, "sample_commit_last_ns": 12_000_000}
        with patch.object(profile.socket, "socket", return_value=FakeChannel(status)):
            with self.assertRaisesRegex(RuntimeError, "sample_commit_total"):
                profile.collector_latency(Path("/unused"))

    def test_summary_counts_total_delta_and_latency_observations(self) -> None:
        rows = [row(0, 255, 0), row(1, 256, 1_000_000), row(2, 257, 2_000_000),
                row(3, 260, 3_000_000)]
        summary = profile.summarize(rows)
        self.assertEqual(summary["observed_sample_commits"], 5)
        self.assertEqual(summary["sample_plus_commit_latency_observations"], 3)

    def test_summary_rejects_collector_restart(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "reset"):
            profile.summarize([row(0, 260, 1_000_000), row(1, 1, 2_000_000)])


if __name__ == "__main__":
    unittest.main()
