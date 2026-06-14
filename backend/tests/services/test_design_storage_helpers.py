"""Tests for durable Design Ops storage helpers."""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from app.services.mockup_generator import storage_helpers


def test_mockup_base_dir_defaults_to_durable_project_data() -> None:
    """Design Ops storage should not default to host temp space."""
    base_dir = storage_helpers.MOCKUP_BASE_DIR

    assert Path("/tmp").resolve() not in (base_dir, *base_dir.parents)
    assert base_dir.parts[-3:] == ("data", "design-studio", "mockups")


def test_mockup_base_dir_rejects_tmp_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """Operators should get a hard failure before important assets go to /tmp."""
    monkeypatch.setenv("SUMMITFLOW_MOCKUP_BASE_DIR", "/tmp/summitflow/mockups")

    with pytest.raises(RuntimeError, match="Refusing to use /tmp"):
        importlib.reload(storage_helpers)

    monkeypatch.delenv("SUMMITFLOW_MOCKUP_BASE_DIR")
    importlib.reload(storage_helpers)


def test_relative_mockup_base_dir_is_project_relative(monkeypatch: pytest.MonkeyPatch) -> None:
    """Relative overrides should not depend on the service working directory."""
    monkeypatch.setenv("SUMMITFLOW_MOCKUP_BASE_DIR", "data/custom-design-store")
    reloaded = importlib.reload(storage_helpers)

    assert reloaded.MOCKUP_BASE_DIR.parts[-2:] == ("data", "custom-design-store")
    assert Path("/tmp").resolve() not in (reloaded.MOCKUP_BASE_DIR, *reloaded.MOCKUP_BASE_DIR.parents)

    monkeypatch.delenv("SUMMITFLOW_MOCKUP_BASE_DIR")
    importlib.reload(storage_helpers)
