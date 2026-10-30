"""Tests for base configuration helpers."""

from __future__ import annotations

from app import local_endpoints


def test_env_or_default_uses_fallback_when_unset(monkeypatch) -> None:
    monkeypatch.delenv("AGENT_HUB_URL", raising=False)

    assert local_endpoints.env_or_default("AGENT_HUB_URL", "http://localhost:8003") == "http://localhost:8003"


def test_env_or_default_uses_fallback_when_blank(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_HUB_URL", "   ")

    assert local_endpoints.env_or_default("AGENT_HUB_URL", "http://localhost:8003") == "http://localhost:8003"


def test_env_or_default_strips_and_keeps_explicit_value(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_HUB_URL", "  http://example.test:8003/  ")

    assert local_endpoints.env_or_default("AGENT_HUB_URL", "http://localhost:8003") == "http://example.test:8003/"


def test_st_start_defers_settings_and_database_driver() -> None:
    """Every st start imports cli.main; validated Settings and psycopg load only for commands that use them."""
    import os
    import subprocess
    import sys
    from pathlib import Path

    backend = Path(__file__).resolve().parents[1]
    probe = (
        "import sys, cli.main, app.local_endpoints as e; assert e.DEFAULT_API_BASE;"
        "print(sorted(m for m in ('app.config', 'pydantic_settings', 'psycopg') if m in sys.modules))"
    )
    result = subprocess.run([sys.executable, "-c", probe], text=True, capture_output=True, check=True, timeout=30,
                            cwd=backend, env={**os.environ, "PYTHONPATH": str(backend)})
    assert result.stdout.strip() == "[]"
