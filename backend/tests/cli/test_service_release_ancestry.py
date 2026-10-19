"""Deploys move forward from the live release unless a rollback is explicit."""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from cli.lib import service_ops, service_release


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, text=True, capture_output=True, check=True).stdout.strip()


@pytest.fixture
def history(tmp_path: Path) -> tuple[Path, list[str]]:
    repo = tmp_path / "checkout"
    repo.mkdir()
    git(repo, "init", "-q", "--initial-branch=main")
    git(repo, "config", "user.name", "Test")
    git(repo, "config", "user.email", "test@example.invalid")
    commits = []
    for number in range(3):
        (repo / "app.py").write_text(f"value = {number}\n")
        git(repo, "add", ".")
        git(repo, "commit", "-qm", f"change {number}")
        commits.append(git(repo, "rev-parse", "HEAD"))
    return repo, commits


def _go_live(state: Path, commit: str, build_id: str = "a" * 32) -> None:
    project_state = state / "projects" / "example"
    (project_state / "releases" / build_id / "source").mkdir(parents=True)
    (project_state / "current").symlink_to(project_state / "releases" / build_id)
    service_release._write_receipt(project_state / "receipts" / f"{build_id}.json",
                                   {"build_id": build_id, "source": {"source_commit": commit}})


def test_first_deploy_and_redeploy_of_the_live_commit_are_allowed(history, tmp_path: Path) -> None:
    repo, commits = history
    state = tmp_path / "state"
    service_release.require_forward_deploy("example", repo, commits[0], state_root=state)
    _go_live(state, commits[1])
    service_release.require_forward_deploy("example", repo, commits[1], state_root=state)


def test_descendant_of_the_live_release_deploys(history, tmp_path: Path) -> None:
    repo, commits = history
    _go_live(tmp_path / "state", commits[0])
    service_release.require_forward_deploy("example", repo, commits[2], state_root=tmp_path / "state")


def test_older_commit_is_refused_unless_rolling_back(history, tmp_path: Path) -> None:
    repo, commits = history
    state = tmp_path / "state"
    _go_live(state, commits[2])
    with pytest.raises(service_release.ReleaseError, match=r"deploy_not_forward.*git revert.*st service rebuild example --rollback"):
        service_release.require_forward_deploy("example", repo, commits[0], state_root=state)
    service_release.require_forward_deploy("example", repo, commits[0], state_root=state, rollback=True)


def test_divergent_and_unknown_live_commits_are_refused(history, tmp_path: Path) -> None:
    repo, commits = history
    git(repo, "checkout", "-q", "-b", "side", commits[0])
    (repo / "side.py").write_text("side = True\n")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "side")
    side = git(repo, "rev-parse", "HEAD")
    state = tmp_path / "state"
    _go_live(state, commits[2])
    with pytest.raises(service_release.ReleaseError, match="does not contain the live release"):
        service_release.require_forward_deploy("example", repo, side, state_root=state)
    other = tmp_path / "other-state"
    _go_live(other, "f" * 40)
    with pytest.raises(service_release.ReleaseError, match="not in this checkout's history"):
        service_release.require_forward_deploy("example", repo, commits[2], state_root=other)


def test_tampered_live_receipt_is_not_trusted_as_a_baseline(history, tmp_path: Path) -> None:
    _repo, commits = history
    state = tmp_path / "state"
    _go_live(state, commits[2])
    receipt = state / "projects" / "example" / "receipts" / f"{'a' * 32}.json"
    receipt.write_text(receipt.read_text().replace(commits[2], commits[0]))
    assert service_release.current_release_commit("example", state_root=state) is None


