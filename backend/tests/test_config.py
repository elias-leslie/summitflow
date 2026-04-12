"""Tests for base configuration helpers."""

from __future__ import annotations

from app import config


def test_env_or_default_uses_fallback_when_unset(monkeypatch) -> None:
    monkeypatch.delenv("AGENT_HUB_URL", raising=False)

    assert config._env_or_default("AGENT_HUB_URL", "http://localhost:8003") == "http://localhost:8003"


def test_env_or_default_uses_fallback_when_blank(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_HUB_URL", "   ")

    assert config._env_or_default("AGENT_HUB_URL", "http://localhost:8003") == "http://localhost:8003"


def test_env_or_default_strips_and_keeps_explicit_value(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_HUB_URL", "  http://example.test:8003/  ")

    assert config._env_or_default("AGENT_HUB_URL", "http://localhost:8003") == "http://example.test:8003/"
