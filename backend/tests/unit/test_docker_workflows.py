from __future__ import annotations

from pathlib import Path

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
    assert any(step.get("uses", "").startswith("astral-sh/setup-uv@") for step in steps)

    pack_step = next(step for step in steps if step.get("name") == "Pack workspace packages")
    assert pack_step["env"]["AGENT_HUB_ROOT"] == "${{ github.workspace }}/agent-hub-repo"


def test_docker_build_workflow_uploads_wheels_and_marks_backend_as_needing_packages() -> None:
    workflow = _load_workflow("docker-build.yml")
    pack_steps = _steps(workflow, "pack-workspace")
    upload_step = next(
        step for step in pack_steps if str(step.get("uses", "")).startswith("actions/upload-artifact@")
    )
    assert ".whl" in upload_step["with"]["path"]

    build_include = workflow["jobs"]["build"]["strategy"]["matrix"]["include"]
    backend_entry = next(entry for entry in build_include if entry["component"] == "backend")
    assert backend_entry["needs-packages"] is True