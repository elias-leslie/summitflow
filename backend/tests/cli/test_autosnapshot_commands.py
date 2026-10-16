from __future__ import annotations

import pytest
from typer.testing import CliRunner

from cli.commands import autosnapshot
from cli.lib.quick_snapshots import SnapshotError


@pytest.mark.parametrize(("command", "target"), [("prune", "prune_all"), ("sweep", "sweep_periodic")])
def test_concurrent_snapshot_job_is_a_skip_but_other_errors_fail(
    monkeypatch: pytest.MonkeyPatch, command: str, target: str
) -> None:
    def busy(**_: object) -> None:
        raise SnapshotError("Deferred: shared physical snapshot operation in progress")

    monkeypatch.setattr(autosnapshot, target, busy)
    result = CliRunner().invoke(autosnapshot.app, [command])
    assert result.exit_code == 0
    assert f"autosnap: {command} skipped: Deferred" in result.output

    def broken(**_: object) -> None:
        raise SnapshotError("manifest unreadable")

    monkeypatch.setattr(autosnapshot, target, broken)
    assert CliRunner().invoke(autosnapshot.app, [command]).exit_code != 0
