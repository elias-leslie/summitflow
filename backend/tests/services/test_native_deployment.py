"""Native completion requires immutable source and private server observations."""

from __future__ import annotations

import copy
import hashlib
import json
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest

from app.services import native_deployment as native
from app.services.task_acceptance import completion_gates
from cli.lib import acceptance

RULE = {"rule_version": 1, "prefixes": ["docs/", "release/observer/"], "paths": ["release/policy.json"]}
CHECKS = ["production_binary", "health", "routes"]


def git(root: Path, *arguments: str) -> str:
    return subprocess.run(["git", *arguments], cwd=root, capture_output=True, text=True, check=True).stdout.strip()


def commit(root: Path) -> str:
    git(root, "add", ".")
    git(root, "commit", "-qm", "fixture checkpoint")
    return git(root, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    root.mkdir()
    git(root, "init", "-q", "--initial-branch=main")
    git(root, "config", "user.name", "Fixture")
    git(root, "config", "user.email", "fixture@example.invalid")
    for directory in ("runtime", "docs", "release/observer"):
        (root / directory).mkdir(parents=True)
    (root / "runtime/app.py").write_text("value = 1\n")
    (root / "runtime/embed.txt").write_text("embedded input\n")
    (root / "docs/guide.md").write_text("original docs\n")
    (root / "release/policy.json").write_text(json.dumps(RULE))
    (root / "release/observer/observe").write_text("observer-only input\n")
    commit(root)
    return root


def observation(accepted: str, deployed: str) -> dict:
    return {"accepted_source_commit": accepted, "deployed_source_commit": deployed,
            "runtime_policy_path": "release/policy.json", "runtime_exclusions": copy.deepcopy(RULE)}


def test_source_binding_preserves_build_source_and_excludes_only_pinned_metadata(repo: Path) -> None:
    deployed = git(repo, "rev-parse", "HEAD")
    (repo / "docs/guide.md").write_text("updated docs\n")
    (repo / "release/observer/observe").write_text("updated observer\n")
    (repo / "release/policy.json").write_text(json.dumps(RULE, indent=2))
    accepted = commit(repo)
    binding = native.source_binding(repo, observation(accepted, deployed))
    assert binding["deployed_source_commit"] == deployed
    assert binding["accepted_source_commit"] == accepted
    assert binding["accepted_projection"] == binding["deployed_projection"]
    assert set(binding["changed_paths"]) == {"docs/guide.md", "release/observer/observe", "release/policy.json"}
    assert binding["runtime_policy_sha256"] == hashlib.sha256((repo / "release/policy.json").read_bytes()).hexdigest()


@pytest.mark.parametrize("change", ["runtime", "embed", "new-file", "delete", "mode", "symlink", "gitlink"])
def test_default_inclusion_rejects_runtime_content_modes_links_and_new_inputs(repo: Path, change: str) -> None:
    deployed = git(repo, "rev-parse", "HEAD")
    if change == "runtime":
        (repo / "runtime/app.py").write_text("value = 2\n")
    elif change == "embed":
        (repo / "runtime/embed.txt").write_text("changed embedded input\n")
    elif change == "new-file":
        (repo / "unlisted-runtime.conf").write_text("new default-included input\n")
    elif change == "delete":
        (repo / "runtime/embed.txt").unlink()
    elif change == "mode":
        (repo / "runtime/app.py").chmod(0o755)
    elif change == "symlink":
        (repo / "runtime/current").symlink_to("app.py")
    else:
        git(repo, "update-index", "--add", "--cacheinfo", f"160000,{deployed},runtime/dependency")
    if change == "gitlink":
        git(repo, "commit", "-qm", "fixture gitlink")
        accepted = git(repo, "rev-parse", "HEAD")
    else:
        accepted = commit(repo)
    with pytest.raises(native.NativeDeploymentError, match="runtime inputs differ"):
        native.source_binding(repo, observation(accepted, deployed))


def test_equal_runtime_projection_does_not_replace_ancestor_requirement(repo: Path) -> None:
    base = git(repo, "rev-parse", "HEAD")
    (repo / "docs/guide.md").write_text("branch one\n")
    accepted = commit(repo)
    git(repo, "checkout", "-q", "--detach", base)
    (repo / "docs/guide.md").write_text("branch two\n")
    unrelated_deployed = commit(repo)
    assert native.runtime_projection(repo, accepted, RULE) == native.runtime_projection(repo, unrelated_deployed, RULE)
    with pytest.raises(native.NativeDeploymentError):
        native.source_binding(repo, observation(accepted, unrelated_deployed))


def test_response_cannot_broaden_policy_to_hide_a_runtime_change(repo: Path) -> None:
    deployed = git(repo, "rev-parse", "HEAD")
    (repo / "runtime/app.py").write_text("value = 2\n")
    accepted = commit(repo)
    payload = observation(accepted, deployed)
    payload["runtime_exclusions"]["prefixes"].append("runtime/")
    assert native.runtime_projection(repo, accepted, payload["runtime_exclusions"]) == native.runtime_projection(
        repo, deployed, payload["runtime_exclusions"]
    )
    with pytest.raises(native.NativeDeploymentError, match="rule differs"):
        native.source_binding(repo, payload)


def test_policy_is_read_from_accepted_git_not_dirty_working_tree(repo: Path) -> None:
    sha = git(repo, "rev-parse", "HEAD")
    (repo / "release/policy.json").write_text('{"untrusted":true}')
    assert native.source_binding(repo, observation(sha, sha))["runtime_exclusions"] == RULE


def acceptance_receipt(repo: Path) -> dict:
    return acceptance.accept_revision(repo, sha="HEAD", reuse=False, runner=lambda command, _cwd: subprocess.CompletedProcess(
        command, 0, "isolated fixture gate", "",
    ))


def successful_observer(_root: Path, accepted: dict, request: dict) -> tuple[dict, dict]:
    return ({**{key: value for key, value in request.items() if key not in ("operation", "contract_version")},
             "schema_version": 1, "target_id": "opaque-target",
             "deployed_source_commit": accepted["source_commit"],
             "checks": [{"id": name, "state": "success", "evidence": {"observed": True}} for name in CHECKS],
             "runtime_policy_path": "release/policy.json", "runtime_exclusions": copy.deepcopy(RULE)},
            {"extension_id": "fixture.observer", "observer_source_commit": accepted["source_commit"]})


@pytest.fixture
def issued(repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[dict, dict, Path]:
    monkeypatch.setenv("SUMMITFLOW_SERVICE_STATE_ROOT", str(tmp_path / "private-state"))
    monkeypatch.setattr(native, "_observe", successful_observer)
    accepted = acceptance_receipt(repo)
    task = {"id": "task-fixture", "project_id": "fixture-owner", "status": "running",
            "context": {"completion_requirements": {"deployment": True, "live_checks": CHECKS}},
            "verification_result": {"acceptance": accepted}}
    evidence = native.issue_native_evidence(task, repo, Path(accepted["acceptance_artifact"]))
    task["verification_result"].update(evidence)
    return task, evidence, Path(evidence["deployment"]["artifact"])


def assert_native_blocked(task: dict) -> None:
    assert {gate["gate"] for gate in completion_gates(task)} >= {"deployment", "live_validation"}


def test_server_issued_receipt_is_private_bound_and_reloaded_at_completion(issued: tuple[dict, dict, Path]) -> None:
    task, evidence, path = issued
    record = native.read_native_evidence(evidence["deployment"]["receipt_id"], project=task["project_id"])
    assert record["task_id"] == task["id"]
    assert record["acceptance_id"] == task["verification_result"]["acceptance"]["acceptance_id"]
    assert record["request"]["challenge"] == record["observation"]["challenge"]
    assert path.stat().st_mode & 0o777 == 0o600
    assert path.parent.stat().st_mode & 0o777 == 0o700
    assert completion_gates(task) == []
    path.unlink()
    assert_native_blocked(task)


@pytest.mark.parametrize("change", ["task", "project", "acceptance-id", "accepted-source", "receipt-id", "verified-flag",
                                   "target", "digest", "artifact", "binding", "live-check"])
def test_completion_rejects_copied_receipts_and_descriptor_or_flag_tampering(issued: tuple[dict, dict, Path], change: str) -> None:
    original, _evidence, _path = issued
    task = copy.deepcopy(original)
    verification = task["verification_result"]
    if change == "task":
        task["id"] = "other-task"
    elif change == "project":
        task["project_id"] = "other-owner"
    elif change == "acceptance-id":
        verification["acceptance"]["acceptance_id"] = "other-acceptance"
    elif change == "accepted-source":
        verification["acceptance"]["source_commit"] = "f" * 40
    elif change == "receipt-id":
        verification["deployment"]["receipt_id"] = "f" * 32
    elif change == "verified-flag":
        verification["deployment"]["server_verified"] = True
    elif change == "live-check":
        verification["live_validation"]["checks"][0]["id"] = "forged-check"
    else:
        key = {"target": "target_id", "digest": "sha256", "artifact": "artifact", "binding": "source_binding"}[change]
        verification["deployment"][key] = {} if change == "binding" else "forged"
    assert_native_blocked(task)


@pytest.mark.parametrize("change", ["nonprivate-file", "symlink-file", "nonprivate-store", "symlink-store"])
def test_completion_rejects_receipt_store_privacy_or_symlink_changes(
    issued: tuple[dict, dict, Path], tmp_path: Path, change: str,
) -> None:
    task, _evidence, path = issued
    if change == "nonprivate-file":
        path.chmod(0o644)
    elif change == "symlink-file":
        replacement = tmp_path / "record.json"
        path.rename(replacement)
        path.symlink_to(replacement)
    elif change == "nonprivate-store":
        path.parent.chmod(0o755)
    else:
        replacement = path.parent.with_name("moved-observations")
        path.parent.rename(replacement)
        path.parent.symlink_to(replacement, target_is_directory=True)
    assert_native_blocked(task)


def test_unknown_receipt_and_caller_success_flags_do_not_authorize_completion(issued: tuple[dict, dict, Path]) -> None:
    task, _evidence, path = issued
    path.unlink()
    task["verification_result"]["deployment"]["server_verified"] = True
    task["verification_result"]["live_validation"]["server_verified"] = True
    assert_native_blocked(task)


@pytest.mark.parametrize("change", ["invalid-json", "wrong-identity", "failed-record"])
def test_completion_reloads_record_content_instead_of_trusting_task_snapshot(
    issued: tuple[dict, dict, Path], change: str,
) -> None:
    task, _evidence, path = issued
    if change == "invalid-json":
        path.write_text("not a receipt")
    else:
        record = json.loads(path.read_text())
        record["receipt_id" if change == "wrong-identity" else "state"] = "f" * 32 if change == "wrong-identity" else "failed"
        path.write_text(json.dumps(record))
    assert_native_blocked(task)


@pytest.mark.parametrize("known_source", [True, False])
def test_failed_observations_are_retained_but_never_issue_success(repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, known_source: bool) -> None:
    monkeypatch.setenv("SUMMITFLOW_SERVICE_STATE_ROOT", str(tmp_path / "private-state"))
    accepted = acceptance_receipt(repo)

    def failed_observer(*args):
        response, pin = successful_observer(*args)
        response["checks"][0]["state"] = "failed"
        response["checks"][0]["evidence"] = {"error": "binary_observation_required"}
        if not known_source:
            response["deployed_source_commit"] = None
        return response, pin

    monkeypatch.setattr(native, "_observe", failed_observer)
    with pytest.raises(native.NativeDeploymentError, match="observations failed"):
        native.issue_native_evidence({"id": "task-fixture", "project_id": "fixture-owner", "status": "running"},
                                     repo, Path(accepted["acceptance_artifact"]))
    records = list((tmp_path / "private-state/native-observations").glob("*.json"))
    decoded = [json.loads(path.read_text()) for path in records]
    assert {record["kind"] for record in decoded} == {native.KIND, "native_deployment_attempt.v1"}
    assert len(decoded) == 2
    assert all(record["state"] == "failed" for record in decoded)
    observation = next(record for record in decoded if record["kind"] == native.KIND)
    assert observation["observation"]["checks"][0]["evidence"]["error"] == "binary_observation_required"
    assert observation["source_binding"]["state"] == "not_verified"


@pytest.mark.parametrize("change", ["outside-canonical-store", "not-running", "annotated-scope", "wrong-current-source"])
def test_issuer_rejects_invalid_acceptance_before_observing(repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str) -> None:
    monkeypatch.setenv("SUMMITFLOW_SERVICE_STATE_ROOT", str(tmp_path / "private-state"))
    observer = Mock(side_effect=AssertionError("invalid acceptance must not execute an observer"))
    monkeypatch.setattr(native, "_observe", observer)
    accepted = acceptance_receipt(repo)
    artifact = Path(accepted["acceptance_artifact"])
    task = {"id": "task-fixture", "project_id": "fixture-owner", "status": "running"}
    if change == "outside-canonical-store":
        copied = tmp_path / artifact.name
        copied.write_bytes(artifact.read_bytes())
        artifact = copied
    elif change == "not-running":
        task["status"] = "completed"
    elif change == "annotated-scope":
        receipt = json.loads(artifact.read_text())
        receipt["scope"] = ["runtime/app.py"]
        artifact.write_text(json.dumps(receipt))
    else:
        (repo / "docs/guide.md").write_text("later source\n")
        commit(repo)
    with pytest.raises(ValueError):
        native.issue_native_evidence(task, repo, artifact)
    observer.assert_not_called()


def trusted_registry(tmp_path: Path, *, enabled: bool = True) -> Path:
    directory = tmp_path / "registry"
    (directory / "extensions").mkdir(parents=True)
    metadata = {"id": "fixture.observer", "owner": "fixture-owner", "namespace": "fixture",
                "version": "1.0.0", "st_contract_versions": [1], "summary": "Fixture observer",
                "effects": ["read-local"], "help": {"": "Fixture"}, "usage": [],
                "structured_operations": {"observe_deployment": {"request_contract_version": 1, "response_schema_version": 1}}}
    (directory / "extensions/fixture.json").write_text(json.dumps(metadata))
    path = directory / "tool-registry.json"
    path.write_text(json.dumps({"extensions": [{"id": "fixture.observer", "owner": "fixture-owner", "namespace": "fixture",
        "manifest": "extensions/fixture.json", "executable": "release/observer/observe", "execution_source": "checkout",
        "grant": {"enabled": enabled, "effects": ["read-local"]}}]}))
    return path


def fixture_observer(repo: Path, *, state: str = "success", exit_code: int = 0) -> str:
    script = """#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
request = json.loads(sys.argv[sys.argv.index('--request') + 1])
context = json.loads(os.environ['ST_EXTENSION_CONTEXT'])
assert context['output'] == dict(human=False, compact=False, progress_only=False)
assert context['cwd'] == str(Path.cwd())
assert context['project_id'] == request['project']
assert context['project_root'] == EXPECTED_PROJECT_ROOT
response = {key: value for key, value in request.items() if key not in ('contract_version', 'operation')}
response.update(schema_version=1, target_id='opaque-fixture-target', deployed_source_commit=request['accepted_source_commit'],
                runtime_policy_path='release/policy.json', runtime_exclusions=json.loads(Path('release/policy.json').read_text()),
                checks=[dict(id='fixture-check', state='success', evidence=dict(runtime=Path('runtime/app.py').read_text(), output=context['output']))])
print(json.dumps(response))
"""
    script = script.replace("EXPECTED_PROJECT_ROOT", repr(str(repo)))
    script = script.replace("state='success'", f"state={state!r}") + f"\nsys.exit({exit_code})\n"
    executable = repo / "release/observer/observe"
    executable.write_text(script)
    executable.chmod(0o755)
    return script


def test_observer_executes_registered_accepted_code_and_ignores_dirty_source(repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from cli import extensions

    script = fixture_observer(repo)
    executable = repo / "release/observer/observe"
    sha = commit(repo)
    accepted = {"source_commit": sha, "source_tree": git(repo, "rev-parse", "HEAD^{tree}")}
    executable.write_text("#!/usr/bin/env python3\nraise SystemExit(99)\n")
    (repo / "runtime/app.py").write_text("dirty runtime\n")
    registry = trusted_registry(tmp_path)
    monkeypatch.setattr(extensions, "tool_registry_path", lambda: registry)
    request = {"contract_version": 1, "operation": "observe_deployment", "challenge": "a" * 32,
               "task_id": "task-fixture", "project": "fixture-owner", "acceptance_id": "acceptance-fixture",
               "accepted_source_commit": sha}
    response, pin = native._observe(repo, accepted, request)
    assert response["checks"][0]["evidence"]["runtime"] == "value = 1\n"
    assert response["checks"][0]["evidence"]["output"] == {"human": False, "compact": False, "progress_only": False}
    assert pin["executable_sha256"] == hashlib.sha256(script.encode()).hexdigest()
    assert pin["observer_source_commit"] == sha
    assert pin["observer_source_tree"] == accepted["source_tree"]
    assert pin["extension_id"] == "fixture.observer"


@pytest.mark.parametrize("exit_code", [0, 1])
def test_actual_failed_observer_output_cannot_issue_success_and_nonzero_output_is_rejected(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, exit_code: int,
) -> None:
    from cli import extensions

    fixture_observer(repo, state="failed", exit_code=exit_code)
    commit(repo)
    accepted = acceptance_receipt(repo)
    registry = trusted_registry(tmp_path)
    monkeypatch.setattr(extensions, "tool_registry_path", lambda: registry)
    monkeypatch.setenv("SUMMITFLOW_SERVICE_STATE_ROOT", str(tmp_path / "private-state"))
    expected = "observations failed" if exit_code == 0 else "did not return a valid observation"
    with pytest.raises(native.NativeDeploymentError, match=expected):
        native.issue_native_evidence({"id": "task-fixture", "project_id": "fixture-owner", "status": "running"},
                                     repo, Path(accepted["acceptance_artifact"]))
    records = list((tmp_path / "private-state/native-observations").glob("*.json"))
    decoded = [json.loads(path.read_text()) for path in records]
    attempts = [record for record in decoded if record["kind"] == "native_deployment_attempt.v1"]
    assert len(attempts) == 1
    assert attempts[0]["state"] == "failed"
    with pytest.raises(native.NativeDeploymentError):
        native.read_native_evidence(attempts[0]["receipt_id"])
    if exit_code:
        assert len(decoded) == 1
    else:
        assert len(decoded) == 2
        record = next(record for record in decoded if record["kind"] == native.KIND)
        assert record["state"] == "failed"
        assert record["observation"]["checks"][0]["state"] == "failed"


@pytest.mark.parametrize("failure", ["timeout", "malformed", "projection-mismatch", "unknown-deployed-source"])
def test_ordinary_issuer_failures_retain_private_sanitized_attempts_without_success_descriptors(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str,
) -> None:
    from cli import extensions

    deployed = git(repo, "rev-parse", "HEAD")
    if failure == "projection-mismatch":
        (repo / "runtime/app.py").write_text("value = 2\n")
        commit(repo)
    if failure == "malformed":
        executable = repo / "release/observer/observe"
        executable.write_text("#!/usr/bin/env python3\nprint('private-output-sentinel')\n")
        executable.chmod(0o755)
        commit(repo)
        registry = trusted_registry(tmp_path)
        monkeypatch.setattr(extensions, "tool_registry_path", lambda: registry)
    accepted = acceptance_receipt(repo)
    monkeypatch.setenv("SUMMITFLOW_SERVICE_STATE_ROOT", str(tmp_path / "private-state"))
    if failure == "timeout":
        monkeypatch.setattr(native, "_observe", Mock(side_effect=subprocess.TimeoutExpired(
            ["/private-path-sentinel/observer"], 330, output=b"private-output-sentinel", stderr=b"private-stderr-sentinel",
        )))
    elif failure != "malformed":
        def differing_source(*args):
            response, pin = successful_observer(*args)
            response["deployed_source_commit"] = deployed if failure == "projection-mismatch" else "f" * 40
            return response, pin

        monkeypatch.setattr(native, "_observe", differing_source)
    task: dict = {"id": "task-fixture", "project_id": "fixture-owner", "status": "running"}
    with pytest.raises(native.NativeDeploymentError, match="retained failed attempt") as raised:
        native.issue_native_evidence(task, repo, Path(accepted["acceptance_artifact"]))
    paths = list((tmp_path / "private-state/native-observations").glob("*.json"))
    assert len(paths) == 1
    record = json.loads(paths[0].read_text())
    assert record["kind"] == "native_deployment_attempt.v1"
    assert record["state"] == "failed"
    assert record["task_id"] == task["id"] and record["project"] == task["project_id"]
    assert record["started_at"] <= record["completed_at"]
    assert paths[0].stat().st_mode & 0o777 == 0o600
    assert set(record) == {"kind", "receipt_id", "task_id", "project", "state", "started_at", "completed_at", "failure_type"}
    for sentinel in ("private-output-sentinel", "private-stderr-sentinel", "private-path-sentinel"):
        assert sentinel not in paths[0].read_text() and sentinel not in str(raised.value)
    with pytest.raises(native.NativeDeploymentError):
        native.read_native_evidence(record["receipt_id"])
    task["context"] = {"completion_requirements": {"deployment": True, "live_checks": CHECKS}}
    task["verification_result"] = {"acceptance": accepted, "deployment": {
        "kind": native.KIND, "receipt_id": record["receipt_id"], "state": "succeeded", "server_verified": True,
    }, "live_validation": {"kind": native.KIND, "checks": []}}
    assert_native_blocked(task)


@pytest.mark.parametrize("change", ["denied", "unknown-owner", "unsupported-operation-version"])
def test_observer_rejects_untrusted_or_incompatible_registry_before_execution(repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str) -> None:
    from cli import extensions

    registry = trusted_registry(tmp_path, enabled=change != "denied")
    if change == "unsupported-operation-version":
        path = registry.parent / "extensions/fixture.json"
        manifest = json.loads(path.read_text())
        manifest["structured_operations"]["observe_deployment"]["request_contract_version"] = 2
        path.write_text(json.dumps(manifest))
    monkeypatch.setattr(extensions, "tool_registry_path", lambda: registry)
    launch = Mock(side_effect=AssertionError("untrusted registration must not execute"))
    monkeypatch.setattr(native.safe_subprocess, "run", launch)
    request = {"project": "unknown-owner" if change == "unknown-owner" else "fixture-owner"}
    with pytest.raises(native.NativeDeploymentError):
        native._observe(repo, {"source_commit": "a" * 40}, request)
    launch.assert_not_called()


def caller_asserted_legacy_task() -> dict:
    sha = "a" * 40
    return {"id": "task-fixture", "project_id": "fixture-owner",
            "context": {"completion_requirements": {"deployment": True, "live_checks": CHECKS}},
            "verification_result": {
                "acceptance": {"state": "success", "source_commit": sha},
                "deployment": {"state": "succeeded", "source_commit": sha},
                "live_validation": {"source_commit": sha, "checks": [
                    {"id": name, "state": "success", "artifact": "/fixture/asserted.json", "sha256": "b" * 64}
                    for name in CHECKS
                ]},
            }}


@pytest.mark.parametrize("registration", ["enabled", "disabled", "denied", "incompatible", "collision", "operation-version"])
def test_native_owner_declaration_cannot_downgrade_to_markerless_client_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, registration: str,
) -> None:
    from cli import extensions

    registry = trusted_registry(tmp_path, enabled=registration != "disabled")
    metadata_path = registry.parent / "extensions/fixture.json"
    metadata = json.loads(metadata_path.read_text())
    if registration == "denied":
        metadata["effects"].append("network")
    elif registration == "incompatible":
        metadata["st_contract_versions"] = [2]
        metadata["structured_operations"]["observe_deployment"]["request_contract_version"] = 2
    elif registration == "operation-version":
        metadata["structured_operations"]["observe_deployment"]["response_schema_version"] = 2
    elif registration == "collision":
        payload = json.loads(registry.read_text())
        payload["extensions"].append(copy.deepcopy(payload["extensions"][0]))
        registry.write_text(json.dumps(payload))
    metadata_path.write_text(json.dumps(metadata))
    monkeypatch.setattr(extensions, "tool_registry_path", lambda: registry)
    launch = Mock(side_effect=AssertionError("verifier selection must be passive"))
    monkeypatch.setattr(native.safe_subprocess, "run", launch)
    assert native.deployment_evidence_family("fixture-owner") == "native"
    task = caller_asserted_legacy_task()
    assert not {"kind", "receipt_id", "accepted_source_commit", "source_binding"} & (
        set(task["verification_result"]["deployment"]) | set(task["verification_result"]["live_validation"])
    )
    assert_native_blocked(task)
    launch.assert_not_called()


@pytest.mark.parametrize("malformed", ["global-json", "global-shape", "owner-manifest", "owner-missing-manifest", "invalid-binding"])
def test_unknown_registry_or_owner_metadata_blocks_required_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, malformed: str,
) -> None:
    from cli import extensions

    registry = trusted_registry(tmp_path)
    if malformed == "global-json":
        registry.write_text("not json")
    elif malformed == "global-shape":
        registry.write_text('{"extensions":{}}')
    elif malformed == "owner-manifest":
        (registry.parent / "extensions/fixture.json").write_text("not json")
    elif malformed == "owner-missing-manifest":
        (registry.parent / "extensions/fixture.json").unlink()
    else:
        payload = json.loads(registry.read_text())
        payload["extensions"][0]["executable"] = "../unsafe"
        registry.write_text(json.dumps(payload))
    monkeypatch.setattr(extensions, "tool_registry_path", lambda: registry)
    assert native.deployment_evidence_family("fixture-owner") == "unknown"
    assert_native_blocked(caller_asserted_legacy_task())


@pytest.mark.parametrize("catalog", ["empty", "other-owner", "owner-without-native-operation"])
def test_valid_catalog_without_native_owner_preserves_legacy_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, catalog: str,
) -> None:
    from cli import extensions

    registry = trusted_registry(tmp_path)
    project = "fixture-owner"
    if catalog == "empty":
        registry.write_text('{"extensions":[]}')
    elif catalog == "other-owner":
        project = "legacy-owner"
    else:
        path = registry.parent / "extensions/fixture.json"
        metadata = json.loads(path.read_text())
        metadata["structured_operations"] = {}
        path.write_text(json.dumps(metadata))
    monkeypatch.setattr(extensions, "tool_registry_path", lambda: registry)
    task = caller_asserted_legacy_task()
    task["project_id"] = project
    assert native.deployment_evidence_family(project) == "legacy"
    assert completion_gates(task) == []


