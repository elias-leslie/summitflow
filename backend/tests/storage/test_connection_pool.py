"""Short-lived CLI clients must not eagerly reserve shared database slots."""
from unittest.mock import MagicMock

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
