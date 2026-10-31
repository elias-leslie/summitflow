"""Self-heal: units off their live release and pages that fail while /health passes."""

from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from typer.testing import CliRunner

from cli.commands import service
from cli.lib import service_heal, service_ops, service_release

CURRENT, OLD, GONE = "c" * 32, "a" * 32, "d" * 32
TETHER = "tether@default.service"


@pytest.fixture
def live(tmp_path, monkeypatch):
    """Aico's shape: aico-web serves the page from the backend port; Tether is a manual worker."""
    state = tmp_path / "state" / "projects" / "aico"
    releases = state / "releases"
    for build in (CURRENT, OLD):
        (releases / build / "source" / "web").mkdir(parents=True)
    (state / "current").symlink_to(releases / CURRENT)
    monkeypatch.setenv("SUMMITFLOW_SERVICE_STATE_ROOT", str(tmp_path / "state"))
    project = service_ops.ProjectServices(
        project_id="aico", root=tmp_path / "checkout", backend_service="aico-web.service", frontend_service="",
        default_workers=(), optional_workers=(), backend_port=3002, frontend_port=0,
        backend_dir=tmp_path / "checkout" / "web", frontend_dir=tmp_path / "checkout", health_endpoint="/health",
        manual_workers=(TETHER,), page_on_backend=True,
    )
    cwd = {"aico-web.service": releases / CURRENT / "source" / "web", TETHER: releases / OLD / "source"}
    proc = tmp_path / "proc"
    pids = {"aico-web.service": 11, TETHER: 12}

    def place(unit: str, path: Path | str) -> None:
        link = proc / str(pids[unit]) / "cwd"
        link.parent.mkdir(parents=True, exist_ok=True)
        if link.is_symlink():
            link.unlink()
        link.symlink_to(path)

    for unit, path in cwd.items():
        place(unit, path)
    monkeypatch.setattr(service_ops, "_PROC_ROOT", proc)
    monkeypatch.setattr(service_ops, "_service_main_pid", lambda unit: pids.get(unit, 0))
    receipt = {"events": [{"phase": "deployment_scope", "scope": "frontend", "workers": []}]}
    monkeypatch.setattr(service_release, "build_receipt", lambda *_a, **_k: receipt)
    answers = {"/health": 200, "/": 200}
    monkeypatch.setattr(service_heal, "_probe", lambda _port, path: answers[path])
    monkeypatch.setattr(service_ops, "load_project", lambda _p: project)
    return SimpleNamespace(project=project, releases=releases, place=place, answers=answers, receipt=receipt)


def _kinds(problems):
    return [(problem.unit, problem.kind, problem.restartable) for problem in service_heal.find_problems(problems)]


def test_healthy_project_has_no_problems_and_tether_on_its_own_release_is_fine(live):
    assert service_heal.find_problems(live.project) == []


def test_the_aico_outage_is_found_three_ways(live):
    """2026-10-31: a frontend deploy left aico-web on an older release, pruning removed it, / was 404."""
    live.place("aico-web.service", live.releases / OLD / "source" / "web")
    assert _kinds(live.project) == [("aico-web.service", "not_current", True)]
    live.place("aico-web.service", f"{live.releases / GONE}/source/web (deleted)")
    live.answers["/"] = 404
    assert _kinds(live.project) == [("aico-web.service", "release_missing", True),
                                    ("aico-web.service", "page_down", True)]


def test_scoped_deploys_may_leave_other_units_on_an_older_release(live):
    # A frontend deploy of a project with its own frontend unit leaves the backend where it was.
    project = replace(live.project, page_on_backend=False, frontend_service="page.service", frontend_port=3003)
    live.place("aico-web.service", live.releases / OLD / "source" / "web")
    assert service_heal.find_problems(project) == []
    live.receipt["events"][0]["scope"] = "backend"
    assert [problem.kind for problem in service_heal.find_problems(project)] == ["not_current"]


def test_manual_workers_are_reported_never_restarted(live):
    live.place(TETHER, f"{live.releases / GONE}/source (deleted)")
    assert _kinds(live.project) == [(TETHER, "release_missing", False)]


def test_page_rule_needs_a_passing_health_check(live):
    live.answers.update({"/health": 503, "/": 404})
    assert service_heal.find_problems(live.project) == []
    live.answers.update({"/health": 200, "/": 401})
    assert service_heal.find_problems(live.project) == []
    live.answers["/"] = None
    assert _kinds(live.project) == [("aico-web.service", "page_down", True)]