def test_real_native_descriptors_missing_kind_fail_exact_server_record_match(
    issued: tuple[dict, dict, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cli import extensions

    registry = trusted_registry(tmp_path)
    monkeypatch.setattr(extensions, "tool_registry_path", lambda: registry)
    task, _evidence, _path = issued
    assert completion_gates(task) == []
    del task["verification_result"]["deployment"]["kind"]
    del task["verification_result"]["live_validation"]["kind"]
    assert_native_blocked(task)


@pytest.mark.parametrize(("requirements", "expected"), [
    ({"deployment": True}, {"deployment"}),
    ({"live_checks": CHECKS}, {"live_validation"}),
])
def test_native_registration_selects_only_the_owner_required_completion_gates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, requirements: dict, expected: set[str],
) -> None:
    from cli import extensions

    registry = trusted_registry(tmp_path)
    monkeypatch.setattr(extensions, "tool_registry_path", lambda: registry)
    task = caller_asserted_legacy_task()
    task["context"]["completion_requirements"] = requirements
    assert {gate["gate"] for gate in completion_gates(task)} == expected


@pytest.fixture
def custom_live_task(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    from cli import extensions

    registry = trusted_registry(tmp_path)
    monkeypatch.setattr(extensions, "tool_registry_path", lambda: registry)
    task = caller_asserted_legacy_task()
    task["context"]["completion_requirements"] = {"deployment": False, "live_checks": ["direct-handoff"]}
    del task["verification_result"]["deployment"]
    task["verification_result"]["live_validation"]["checks"] = [
        {"id": "direct-handoff", "state": "success", "artifact": "/fixture/custom.json", "sha256": "b" * 64},
    ]
    assert native.deployment_evidence_family(task["project_id"]) == "native"
    return task


def test_native_owner_allows_source_bound_custom_checks_without_deployment_evidence(custom_live_task: dict) -> None:
    assert completion_gates(custom_live_task) == []


def test_native_owner_requires_explicit_deployment_waiver_for_custom_checks(custom_live_task: dict) -> None:
    del custom_live_task["context"]["completion_requirements"]["deployment"]
    assert {gate["gate"] for gate in completion_gates(custom_live_task)} == {"live_validation"}


@pytest.mark.parametrize("change", ["source", "acceptance", "failed-check", "missing-check", "artifact", "digest"])
def test_custom_live_checks_require_accepted_source_and_successful_durable_evidence(custom_live_task: dict, change: str) -> None:
    verification = custom_live_task["verification_result"]
    live = verification["live_validation"]
    if change == "source":
        live["source_commit"] = "c" * 40
    elif change == "acceptance":
        verification["acceptance"]["state"] = "failed"
    else:
        key, value = {
            "failed-check": ("state", "failed"), "missing-check": ("id", "another-check"),
            "artifact": ("artifact", ""), "digest": ("sha256", "invalid"),
        }[change]
        live["checks"][0][key] = value
    assert "live_validation" in {gate["gate"] for gate in completion_gates(custom_live_task)}


@pytest.mark.parametrize("descriptor", ["deployment", "live_validation"])
@pytest.mark.parametrize(("key", "value"), [
    ("receipt_id", "f" * 32), ("accepted_source_commit", "a" * 40),
    ("source_binding", {}), ("kind", native.KIND),
    ("kind", "native_deployment_observation.v2"), ("kind", ""),
])
def test_custom_checks_cannot_downgrade_forged_or_mixed_native_evidence(
    custom_live_task: dict, descriptor: str, key: str, value: object,
) -> None:
    custom_live_task["verification_result"].setdefault(descriptor, {})[key] = value
    assert {gate["gate"] for gate in completion_gates(custom_live_task)} == {"live_validation"}


def test_custom_checks_cannot_bypass_required_native_deployment(custom_live_task: dict) -> None:
    custom_live_task["context"]["completion_requirements"]["deployment"] = True
    custom_live_task["verification_result"]["deployment"] = {"state": "succeeded", "source_commit": "a" * 40}
    assert_native_blocked(custom_live_task)


def test_custom_checks_with_markerless_deployment_still_require_native_receipt(custom_live_task: dict) -> None:
    custom_live_task["verification_result"]["deployment"] = {"state": "succeeded", "source_commit": "a" * 40}
    assert {gate["gate"] for gate in completion_gates(custom_live_task)} == {"live_validation"}


def test_native_receipt_is_still_validated_for_live_only_requirement(issued: tuple[dict, dict, Path]) -> None:
    task, _evidence, path = issued
    task["context"]["completion_requirements"]["deployment"] = False
    assert completion_gates(task) == []
    path.unlink()
    assert {gate["gate"] for gate in completion_gates(task)} == {"live_validation"}


@pytest.mark.parametrize("code_only", [False, True])
def test_administrative_and_code_only_tasks_do_not_consult_malformed_deployment_registry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, code_only: bool,
) -> None:
    from cli import extensions

    registry = tmp_path / "malformed-registry.json"
    registry.write_text("not json")
    monkeypatch.setattr(extensions, "tool_registry_path", lambda: registry)
    lookup = Mock(side_effect=AssertionError("no deployment requirement means no deployment lookup"))
    monkeypatch.setattr(native, "deployment_evidence_family", lookup)
    task: dict = {"id": "task-fixture", "project_id": "fixture-owner", "context": {}, "verification_result": {}}
    if code_only:
        task["context"]["files_to_modify"] = ["runtime/app.py"]
        task["verification_result"]["acceptance"] = {"state": "success", "source_commit": "a" * 40}
    assert completion_gates(task) == []
    lookup.assert_not_called()
