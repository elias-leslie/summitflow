"""`st service rebuild|result|wait`, `st logs`, `st snap|snaps|rollback` and `st vm` call Aico's ops verbs per verb, and fall back on exit 3."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from cli.commands import logs, service, snapshots, vm
from cli.lib import aico_delegate
from cli.output_context import OutputContext

runner = CliRunner()


@pytest.fixture
def aico(monkeypatch):
    """Aico on PATH with every ops verb on; records each call and answers with ``codes``."""
    monkeypatch.setenv("ST_AICO_OPS", "1")
    monkeypatch.setattr(aico_delegate.shutil, "which", lambda name: f"/bin/{name}")
    calls: list[tuple[str, ...]] = []
    codes = [0]
    monkeypatch.setattr(aico_delegate, "run_ops", lambda *argv: calls.append(argv) or codes[0])
    monkeypatch.setattr(snapshots, "get_config", lambda: SimpleNamespace(project_id="demo"))
    return calls, codes


def test_each_verb_has_its_own_switch(monkeypatch):
    monkeypatch.setattr(aico_delegate.shutil, "which", lambda name: f"/bin/{name}")
    monkeypatch.setattr(aico_delegate, "AICO_OPS_VERBS", frozenset({"vm"}))
    monkeypatch.delenv("ST_AICO_OPS")
    assert aico_delegate.ops_enabled("vm") and not aico_delegate.ops_enabled("rebuild")
    monkeypatch.setenv("ST_AICO_OPS", "0")
    assert not aico_delegate.ops_enabled("vm")
    monkeypatch.setenv("ST_AICO_OPS", "1")
    assert aico_delegate.ops_enabled("rebuild")


def test_vm_verbs_pass_to_aico(aico):
    calls, codes = aico
    for argv in (["list"], ["status", "100"], ["stop", "100"], ["snapshot", "100", "pre"]):
        assert runner.invoke(vm.app, argv).exit_code == 0
    assert runner.invoke(vm.app, ["start", "200", "--reason", "lab"]).exit_code == 0
    codes[0] = 1
    assert runner.invoke(vm.app, ["status", "999"]).exit_code == 1
    assert calls[:5] == [
        ("vm", "list"), ("vm", "status", "100"), ("vm", "stop", "100"), ("vm", "snapshot", "100", "pre"),
        ("vm", "start", "200", "--hours", "4.0", "--reason", "lab"),
    ]


def test_snapshots_pass_to_aico_in_compact_mode_only(aico, monkeypatch):
    calls, _ = aico
    monkeypatch.setattr(snapshots, "confirm_gate", lambda *args: None)  # the confirm pass stays SummitFlow's
    compact = OutputContext()
    assert runner.invoke(snapshots.app, ["snap", "pre"], obj=compact).exit_code == 0
    assert runner.invoke(snapshots.app, ["snaps"], obj=compact).exit_code == 0
    assert runner.invoke(snapshots.app, ["rollback", "-1", "--confirm", "x"], obj=compact).exit_code == 0
    monkeypatch.setattr(snapshots, "list_snapshots", lambda *, project_id: [])
    assert runner.invoke(snapshots.app, ["snaps"], obj=OutputContext(compact=False)).exit_code == 0
    assert runner.invoke(snapshots.app, ["snaps", "--usage"], obj=compact).exit_code == 0
    assert calls[:3] == [
        ("snapshots", "take", "pre", "--project", "demo"),
        ("snapshots", "list", "--project", "demo"),
        ("snapshots", "restore", "-1", "--project", "demo"),
    ]
    assert len(calls) == 3  # JSON output and --usage stay SummitFlow's


def test_logs_pass_one_unit_and_fall_back_on_not_handled(aico, monkeypatch):
    calls, codes = aico
    compact = OutputContext()
    assert runner.invoke(logs.app, ["tail", "-s", "tether@default", "-n", "5"], obj=compact).exit_code == 0
    assert calls == [("logs", "tether@default", "-n", "5", "--since", logs.DEFAULT_SINCE)]
    ran: list[str] = []
    monkeypatch.setattr(logs, "_do_tail", lambda ctx, user, system, *rest: ran.append("summitflow"))
    codes[0] = aico_delegate.NOT_HANDLED
    assert runner.invoke(logs.app, ["tail", "-s", "summitflow"], obj=compact).exit_code == 0
    assert runner.invoke(logs.app, ["tail", "-s", "summitflow,redis"], obj=compact).exit_code == 0
    assert ran == ["summitflow", "summitflow"] and len(calls) == 2


def test_rebuild_passes_the_options_aico_deploy_runs(aico):
    calls, codes = aico
    with patch.object(service, "_load", side_effect=AssertionError("SummitFlow's rebuild ran")):
        argv = ["rebuild", "aico", "--detach", "--worker", "tether@default", "--with-ack", "r1", "--sha", "abc"]
        assert runner.invoke(service.app, argv).exit_code == 0
        assert runner.invoke(service.app, ["result", "aico-0c939e20fe37"]).exit_code == 0
        codes[0] = 4
        assert runner.invoke(service.app, ["wait", "aico-0c939e20fe37", "--timeout", "5"]).exit_code == 4
    assert calls == [
        ("deploy", "aico", "--scope", "full", "--worker=tether@default", "--detach", "--with-ack=r1", "--sha=abc"),
        ("deploy", "result", "aico-0c939e20fe37"),
        ("deploy", "wait", "aico-0c939e20fe37", "--timeout", "5.0"),
    ]


def test_rebuild_of_other_projects_and_pinned_mirrors_stays_summitflow(aico):
    calls, codes = aico
    codes[0] = aico_delegate.NOT_HANDLED
    with patch.object(service, "_load", side_effect=RuntimeError("summitflow path")):
        assert isinstance(runner.invoke(service.app, ["rebuild", "summitflow"]).exception, RuntimeError)
        mirror = ["rebuild", "aico", "--source-repo", "/m", "--sha", "abc"]
        assert isinstance(runner.invoke(service.app, mirror).exception, RuntimeError)
    assert calls == [("deploy", "summitflow", "--scope", "full")]
