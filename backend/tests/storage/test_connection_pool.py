"""Short-lived CLI clients must not eagerly reserve shared database slots."""
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

from app import config
from app.storage import connection


def test_pool_is_lazy_and_bounded(monkeypatch):
    pool = MagicMock(closed=False)
    factory = MagicMock(return_value=pool)
    monkeypatch.setattr(connection, "_pool", None)
    monkeypatch.setattr(connection, "DATABASE_URL", "postgresql://synthetic")
    monkeypatch.setattr(connection, "ConnectionPool", factory)
    assert connection.get_pool() is pool
    assert connection.get_pool() is pool
    factory.assert_called_once_with("postgresql://synthetic", min_size=0, max_size=5, timeout=30.0, max_idle=60.0, open=True)
    connection.close_pool()
    pool.close.assert_called_once()


def test_an_agent_hosts_placeholder_url_is_refused_at_once(monkeypatch):
    """The real pool would retry 127.0.0.1:1 for its whole 30 s timeout."""
    monkeypatch.setattr(connection, "_pool", None)
    monkeypatch.setattr(connection, "DATABASE_URL", config.AGENT_HOST_DATABASE_URL)
    started = time.monotonic()
    with pytest.raises(connection.DatabaseUnavailable, match="only on the workstation"), connection.get_cursor():
        pass
    assert time.monotonic() - started < 1 and connection._pool is None


def test_a_db_backed_command_on_an_agent_host_says_why_in_one_line(monkeypatch):
    import typer

    from cli.main import app

    monkeypatch.setattr(connection, "_pool", None)
    monkeypatch.setattr(connection, "DATABASE_URL", config.AGENT_HOST_DATABASE_URL)

    def needs_db() -> None:
        with connection.get_cursor():
            pass

    probe = typer.Typer()
    probe.command("probe")(needs_db)
    monkeypatch.setattr(app, "registered_groups", [*app.registered_groups, typer.models.TyperInfo(probe, name="dbprobe")])
    result = CliRunner().invoke(app, ["dbprobe", "probe"])
    assert result.exit_code == 2
    assert result.output.strip().startswith("ERROR this needs the SummitFlow database")
    assert "Traceback" not in result.output


def test_the_placeholder_matches_the_agent_host_st_guard():
    guard = Path("/srv/workspaces/projects/agent-hub/scripts/remote-host/host/st")
    if not guard.exists():
        pytest.skip("agent-hub is not checked out here")
    assert f"DATABASE_URL:-{config.AGENT_HOST_DATABASE_URL}}}" in guard.read_text()
