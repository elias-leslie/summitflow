"""CLI tests must not escape in-process mocks into installed owner programs."""

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def unit_service_preflight(monkeypatch):
    """Lifecycle unit fixtures never wait on the operator API."""
    from cli.commands import service

    monkeypatch.setattr(service, "wait_for_summitflow_api", lambda: True)


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


@pytest.fixture(autouse=True)
def no_ambient_agent_identity(monkeypatch):
    """The agent running the suite must not leak its own session identity into CLI cases."""
    for key in ("ST_BROWSER_OWNER", "ST_AGENT_ID", "CODEX_THREAD_ID", "CLAUDE_CODE_SESSION_ID",
                "ST_SESSION_ID", "AICO_SESSION_ID", "ST_BROWSER_SHARED_PROFILE"):
        monkeypatch.delenv(key, raising=False)
