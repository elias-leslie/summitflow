"""`st web` calls `aico web` and falls back to Agent Hub's executable on exit 3 or when rolled back."""

from __future__ import annotations

from dataclasses import replace

import pytest

from cli import extensions
from cli.extension_contract import ExtensionBinding
from cli.extensions import dispatch_extension, load_extensions
from cli.lib import aico_delegate
from cli.tool_registry import load_tool_registry
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


@pytest.mark.parametrize("owner_root", [None, "missing-executable"])
def test_supported_web_does_not_require_the_old_owner(tmp_path, monkeypatch, owner_root):
    registry = registration(tmp_path, namespace="web", binding_changes={"presentation": "web-details"})
    record = load_extensions(set(), registry_path=registry).records[0]
    calls = []
    monkeypatch.setattr(aico_delegate, "web_command", lambda: "/bin/aico")
    monkeypatch.setattr(extensions, "_run_process", lambda argv, **kwargs: (calls.append(argv) or (0, "{}", "")))
    monkeypatch.setattr("cli.extension_presentation.present_web", lambda *args: None)
    root = None if owner_root is None else str(tmp_path)
    assert dispatch_extension(record, ["search", "query"], context=context(tmp_path), root_resolver=lambda _: root) == 0
    assert calls == [["/bin/aico", "web", "search", "query", "--compact"]]


@pytest.mark.parametrize("status", ["denied", "malformed", "collision", "incompatible"])
def test_aico_delegation_still_requires_a_valid_grant(web, monkeypatch, status):
    record, calls, _, _, tmp_path = web
    monkeypatch.setattr(aico_delegate, "web_command", lambda: pytest.fail("invalid registration reached Aico"))
    assert dispatch_extension(replace(record, status=status), ["search", "query"], context=context(tmp_path)) == 2
    assert calls == []


@pytest.mark.parametrize("aico_code", [None, aico_delegate.NOT_HANDLED])
def test_missing_old_owner_is_reported_only_when_its_execution_is_needed(tmp_path, monkeypatch, aico_code):
    registry = registration(tmp_path, namespace="web", binding_changes={"presentation": "web-details"})
    record = load_extensions(set(), registry_path=registry).records[0]
    calls = []
    monkeypatch.setattr(aico_delegate, "web_command", lambda: "/bin/aico" if aico_code is not None else None)
    monkeypatch.setattr(extensions, "_run_process", lambda argv, **kwargs: (calls.append(argv) or (aico_code, "", "")))
    assert dispatch_extension(record, ["doctor"], context=context(tmp_path), root_resolver=lambda _: None) == 127
    assert len(calls) == (0 if aico_code is None else 1)


def test_real_web_binding_preserves_aico_configuration_without_arbitrary_environment(tmp_path, monkeypatch):
    binding = ExtensionBinding.model_validate(next(row for row in load_tool_registry()["extensions"]
                                                  if row.get("presentation") == "web-details"))
    keys = ["AICO_DATA_DIR", "XDG_STATE_HOME", "AICO_WEB_CACHE_DIR", "AICO_WEB_URL", "AICO_WEB_PORT", "AICO_NODE", "AICO_WEB_DEBUG"]
    for key in keys:
        monkeypatch.setenv(key, f"sentinel-{key}")
    monkeypatch.setenv("UNRELATED_SECRET", "never-inherited")
    monkeypatch.setattr("cli.lib.task_claims.current_caller_identity", lambda: {})
    child = extensions._environment(binding, context(tmp_path))
    assert {key: child.get(key) for key in keys} == {key: f"sentinel-{key}" for key in keys}
    assert "UNRELATED_SECRET" not in child