def test_backend_with_unrun_migrations_is_not_restarted(live):
    live.project.backend_dir.mkdir(parents=True)
    (live.project.backend_dir / "alembic.ini").write_text("")
    live.place("aico-web.service", f"{live.releases / GONE}/source/web (deleted)")
    assert _kinds(live.project) == [("aico-web.service", "release_missing", False)]


@contextmanager
def _free_lock(_project):
    yield


def test_heal_restarts_onto_current_records_it_and_holds_back_a_repeat(live, monkeypatch):
    monkeypatch.setattr(service_release, "deployment_lock", _free_lock)
    live.place("aico-web.service", live.releases / OLD / "source" / "web")
    restarted = []

    def restart(project, units, *, reason, problems=()):
        restarted.append(list(units))
        live.place("aico-web.service", live.releases / CURRENT / "source" / "web")
        service_heal.record(project.project_id, {"reason": reason, "units": list(units), "result": "succeeded"})
        return 0

    monkeypatch.setattr(service_heal, "restart_onto_current", restart)
    result = service_heal.heal_project("aico", cooldown_seconds=1800)
    assert result["status"] == "healed" and restarted == [["aico-web.service"]]
    log = (service_release.project_state_dir("aico") / service_heal.RESTART_LOG).read_text().splitlines()
    assert json.loads(log[-1])["reason"] == "self-heal"
    live.place("aico-web.service", live.releases / OLD / "source" / "web")  # broke again right away
    result = service_heal.heal_project("aico", cooldown_seconds=1800)
    assert result["status"] == "failed" and "broke again" in result["detail"]
    assert restarted == [["aico-web.service"]]


def test_heal_reports_a_restart_that_did_not_fix_it(live, monkeypatch):
    monkeypatch.setattr(service_release, "deployment_lock", _free_lock)
    live.answers["/"] = 404
    monkeypatch.setattr(service_heal, "restart_onto_current", Mock(return_value=0))
    result = service_heal.heal_project("aico", cooldown_seconds=0)
    assert result["status"] == "failed" and result["restarted"] == ["aico-web.service"]


def test_heal_skips_a_project_mid_deploy_and_dry_run_changes_nothing(live, monkeypatch):
    @contextmanager
    def busy(_project):
        raise service_release.ReleaseError("Managed deployment already in progress for aico")
        yield

    monkeypatch.setattr(service_release, "deployment_lock", busy)
    assert service_heal.heal_project("aico", cooldown_seconds=0)["status"] == "busy"
    monkeypatch.setattr(service_release, "deployment_lock", _free_lock)
    restart = Mock(return_value=0)
    monkeypatch.setattr(service_heal, "restart_onto_current", restart)
    live.answers["/"] = 404
    result = service_heal.heal_project("aico", cooldown_seconds=0, dry_run=True)
    assert result["status"] == "found" and result["would_restart"] == ["aico-web.service"]
    restart.assert_not_called()


def test_restart_onto_current_refuses_a_unit_file_naming_another_release(live, monkeypatch, tmp_path):
    unit_file = tmp_path / "aico-web.service"
    unit_file.write_text(f"WorkingDirectory={live.releases / OLD}/source/web\n")
    monkeypatch.setattr(service_ops, "_systemctl_value",
                        lambda _unit, key: str(unit_file) if key == "FragmentPath" else "")
    restart = Mock(return_value=0)
    monkeypatch.setattr(service_ops, "restart_service", restart)
    monkeypatch.setattr(service_ops, "verify_health", Mock(return_value=0))
    assert service_heal.restart_onto_current(live.project, ["aico-web.service"], reason="restart") == 1
    restart.assert_not_called()
    unit_file.write_text(f"WorkingDirectory={live.releases / CURRENT}/source/web\n")
    assert service_heal.restart_onto_current(live.project, ["aico-web.service"], reason="restart") == 0
    bound = restart.call_args.kwargs["project"]
    assert bound.root == live.releases / CURRENT / "source"
    assert restart.call_args.kwargs["port"] == 3002


def test_heal_cli_exits_nonzero_only_for_owner_problems(monkeypatch):
    statuses = iter([{"project": "a", "status": "healed", "restarted": ["x.service"], "problems": []},
                     {"project": "b", "status": "busy", "problems": []}])
    monkeypatch.setattr(service_heal, "heal_project", lambda *_a, **_k: next(statuses))
    result = CliRunner().invoke(service.app, ["heal", "a", "b", "--json"])
    assert result.exit_code == 0, result.output
    assert [json.loads(line)["status"] for line in result.output.splitlines()] == ["healed", "busy"]
    monkeypatch.setattr(service_heal, "heal_project", lambda *_a, **_k: {"project": "a", "status": "failed"})
    assert CliRunner().invoke(service.app, ["heal", "a"]).exit_code == 1
