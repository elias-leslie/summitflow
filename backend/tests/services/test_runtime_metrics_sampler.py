"""Runtime metric sampler policy tests."""

from __future__ import annotations

import pytest

from app.services import runtime_metrics_sampler


def test_runtime_metric_defaults_fit_solo_operator_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SUMMITFLOW_RUNTIME_METRICS_INTERVAL_SECONDS", raising=False)
    monkeypatch.delenv("SUMMITFLOW_RUNTIME_METRICS_RETENTION_DAYS", raising=False)

    assert runtime_metrics_sampler._interval_seconds() == 300
    assert runtime_metrics_sampler._retention_days() == 1


def test_runtime_metric_policy_can_be_overridden(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SUMMITFLOW_RUNTIME_METRICS_INTERVAL_SECONDS", "60")
    monkeypatch.setenv("SUMMITFLOW_RUNTIME_METRICS_RETENTION_DAYS", "7")

    assert runtime_metrics_sampler._interval_seconds() == 60
    assert runtime_metrics_sampler._retention_days() == 7


def test_invalid_runtime_metric_policy_uses_bounded_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SUMMITFLOW_RUNTIME_METRICS_INTERVAL_SECONDS", "frequent")
    monkeypatch.setenv("SUMMITFLOW_RUNTIME_METRICS_RETENTION_DAYS", "forever")

    assert runtime_metrics_sampler._interval_seconds() == 300
    assert runtime_metrics_sampler._retention_days() == 1


def test_window_clamp_caps_at_one_day_even_with_longer_retention(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SUMMITFLOW_RUNTIME_METRICS_RETENTION_DAYS", "14")

    assert runtime_metrics_sampler.clamp_window_minutes(43200) == 1440
    assert runtime_metrics_sampler.clamp_window_minutes(360) == 360
    assert runtime_metrics_sampler.clamp_window_minutes(0) == 1
