from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tomllib
from pathlib import Path

import pytest
import yaml


def _load_workflow(name: str) -> dict:
    root = Path(__file__).resolve().parents[3]
    return yaml.safe_load((root / ".github" / "workflows" / name).read_text(encoding="utf-8"))


def _steps(workflow: dict, job_name: str) -> list[dict]:
    return workflow["jobs"][job_name]["steps"]


def test_docker_integration_workflow_packs_with_agent_hub_checkout_and_uv() -> None:
    workflow = _load_workflow("docker-integration.yml")
    steps = _steps(workflow, "integration")

    agent_hub_checkout = next(
        step for step in steps if step.get("with", {}).get("repository") == "elias-leslie/agent-hub"
    )
    assert agent_hub_checkout["with"]["path"] == "agent-hub-repo"
    assert "token" not in agent_hub_checkout["with"]
    assert any(step.get("uses", "").startswith("astral-sh/setup-uv@") for step in steps)

    pack_step = next(step for step in steps if step.get("name") == "Pack workspace packages")
    assert pack_step["env"]["AGENT_HUB_ROOT"] == "${{ github.workspace }}/agent-hub-repo"


def test_docker_build_workflow_uploads_only_js_and_retains_checked_in_wheels() -> None:
    workflow = _load_workflow("docker-build.yml")
    pack_steps = _steps(workflow, "pack-workspace")
    agent_hub_checkout = next(
        step for step in pack_steps if step.get("with", {}).get("repository") == "elias-leslie/agent-hub"
    )
    assert agent_hub_checkout["with"]["path"] == "agent-hub-repo"
    assert "token" not in agent_hub_checkout["with"]

    upload_step = next(
        step for step in pack_steps if str(step.get("uses", "")).startswith("actions/upload-artifact@")
    )
    assert ".tgz" in upload_step["with"]["path"]
    assert ".whl" not in upload_step["with"]["path"]

    build_include = workflow["jobs"]["build"]["strategy"]["matrix"]["include"]
    backend_entry = next(entry for entry in build_include if entry["component"] == "backend")
    assert backend_entry["needs-packages"] is True


def test_all_image_publish_jobs_require_exact_source_ci() -> None:
    workflow = _load_workflow("docker-build.yml")
    for name in ("pack-workspace", "build", "agent-browser"):
        needs = workflow["jobs"][name]["needs"]
        assert "source-ci" in ([needs] if isinstance(needs, str) else needs)
    gate = _steps(workflow, "source-ci")[0]
    assert gate["env"]["SOURCE_SHA"] == "${{ github.sha }}"
    assert "--paginate --slurp" in gate["run"]
    assert workflow["jobs"]["source-ci"]["permissions"]["actions"] == "read"


def _run_ci_gate(tmp_path: Path, pages: list, *, api_exit: int = 0):
    commands = tmp_path / "bin"
    commands.mkdir()
    gh = commands / "gh"
    gh.write_text('#!/bin/sh\n[ "$1 $2 $3" = "api --paginate --slurp" ] || exit 98\nprintf "%s" "$FIXTURE_RUNS"\nexit "$FIXTURE_API_EXIT"\n')
    gh.chmod(0o755)
    script = _steps(_load_workflow("docker-build.yml"), "source-ci")[0]["run"]
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=False,
                          env={**os.environ, "PATH": f"{commands}:{os.environ['PATH']}", "SOURCE_SHA": "c" * 40,
                               "GITHUB_REPOSITORY": "fixture/project", "FIXTURE_RUNS": json.dumps(pages),
                               "FIXTURE_API_EXIT": str(api_exit)})


def _run(**changes):
    return {"id": 42, "head_sha": "c" * 40, "event": "push", "run_number": 2,
            "run_attempt": 1, "status": "completed", "conclusion": "success", **changes}


@pytest.mark.parametrize("runs", [[], [_run(head_sha="b" * 40)], [_run(event="pull_request")],
                                  [_run(status="in_progress", conclusion=None)], [_run(conclusion="failure")],
                                  [_run(), _run(run_attempt=2, conclusion="failure")]])
def test_image_publication_rejects_missing_pending_failed_or_different_source(tmp_path, runs):
    assert _run_ci_gate(tmp_path, [{"workflow_runs": runs}]).returncode != 0


def test_image_publication_accepts_only_observed_exact_source_ci_across_pages(tmp_path):
    result = _run_ci_gate(tmp_path, [{"workflow_runs": [_run(head_sha="a" * 40)]}, {"workflow_runs": [_run()]}])
    assert result.returncode == 0, result.stderr
    assert "c" * 40 in result.stdout and "run=42" in result.stdout


def test_image_publication_api_error_never_publishes(tmp_path):
    assert _run_ci_gate(tmp_path, [{"workflow_runs": [_run()]}], api_exit=1).returncode != 0


def test_backend_docker_preserves_lock_paths_and_exact_checked_in_wheel_hashes():
    root = Path(__file__).resolve().parents[3]
    dockerfile = (root / "docker/backend.Dockerfile").read_text()
    assert "WORKDIR /app/backend" in dockerfile
    assert "COPY docker/workspace-packages/ /app/docker/workspace-packages/" in dockerfile
    assert "uv sync --frozen --no-dev --no-editable --no-install-project" in dockerfile
    assert "--no-hashes" not in dockerfile and "uv pip install" not in dockerfile and "*.whl" not in dockerfile
    assert "/app/backend/.venv /app/backend/.venv" in dockerfile
    locked = tomllib.loads((root / "backend/uv.lock").read_text())
    wheels = [package for package in locked["package"] if package["source"].get("path", "").endswith(".whl")]
    assert len(wheels) >= 6
    for package in wheels:
        wheel = root / "backend" / package["source"]["path"]
        assert package["wheels"] == [{"filename": wheel.name, "hash": "sha256:" + hashlib.sha256(wheel.read_bytes()).hexdigest()}]


@pytest.mark.parametrize("tamper", [False, True])
def test_docker_build_rejects_same_name_rebuilt_wheel(tmp_path, tamper):
    root = Path(__file__).resolve().parents[3]
    dockerfile = (root / "docker/backend.Dockerfile").read_text()
    script = dockerfile.split("RUN python3 - <<'PY'\n", 1)[1].split("\nPY\n", 1)[0]
    backend = tmp_path / "backend"
    backend.mkdir()
    wheels = tmp_path / "docker/workspace-packages"
    wheels.mkdir(parents=True)
    wheel = wheels / "fixture-0.1.0-py3-none-any.whl"
    content = b"locked wheel"
    wheel.write_bytes(b"rebuilt wheel" if tamper else content)
    (backend / "uv.lock").write_text('[[package]]\nname = "fixture"\nsource = { path = "../docker/workspace-packages/' + wheel.name + '" }\nwheels = [{ filename = "' + wheel.name + '", hash = "sha256:' + hashlib.sha256(content).hexdigest() + '" }]\n')
    result = subprocess.run(["python3", "-c", script], cwd=backend, capture_output=True, text=True, check=False)
    assert (result.returncode == 0) is not tamper
