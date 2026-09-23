"""Approved ST service credential lookup never falls back to caller identity."""

from __future__ import annotations

import pytest
import typer
from st_sdk import credentials


def test_internal_secret_uses_approved_local_source(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("INTERNAL_SERVICE_SECRET", raising=False)
    monkeypatch.setattr(
        credentials,
        "_read_env_local",
        lambda: {"INTERNAL_SERVICE_SECRET": "local-test-secret"},
    )

    assert credentials.load_internal_service_secret() == "local-test-secret"


def test_internal_secret_missing_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("INTERNAL_SERVICE_SECRET", raising=False)
    monkeypatch.setattr(credentials, "_read_env_local", lambda: {})

    with pytest.raises(typer.Exit) as exc:
        credentials.load_internal_service_secret()

    assert exc.value.exit_code == 1
