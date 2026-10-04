"""CLI tests must not escape in-process mocks into installed owner programs."""

from pathlib import Path
from unittest.mock import Mock

import pytest


@pytest.fixture(autouse=True)
def unit_service_preflight(monkeypatch):
    """Lifecycle unit fixtures use an in-process gate rather than the operator API."""
    from cli.commands import service

    gate = Mock()
    monkeypatch.setattr(service, "require_pulse_gate", gate)
    return gate


@pytest.fixture(autouse=True)
def isolated_extension_processes(monkeypatch, tmp_path):
    from cli import extensions

    run_process = extensions._run_process

    def fixture_only(argv, **kwargs):
        executable = Path(argv[0]).resolve()
        if executable.name == "fixture" and executable.is_relative_to(tmp_path.resolve()):
            return run_process(argv, **kwargs)
        pytest.fail("CLI test attempted to launch an installed extension; mock dispatch or use an isolated fixture")

    monkeypatch.setattr(extensions, "_run_process", fixture_only)
