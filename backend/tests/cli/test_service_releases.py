"""Stable managed service release materialization and evidence."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from cli.lib import service_release


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=repo, text=True, capture_output=True, check=True
    )
    return result.stdout.strip()


@pytest.fixture
def accepted_repo(tmp_path: Path) -> tuple[Path, service_release.AcceptedSource]:
    repo = tmp_path / "checkout"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "service-tests@example.invalid")
    _git(repo, "config", "user.name", "Service Tests")
    (repo / "backend").mkdir()
    (repo / "frontend").mkdir()
    (repo / "docker" / "workspace-packages").mkdir(parents=True)
    (repo / "backend" / "app.py").write_text("ACCEPTED = True\n")
    (repo / "frontend" / "package.json").write_text('{"name":"accepted"}\n')
    (repo / "docker" / "workspace-packages" / "local.whl").write_bytes(b"wheel")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "accepted source")
    commit = _git(repo, "rev-parse", "HEAD")
    tree = _git(repo, "rev-parse", "HEAD^{tree}")
    return repo, service_release.AcceptedSource(
        acceptance_id="acceptance-1", source_commit=commit, source_tree=tree
    )


def test_materialize_uses_exact_accepted_tree_not_later_checkout_edits(
    accepted_repo: tuple[Path, service_release.AcceptedSource],
    tmp_path: Path,
) -> None:
    repo, source = accepted_repo
    (repo / "backend" / "app.py").write_text("UNACCEPTED = True\n")
    (repo / "frontend" / "package.json").write_text('{"name":"later-edit"}\n')

    release = service_release._materialize_release(
        "example", repo, source, state_root=tmp_path / "state"
    )

    assert (release.source_root / "backend" / "app.py").read_text() == "ACCEPTED = True\n"
    assert json.loads((release.source_root / "frontend" / "package.json").read_text()) == {
        "name": "accepted"
    }
    assert (release.source_root / "docker" / "workspace-packages" / "local.whl").read_bytes() == b"wheel"
    receipt = json.loads(release.receipt_path.read_text())
    assert receipt["source"] == {
        "acceptance_id": "acceptance-1",
        "source_commit": source.source_commit,
        "source_tree": source.source_tree,
        "acceptance_artifact": "",
        "input_fingerprint": "",
        "acceptance_plan_fingerprint": "",
        "scope": [],
        "task_id": "",
        "checks": None,
        "check_count": 0,
        "duration_ms": None,
        "output_bytes": 0,
        "started_at": None,
        "completed_at": None,
        "reused": False,
        "reuse_lookup_ms": None,
    }
    assert receipt["build_id"] == release.build_id
    assert receipt["state"] == "prepared"


def test_materialize_rejects_source_tree_identity_mismatch_before_release(
    accepted_repo: tuple[Path, service_release.AcceptedSource],
    tmp_path: Path,
) -> None:
    repo, source = accepted_repo
    mismatched = service_release.AcceptedSource(
        acceptance_id=source.acceptance_id,
        source_commit=source.source_commit,
        source_tree="0" * 40,
    )

    with pytest.raises(service_release.ReleaseError, match="tree identity"):
        service_release._materialize_release(
            "example", repo, mismatched, state_root=tmp_path / "state"
        )
    assert not list((tmp_path / "state").glob("**/source"))


def test_successful_release_preserves_previous_usable_release(
    accepted_repo: tuple[Path, service_release.AcceptedSource],
    tmp_path: Path,
) -> None:
    repo, first_source = accepted_repo
    state = tmp_path / "state"
    first = service_release._materialize_release("example", repo, first_source, state_root=state)
    service_release.complete_release(first)

    (repo / "backend" / "app.py").write_text("SECOND = True\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "second source")
    second_source = service_release.AcceptedSource(
        acceptance_id="acceptance-2",
        source_commit=_git(repo, "rev-parse", "HEAD"),
        source_tree=_git(repo, "rev-parse", "HEAD^{tree}"),
    )
    second = service_release._materialize_release("example", repo, second_source, state_root=state)
    service_release.complete_release(second)

    project_state = state / "projects" / "example"
    assert (project_state / "current").resolve() == second.release_root
    assert (project_state / "previous").resolve() == first.release_root
    assert first.release_root.is_dir()
    receipt = json.loads(second.receipt_path.read_text())
    assert receipt["state"] == "succeeded"
    assert receipt["previous_usable_release"] == first.build_id


def _release_for_cleanup(state: Path, build_id: str) -> service_release.PreparedRelease:
    release_root = state / "projects" / "example" / "releases" / build_id
    (release_root / "source").mkdir(parents=True)
    return service_release.PreparedRelease(
        project_id="example",
        build_id=build_id,
        source=service_release.AcceptedSource(
            acceptance_id="acceptance-cleanup",
            source_commit="c" * 40,
            source_tree="d" * 40,
        ),
        release_root=release_root,
        source_root=release_root / "source",
        receipt_path=state / "projects" / "example" / "receipts" / f"{build_id}.json",
    )


def test_release_cleanup_preserves_pointers_service_references_receipts_and_logs(
    tmp_path: Path,
) -> None:
    state = tmp_path / "state"
    current = _release_for_cleanup(state, "1" * 32)
    previous = _release_for_cleanup(state, "2" * 32)
    inactive_service = _release_for_cleanup(state, "3" * 32)
    rebuildable = _release_for_cleanup(state, "4" * 32)
    project_state = state / "projects" / "example"
    (project_state / "current").symlink_to(current.release_root)
    (project_state / "previous").symlink_to(previous.release_root)
    receipts = project_state / "receipts"
    receipts.mkdir()
    retained_receipt = receipts / f"{rebuildable.build_id}.json"
    retained_receipt.write_text("durable receipt\n")
    jobs = state / "jobs"
    jobs.mkdir()
    retained_log = jobs / "rollout.log"
    retained_log.write_text("durable log\n")

    removed = service_release.prune_old_releases(
        current, service_references={inactive_service.release_root}
    )

    assert removed == (rebuildable.release_root,)
    assert current.release_root.is_dir()
    assert previous.release_root.is_dir()
    assert inactive_service.release_root.is_dir()
    assert not rebuildable.release_root.exists()
    assert retained_receipt.read_text() == "durable receipt\n"
    assert retained_log.read_text() == "durable log\n"


@pytest.mark.parametrize("references", [None, {Path("/outside/managed/releases")}])
def test_release_cleanup_fails_closed_for_unknown_or_invalid_service_references(
    tmp_path: Path, references: set[Path] | None
) -> None:
    state = tmp_path / "state"
    current = _release_for_cleanup(state, "1" * 32)
    rebuildable = _release_for_cleanup(state, "4" * 32)
    project_state = state / "projects" / "example"
    (project_state / "current").symlink_to(current.release_root)

    assert service_release.prune_old_releases(
        current, service_references=references
    ) == ()
    assert rebuildable.release_root.is_dir()


def test_release_cleanup_fails_closed_when_release_entry_is_a_symlink(
    tmp_path: Path,
) -> None:
    state = tmp_path / "state"
    current = _release_for_cleanup(state, "1" * 32)
    rebuildable = _release_for_cleanup(state, "4" * 32)
    project_state = state / "projects" / "example"
    (project_state / "current").symlink_to(current.release_root)
    outside = tmp_path / "outside"
    outside.mkdir()
    (current.release_root.parent / ("5" * 32)).symlink_to(outside)

    assert service_release.prune_old_releases(
        current, service_references=set()
    ) == ()
    assert rebuildable.release_root.is_dir()
    assert outside.is_dir()


def test_complete_release_rejects_non_symlink_current_pointer(
    accepted_repo: tuple[Path, service_release.AcceptedSource], tmp_path: Path
) -> None:
    repo, source = accepted_repo
    state = tmp_path / "state"
    release = service_release._materialize_release(
        "example", repo, source, state_root=state
    )
    current = state / "projects" / "example" / "current"
    current.write_text("invalid pointer\n")

    with pytest.raises(service_release.ReleaseError, match="not a symlink"):
        service_release.complete_release(release, service_references=set())

    assert current.read_text() == "invalid pointer\n"


def test_failed_release_records_safeguards_without_replacing_current(
    accepted_repo: tuple[Path, service_release.AcceptedSource],
    tmp_path: Path,
) -> None:
    repo, source = accepted_repo
    state = tmp_path / "state"
    current = service_release._materialize_release("example", repo, source, state_root=state)
    service_release.complete_release(current)
    candidate = service_release._materialize_release("example", repo, source, state_root=state)

    service_release.fail_release(
        candidate,
        "health",
        migrations="applied; automatic database rollback is unsupported",
    )

    assert (state / "projects" / "example" / "current").resolve() == current.release_root
    receipt = json.loads(candidate.receipt_path.read_text())
    assert receipt["state"] == "failed"
    assert receipt["failed_phase"] == "health"
    assert receipt["migrations"] == "applied; automatic database rollback is unsupported"


def test_service_state_root_is_configurable(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    configured = tmp_path / "configured"
    monkeypatch.setenv("SUMMITFLOW_SERVICE_STATE_ROOT", str(configured))
    assert service_release.service_state_root() == configured


def test_release_state_cannot_live_inside_development_checkout(
    accepted_repo: tuple[Path, service_release.AcceptedSource],
) -> None:
    repo, source = accepted_repo
    with pytest.raises(service_release.ReleaseError, match="outside the development checkout"):
        service_release._materialize_release(
            "example", repo, source, state_root=repo / ".service-state"
        )


def test_deployment_lock_rejects_concurrent_rollouts(tmp_path: Path) -> None:
    state = tmp_path / "state"
    with (
        service_release.deployment_lock("example", state_root=state),
        pytest.raises(service_release.ReleaseError, match="already in progress"),
        service_release.deployment_lock("example", state_root=state),
    ):
        pass


def test_mark_phase_records_normal_rollout_evidence(
    accepted_repo: tuple[Path, service_release.AcceptedSource],
    tmp_path: Path,
) -> None:
    repo, source = accepted_repo
    release = service_release._materialize_release(
        "example", repo, source, state_root=tmp_path / "state"
    )
    service_release.mark_phase(release, "migrations", status="succeeded")
    service_release.mark_phase(
        release, "restart", status="succeeded", services=["api.service", "worker.service"]
    )
    service_release.mark_phase(release, "health", status="succeeded")
    receipt = json.loads(release.receipt_path.read_text())
    assert [(item["phase"], item["status"]) for item in receipt["events"]] == [
        ("prepared", "succeeded"),
        ("migrations", "succeeded"),
        ("restart", "succeeded"),
        ("health", "succeeded"),
    ]
    assert receipt["events"][2]["services"] == ["api.service", "worker.service"]
    assert os.path.commonpath([str(release.release_root), str(tmp_path / "state")]) == str(
        tmp_path / "state"
    )


def test_closeout_validation_binds_project_checkout_and_source_commit(
    accepted_repo: tuple[Path, service_release.AcceptedSource],
    tmp_path: Path,
) -> None:
    repo, source = accepted_repo
    release = service_release._materialize_release(
        "example", repo, source, state_root=tmp_path / "state"
    )
    for phase in (
        "backend_dependencies",
        "frontend_build",
        "migrations",
        "systemd_units",
        "restart",
        "health",
        "seeds",
    ):
        service_release.mark_phase(release, phase, status="succeeded")
    service_release.complete_release(release)

    evidence = service_release.validate_deployment_receipt(
        release.receipt_path,
        project_root=repo,
        source_commit=source.source_commit,
    )

    assert evidence["state"] == "succeeded"
    assert evidence["artifact"] == str(release.receipt_path)
    assert evidence["source_commit"] == source.source_commit
    assert evidence["build_id"] == release.build_id
    with pytest.raises(service_release.ReleaseError, match="source commit"):
        service_release.validate_deployment_receipt(
            release.receipt_path, source_commit="f" * 40
        )


def test_release_systemd_unit_points_only_at_stable_source(
    accepted_repo: tuple[Path, service_release.AcceptedSource],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cli.lib import service_ops

    repo, source = accepted_repo
    templates = repo / "scripts" / "systemd"
    templates.mkdir(parents=True)
    (templates / "api.service").write_text(
        "[Service]\nWorkingDirectory=__PROJECT_ROOT__/backend\n"
        "Environment=SUMMITFLOW_MOCKUP_BASE_DIR=__SUMMITFLOW_DATA_ROOT__/design-studio/mockups\n"
        "Environment=SUMMITFLOW_HOST_CONFIG_ROOT=__SUMMITFLOW_HOST_CONFIG_ROOT__\n"
        "ExecStart=__SUMMITFLOW_ROOT__/backend/.venv/bin/python -m app\n"
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "add service unit")
    source = service_release.AcceptedSource(
        acceptance_id="acceptance-units",
        source_commit=_git(repo, "rev-parse", "HEAD"),
        source_tree=_git(repo, "rev-parse", "HEAD^{tree}"),
    )
    release = service_release._materialize_release(
        "summitflow", repo, source, state_root=tmp_path / "state"
    )
    services = service_ops.ProjectServices(
        project_id="summitflow",
        root=release.source_root,
        backend_service="api.service",
        frontend_service="",
        default_workers=(),
        optional_workers=(),
        backend_port=0,
        frontend_port=0,
        backend_dir=release.source_root / "backend",
        frontend_dir=release.source_root / "frontend",
        health_endpoint="/health",
        host_config_root=repo,
        durable_data_root=repo / "data",
    )
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setattr(service_ops, "run", lambda *_args, **_kwargs: 0)

    assert service_ops.sync_systemd_units(services) == 0

    unit = (tmp_path / "config" / "systemd" / "user" / "api.service").read_text()
    assert str(release.source_root) in unit
    assert f"WorkingDirectory={repo}" not in unit
    assert f"ExecStart={repo}" not in unit
    assert f"SUMMITFLOW_MOCKUP_BASE_DIR={repo}/data/design-studio/mockups" in unit
    assert f"SUMMITFLOW_HOST_CONFIG_ROOT={repo}" in unit
    assert f"SUMMITFLOW_HOST_CONFIG_ROOT={release.source_root}" not in unit


def test_service_preparation_consumes_canonical_acceptance_receipt(
    accepted_repo: tuple[Path, service_release.AcceptedSource],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cli.lib import acceptance, service_ops

    repo, source = accepted_repo
    descriptor = acceptance.accept_revision(
        repo,
        sha=source.source_commit,
        runner=lambda command, cwd: subprocess.CompletedProcess(command, 0, "accepted", ""),
    )
    reused = acceptance.accept_revision(
        repo,
        sha=source.source_commit,
        runner=lambda *_args: pytest.fail("matching acceptance should be reused"),
    )
    project = service_ops.ProjectServices(
        project_id="example",
        root=repo,
        backend_service="api.service",
        frontend_service="web.service",
        default_workers=("worker.service",),
        optional_workers=(),
        backend_port=8001,
        frontend_port=3001,
        backend_dir=repo / "backend",
        frontend_dir=repo / "frontend",
        health_endpoint="/health",
    )
    monkeypatch.setenv("SUMMITFLOW_SERVICE_STATE_ROOT", str(tmp_path / "service-state"))

    release, deployed = service_ops.prepare_accepted_release(
        project, reused
    )

    assert release.source.acceptance_id == descriptor["acceptance_id"]
    assert release.source.source_commit == source.source_commit
    assert release.source.reused is True
    assert release.source.reuse_lookup_ms is not None
    assert deployed.root == release.source_root
    assert deployed.backend_dir == release.source_root / "backend"
    assert deployed.frontend_dir == release.source_root / "frontend"
    assert deployed.host_config_root == repo
    assert deployed.durable_data_root == repo / "data"
    assert deployed.root != repo
