"""Aico owns publication; the retained transport is CLI-only and fail-closed."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from cli.lib import aico_delegate
from cli.lib.aico_publish import checked_main, deliver, failed_check_names, record_local_check
from cli.main import app

runner = CliRunner()


def test_failed_check_names_ignore_protocol_examples_in_passing_test_names():
    detail = "acceptance_checks_failed; TEST:FAIL:1\nPASSED test_pattern[CODEQL:FAIL:1]\n"
    assert failed_check_names(detail) == ["pytest"]


def test_publish_delegates_without_sf_db_or_services(monkeypatch):
    monkeypatch.setattr(aico_delegate, "publication_enabled", lambda: True)
    with (
        patch.object(aico_delegate, "run_publication", return_value=0) as run,
        patch("app.storage.projects.get_project_root_path", side_effect=AssertionError("DB used")),
    ):
        result = runner.invoke(app, ["vcs", "publish", "--source", "example", "--sha", "abc", "--json"])
    assert result.exit_code == 0, result.output
    run.assert_called_once_with("--source", "example", "--sha", "abc", "--json")


def test_publish_preserves_global_project_override(monkeypatch):
    monkeypatch.setattr(aico_delegate, "publication_enabled", lambda: True)
    with patch.object(aico_delegate, "run_publication", return_value=0) as run:
        result = runner.invoke(app, ["-P", "selected-project", "vcs", "publish"])
    assert result.exit_code == 0, result.output
    run.assert_called_once_with("--source", "selected-project")


def test_nightly_delegates_before_sf_registry_lookup(monkeypatch):
    from app.tasks import nightly_publication

    monkeypatch.setattr(aico_delegate, "publication_enabled", lambda: True)
    with (
        patch.object(aico_delegate, "nightly_publication", return_value={"status": "completed", "projects": []}) as run,
        patch.object(nightly_publication, "_projects", side_effect=AssertionError("DB used")),
    ):
        assert nightly_publication.run_nightly_publication(dry_run=True, project_ids=["example"])["status"] == "completed"
    run.assert_called_once_with(dry_run=True, project_ids=["example"])


def test_publication_switch_is_independent(monkeypatch):
    monkeypatch.setattr(aico_delegate.shutil, "which", lambda _: "/bin/aico")
    monkeypatch.delenv("ST_AICO_PUBLISH", raising=False)
    assert aico_delegate.publication_enabled()
    monkeypatch.setenv("ST_AICO_PUBLISH", "0")
    assert not aico_delegate.publication_enabled()


def test_publication_policy_delegates_without_sf_db(monkeypatch):
    monkeypatch.setattr(aico_delegate, "publication_enabled", lambda: True)
    with (
        patch.object(aico_delegate, "run_publication", return_value=0) as run,
        patch("app.storage.agent_configs.update_agent_config", side_effect=AssertionError("SF DB used")),
    ):
        result = runner.invoke(app, ["vcs", "publication", "--hold", "--reason", "owner hold"])
    assert result.exit_code == 0, result.output
    run.assert_called_once_with("policy", "--hold", "--reason", "owner hold")


def test_nightly_formats_aico_rows_without_actions_or_legacy_row_fields(monkeypatch):
    monkeypatch.setattr(aico_delegate, "publication_enabled", lambda: True)
    rows = {"status": "completed", "projects": [{"project": "example", "state": "ok", "reason": "source_published", "sha": "a" * 40}]}
    with patch.object(aico_delegate, "nightly_publication", return_value=rows):
        result = runner.invoke(app, ["vcs", "nightly", "--run"])
    assert result.exit_code == 0, result.output
    assert "example" in result.output and "source_published" in result.output


def test_transport_refuses_missing_failed_and_wrong_tree_proof(tmp_path: Path):
    import subprocess

    def git(*args):
        return subprocess.check_output(["git", "-C", str(tmp_path), *args], text=True).strip()

    git("init", "-q", "-b", "main")
    git("config", "user.email", "test@example.invalid")
    git("config", "user.name", "Test")
    (tmp_path / "note").write_text("checked")
    git("add", ".")
    git("commit", "-qm", "initial")
    sha = git("rev-parse", "HEAD")
    assert not checked_main(tmp_path, sha)
    assert deliver(tmp_path, sha)["reason"] == "local_check_required"
    record_local_check(tmp_path, sha, passed=False, failed=["types"])
    assert not checked_main(tmp_path, sha)
    record_local_check(tmp_path, sha, passed=True)
    assert checked_main(tmp_path, sha)
    path = tmp_path / ".git/aico-checks/receipts" / f"publish-{sha}.json"
    value = json.loads(path.read_text())
    value["tree"] = "0" * 40
    path.write_text(json.dumps(value))
    assert not checked_main(tmp_path, sha)


def test_legacy_commit_does_not_stamp_a_tree_helped_by_uncommitted_dependencies(tmp_path, monkeypatch):
    import subprocess

    from cli.lib import commit_workflow

    def git(*args):
        return subprocess.check_output(["git", "-C", str(tmp_path), *args], text=True).strip()

    git("init", "-q", "-b", "main")
    git("config", "user.email", "test@example.invalid")
    git("config", "user.name", "Test")
    (tmp_path / "note").write_text("initial")
    (tmp_path / "helper").write_text("deny")
    git("add", ".")
    git("commit", "-qm", "initial")
    (tmp_path / "note").write_text("selected")
    (tmp_path / "helper").write_text("allow")
    monkeypatch.setattr(commit_workflow, "run_checks", lambda *_args, **_kwargs: ((tmp_path / "helper").read_text() == "allow", "gate"))
    monkeypatch.setattr(commit_workflow.coord, "guard", lambda *_args, **_kwargs: None)
    committed = commit_workflow.commit_git_revision(tmp_path, message="selected", paths=["note"])
    assert committed["status"] == "SUCCESS"
    assert git("show", committed["sha"] + ":helper") == "deny"
    assert not checked_main(tmp_path, committed["sha"])


def test_transport_command_never_reads_registry_or_prints_raw_errors(monkeypatch):
    with (
        patch("cli.lib.aico_publish.deliver", side_effect=RuntimeError("private diagnostic")),
        patch("app.storage.projects.get_project_root_path", side_effect=AssertionError("DB used")),
    ):
        result = runner.invoke(app, ["vcs", "deliver", "--root", "/repo", "--sha", "a" * 40])
    assert result.exit_code == 1
    assert json.loads(result.output) == {"publication_complete": False, "reason": "transport_unavailable"}


def test_failed_acceptance_replaces_the_same_commits_prior_publish_pass(tmp_path, monkeypatch):
    import subprocess

    from cli.commands import check as check_command
    from cli.lib.acceptance import AcceptanceError

    def git(*args):
        return subprocess.check_output(["git", "-C", str(tmp_path), *args], text=True).strip()

    git("init", "-q", "-b", "main")
    git("config", "user.email", "test@example.invalid")
    git("config", "user.name", "Test")
    git("commit", "--allow-empty", "-qm", "initial")
    sha = git("rev-parse", "HEAD")
    record_local_check(tmp_path, sha, passed=True)
    monkeypatch.setattr(check_command, "_resolve_repo_root", lambda: tmp_path)
    monkeypatch.setattr(check_command, "_acceptance_materialization", lambda *_: "actual")
    with patch("cli.lib.acceptance_coordinator.accept_source", side_effect=AcceptanceError("acceptance_checks_failed; OSV:FAIL:1")):
        assert check_command._acceptance_mode(["--acceptance"]) == 2
    assert not checked_main(tmp_path, sha)
    proof = json.loads((tmp_path / ".git/aico-checks/receipts" / f"publish-{sha}.json").read_text())
    assert proof["failed"] == ["osv"]


def test_acceptance_pins_head_before_materialization_can_observe_another_commit(tmp_path, monkeypatch):
    import subprocess

    from cli.commands import check as check_command

    def git(*args):
        return subprocess.check_output(["git", "-C", str(tmp_path), *args], text=True).strip()

    git("init", "-q", "-b", "main")
    git("config", "user.email", "test@example.invalid")
    git("config", "user.name", "Test")
    git("commit", "--allow-empty", "-qm", "initial")
    sha = git("rev-parse", "HEAD")
    monkeypatch.setattr(check_command, "_resolve_repo_root", lambda: tmp_path)

    def moved(*_):
        git("commit", "--allow-empty", "-qm", "concurrent commit")
        return "actual"

    monkeypatch.setattr(check_command, "_acceptance_materialization", moved)
    with patch("cli.lib.acceptance_coordinator.accept_source") as accept:
        accept.return_value.to_dict.return_value = {"state": "success", "source_commit": sha}
        assert check_command._acceptance_mode(["--acceptance"]) == 0
    assert accept.call_args.kwargs["sha"] == sha


