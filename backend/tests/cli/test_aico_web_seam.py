"""`st web` calls `aico web` and falls back to Agent Hub's executable on exit 3 or when rolled back."""

from __future__ import annotations

import pytest

from cli import extensions
from cli.extensions import dispatch_extension, load_extensions
from cli.lib import aico_delegate
from tests.cli.test_extensions import context, registration


@pytest.fixture
def web(tmp_path, monkeypatch):
    registry = registration(tmp_path, namespace="web", binding_changes={"presentation": "web-details"})
    record = load_extensions(set(), registry_path=registry).records[0]
    monkeypatch.setattr(extensions, "_resolve_executable", lambda *args: ("/owner/web-research", 0, ""))
    calls: list[list[str]] = []
    answers = [(0, "aico out", "")]

    def fake_run(argv, **kwargs):
        calls.append(argv)
        return answers.pop(0) if len(answers) > 1 else answers[0]

    monkeypatch.setattr(extensions, "_run_process", fake_run)
    shown: list[tuple] = []
    monkeypatch.setattr("cli.extension_presentation.present_web", lambda *args: shown.append(args))
    monkeypatch.delenv("ST_AICO_WEB", raising=False)
    monkeypatch.setattr(aico_delegate.shutil, "which", lambda name: f"/bin/{name}")
    return record, calls, answers, shown, tmp_path


def test_web_calls_aico_with_compact_and_presents_its_output(web):
    record, calls, _, shown, tmp_path = web
    assert dispatch_extension(record, ["search", "--query", "x"], context=context(tmp_path)) == 0
    assert calls == [["/bin/aico", "web", "search", "--query", "x", "--compact"]]
    assert shown == [(["search", "--query", "x"], 0, "aico out", "")]


def test_exit_3_runs_the_owner_executable(web):
    record, calls, answers, shown, tmp_path = web
    answers[:] = [(aico_delegate.NOT_HANDLED, "", "not handled"), (0, "owner out", "")]
    assert dispatch_extension(record, ["doctor"], context=context(tmp_path)) == 0
    assert [call[0] for call in calls] == ["/bin/aico", "/owner/web-research"]
    assert shown == [(["doctor"], 0, "owner out", "")]  # the aico attempt is never shown


def test_aico_failures_are_aicos_answer(web):
    record, calls, answers, shown, tmp_path = web
    answers[:] = [(1, "", "fetch failed")]
    assert dispatch_extension(record, ["fetch", "https://example.com"], context=context(tmp_path)) == 1
    assert len(calls) == 1 and shown[0][1] == 1


def test_rollback_switch_and_missing_aico_use_the_owner_executable(web, monkeypatch):
    record, calls, _, _, tmp_path = web
    monkeypatch.setenv("ST_AICO_WEB", "0")
    dispatch_extension(record, ["search", "x"], context=context(tmp_path))
    monkeypatch.delenv("ST_AICO_WEB")
    monkeypatch.setattr(aico_delegate.shutil, "which", lambda name: None)
    dispatch_extension(record, ["search", "x"], context=context(tmp_path))
    assert [call[0] for call in calls] == ["/owner/web-research", "/owner/web-research"]
