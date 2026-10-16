"""Concurrent pytest runs get their own xdist worker databases."""

from __future__ import annotations

import re

from tests.conftest import _orphaned_worker_databases, _worker_database_name


def test_concurrent_runs_never_share_a_worker_database() -> None:
    first = _worker_database_name("summitflow_test", "gw0", 4100)
    second = _worker_database_name("summitflow_test", "gw0", 4200)
    assert first != second
    assert first == "summitflow_test_r4100_gw0"
    # The end-of-run drop still recognises per-run worker databases.
    assert re.fullmatch(r"[a-z0-9_]+_gw[0-9]+", first)


def test_only_databases_of_exited_runs_are_orphans() -> None:
    names = ["summitflow_test", "summitflow_test_gw0", "summitflow_test_r10_gw0", "summitflow_test_r10_gw1",
             "summitflow_test_r20_gw0", "other_test_r10_gw0", "summitflow_test_r10_gw0_extra"]
    live = {20}
    assert _orphaned_worker_databases(names, "summitflow_test", lambda pid: pid in live) == [
        "summitflow_test_r10_gw0", "summitflow_test_r10_gw1",
    ]