def test_rebuild_accepts_isolated_projects_and_dirty_checkouts_in_a_private_clone(history, monkeypatch) -> None:
    from cli.lib import acceptance_coordinator

    repo, commits = history
    chosen: list[tuple[str, str]] = []

    def accept_source(root, *, sha, materialization, **_kwargs):
        chosen.append((sha, materialization))
        return SimpleNamespace(receipt={"materialization": materialization})

    monkeypatch.setattr(acceptance_coordinator, "accept_source", accept_source)
    for project_id, dirty, expected in [("example", False, "actual"), ("summitflow", False, "isolated"),
                                        ("example", True, "isolated")]:
        if project_id == "summitflow":
            (repo / ".st-check.toml").write_text('[acceptance]\nbasis = "isolated"\n')
            git(repo, "add", ".st-check.toml")
            git(repo, "commit", "-qm", "opt in")
            commits.append(git(repo, "rev-parse", "HEAD"))
        if dirty:
            (repo / "wip.py").write_text("another agent's work\n")
        project = cast(service_ops.ProjectServices, SimpleNamespace(project_id=project_id, root=repo, git_root=repo))
        assert service_ops._acceptance_candidate(project, None) == {"materialization": expected}
    assert chosen == [(commits[2], "actual"), (commits[3], "isolated"), (commits[3], "isolated")]


def test_detached_rollback_reaches_the_queued_rebuild(monkeypatch, tmp_path: Path) -> None:
    jobs: list[dict] = []
    monkeypatch.setattr(service_ops, "systemctl", lambda *_a: SimpleNamespace(stdout="inactive"))
    monkeypatch.setattr(service_ops, "_write_job", jobs.append)
    monkeypatch.setattr(service_ops, "capture", lambda *_a, **_k: SimpleNamespace(returncode=0, stdout="", stderr=""))
    monkeypatch.setattr(service_ops, "get_repo_root", lambda: tmp_path)
    service_ops.queue_detached("example", False, rollback=True)
    assert jobs[0]["command"] == ["st", "service", "rebuild", "--rollback", "example"]


def test_detached_rebuild_refuses_a_backward_deploy_before_it_queues(history, monkeypatch, tmp_path: Path) -> None:
    from contextlib import nullcontext

    from cli.lib import acceptance

    repo, commits = history
    state = tmp_path / "state"
    _go_live(state, commits[2])
    monkeypatch.setattr(service_release, "service_state_root", lambda: state)
    monkeypatch.setattr(service_ops, "_acceptance_candidate", lambda *_a: {"source_commit": commits[0]})
    monkeypatch.setattr(acceptance, "repo_lock", lambda *_a, **_k: nullcontext())
    monkeypatch.setattr(acceptance, "validate_acceptance_receipt", lambda _root, candidate: dict(candidate))
    project = cast(service_ops.ProjectServices, SimpleNamespace(project_id="example", root=repo, git_root=repo))
    with pytest.raises(service_release.ReleaseError, match="deploy_not_forward"):
        service_ops.resolve_accepted_source(project)


def test_rebuild_rollback_flag_reaches_validation_and_the_queue(monkeypatch) -> None:
    from unittest.mock import Mock

    from typer.testing import CliRunner

    from cli.commands import service
    from cli.lib import coord

    monkeypatch.setattr(coord, "guard", Mock())
    monkeypatch.setattr(service, "_load", lambda _p: Mock(root=Path("/x"), git_root=Path("/x"), runtime_user="", backend_dir=Path("/x/b"),
                                                          frontend_dir=Path("/x/f"), project_id="example",
                                                          workers=lambda **_: ()))
    monkeypatch.setattr(service, "require_pulse_gate", lambda _p: None)
    monkeypatch.setattr(service_ops, "preflight_host_monitor", lambda _s: 0)
    resolve = Mock(return_value={"acceptance_id": "a", "source_commit": "c" * 40})
    queue = Mock(return_value=0)
    monkeypatch.setattr(service_ops, "resolve_accepted_source", resolve)
    monkeypatch.setattr(service_ops, "queue_detached", queue)
    result = CliRunner().invoke(service.app, ["rebuild", "example", "--detach", "--rollback"])
    assert result.exit_code == 0, result.output
    assert resolve.call_args.kwargs["rollback"] is True
    assert queue.call_args.kwargs["rollback"] is True
