"""Private runtime selection and qualification boundaries; no registry traffic."""

import hashlib
import importlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts/lib"))
update = importlib.import_module("codex_managed_update")
capture = importlib.import_module("codex_managed_capture")
outboxes = importlib.import_module("codex_managed_outbox")


@pytest.fixture
def outbox(tmp_path):
    return outboxes.ManagedOutbox(tmp_path / "private/outbox.sqlite", max_bytes=100_000, retention_seconds=0)


def vendor(tmp_path, name):
    root = tmp_path / name
    (root / "bin").mkdir(parents=True)
    (root / "codex-resources").mkdir()
    (root / "codex-package.json").write_text('{}')
    (root / "codex-resources/helper").write_text("original resource")
    binary = root / "bin/codex"
    binary.write_text("#!/bin/sh\nexit 0\n")
    binary.chmod(0o700)
    return binary


def test_pin_covers_resources_and_existing_tree_integrity(outbox, tmp_path):
    binary = vendor(tmp_path, "vendor")
    first = update.pin_runtime(outbox, str(binary))
    assert update.pin_runtime(outbox, str(binary)) == first
    (binary.parent.parent / "codex-resources/helper").write_text("new resource")
    second = update.pin_runtime(outbox, str(binary))
    assert first != second and Path(first).read_bytes() == Path(second).read_bytes()
    assert (Path(first).parent.parent / "codex-resources/helper").read_text() == "original resource"
    (Path(second).parent.parent / "codex-resources/helper").write_text("tampered")
    with pytest.raises(ValueError, match="changed"):
        update.pin_runtime(outbox, str(binary))


def test_pin_rejects_resources_escaping_known_vendor(outbox, tmp_path):
    binary = vendor(tmp_path, "vendor")
    (tmp_path / "outside").write_text("outside scope")
    (binary.parent.parent / "codex-resources/link").symlink_to(tmp_path / "outside")
    with pytest.raises(ValueError, match="escapes_vendor"):
        update.pin_runtime(outbox, str(binary))


def test_promotion_requires_qualification_and_preserves_running_old_runtime(outbox, tmp_path, monkeypatch):
    old = update.pin_runtime(outbox, str(vendor(tmp_path, "old")))
    candidate_source = vendor(tmp_path, "new")
    (candidate_source.parent.parent / "codex-resources/helper").write_text("new")
    candidate = update.pin_runtime(outbox, str(candidate_source))
    def record(path, version):
        return {"binary": path, "version": version, "binary_sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest(), "runtime_sha256": update.runtime_digest(Path(path))}
    state = {"active": record(old, "1.0.0"), "candidate": record(candidate, "1.0.1"), "candidate_qualified": False}
    outbox.metadata("update", state)
    outbox.metadata("running_runtime", {"binary": old})
    monkeypatch.setattr(capture, "conformance", lambda *_args, **_kwargs: ("codex-cli 1.0.1", "fingerprint", {}))
    with pytest.raises(ValueError):
        update.update_action(outbox, "promote-update")
    assert update.selected_binary(outbox) == old
    state["candidate_qualified"] = True
    outbox.metadata("update", state)
    update.update_action(outbox, "promote-update")
    assert update.selected_binary(outbox) == candidate and Path(old).exists()
    update.update_action(outbox, "promote-update")
    assert outbox.metadata("update")["previous"]["binary"] == old
    assert "promote-update" not in update.update_actions(outbox)
    update.update_action(outbox, "rollback-update")
    assert update.selected_binary(outbox) == old and Path(candidate).exists()
    update.update_action(outbox, "rollback-update")
    assert update.selected_binary(outbox) == old
    assert outbox.metadata("running_runtime")["binary"] == old


def test_update_check_does_not_install_and_uses_only_canonical_registry(outbox, monkeypatch):
    commands = []
    monkeypatch.setattr(update.subprocess, "run", lambda command, **_kw: (commands.append(command) or SimpleNamespace(stdout='"0.159.4"')))
    update.update_action(outbox, "check-update")
    assert commands == [["npm", "view", "@openai/codex", "version", "--json", "--registry", update.REGISTRY]]
    assert update.update_status(outbox)["latest_version"] == "0.159.4"
    assert not outbox.metadata("update").get("candidate")


def test_untrusted_version_never_becomes_an_install_argument(outbox, monkeypatch):
    outbox.metadata("update", {"latest_version": "--prefix=/unrelated"})
    monkeypatch.setattr(update.subprocess, "run", lambda *_a, **_k: pytest.fail("Must not execute invalid version"))
    with pytest.raises(ValueError):
        update.update_action(outbox, "stage-update")
    assert update.update_status(outbox)["state"] == "failed"


def test_cleanup_preserves_active_candidate_rollback_and_running_references(outbox, tmp_path):
    paths = []
    for number in range(5):
        binary = vendor(tmp_path, str(number))
        (binary.parent.parent / "codex-resources/helper").write_text(str(number))
        paths.append(update.pin_runtime(outbox, str(binary)))
    outbox.metadata("running_runtime", {"binary": paths[3]})
    update.reclaim_runtimes(outbox, {"active": {"binary": paths[0]}, "candidate": {"binary": paths[1]}, "previous": {"binary": paths[2]}})
    assert all(Path(path).exists() for path in paths[:4])
    assert not Path(paths[4]).exists()


def test_runtime_lease_protects_active_resources_without_sqlite_marker(outbox, tmp_path):
    pinned = update.pin_runtime(outbox, str(vendor(tmp_path, "vendor")))
    with update.runtime_lease(pinned):
        update.reclaim_runtimes(outbox, {})
        assert Path(pinned).exists()
    update.reclaim_runtimes(outbox, {})
    assert not Path(pinned).exists()


def test_conformance_cache_is_binary_specific_and_unknown_alias_needs_authority(outbox, tmp_path, monkeypatch):
    import types

    binary = vendor(tmp_path, "vendor")
    schemas = {"ServerRequest": {}, "ServerNotification": {}}
    fingerprint = hashlib.sha256(json.dumps(schemas, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    protocol = types.ModuleType("agent_hub.codex_protocol")
    monkeypatch.setattr(protocol, "SUPPORTED_VERSIONS", ("codex-cli 1.0.0",), raising=False)
    def assets(provider_version):
        if provider_version != "codex-cli 1.0.0":
            raise ValueError("unknown")
        return schemas
    monkeypatch.setattr(protocol, "schemas", assets, raising=False)
    monkeypatch.setattr(protocol, "fingerprint", lambda provider_version: (assets(provider_version) and fingerprint), raising=False)
    monkeypatch.setitem(sys.modules, protocol.__name__, protocol)
    version = "codex-cli 1.0.0"
    generated = []
    def run(command, **_kwargs):
        if command[-1] == "--version":
            return SimpleNamespace(stdout=version)
        generated.append(command)
        directory = Path(command[-1])
        for name, schema in schemas.items():
            (directory / f"{name}.json").write_text(json.dumps(schema))
        return SimpleNamespace(stdout="")
    monkeypatch.setattr(capture.subprocess, "run", run)
    capture._CONFORMANCE_CACHE.clear()
    capture.conformance(str(binary), outbox=outbox)
    capture._CONFORMANCE_CACHE.clear()
    capture.conformance(str(binary), outbox=outbox)
    assert len(generated) == 1
    version = "codex-cli 1.0.1"
    with pytest.raises(ValueError, match="unsupported"):
        capture.conformance(str(binary), outbox=outbox)
    outbox.metadata("approved_profiles", {version: {"qualified": True, "reference_profile_version": "codex-cli 1.0.0", "schema_fingerprint": fingerprint}})
    assert capture.conformance(str(binary), outbox=outbox)[0] == version
    assert len(generated) == 2


def test_context_launcher_pins_its_selected_native_package(outbox, tmp_path, monkeypatch):
    binary = vendor(tmp_path, "vendor")
    launcher = tmp_path / "codex"
    launcher.write_text('#!/usr/bin/env python3\nimport os\nreal = os.environ.get("CODEX_REAL")\n')
    monkeypatch.setenv("CODEX_REAL", str(binary))
    pinned = Path(update.pin_runtime(outbox, str(launcher)))
    assert pinned.read_bytes() == binary.read_bytes()
    assert (pinned.parent.parent / "codex-resources/helper").is_file()


@pytest.mark.parametrize("action,code", [("check-update", "registry_check_failed"), ("stage-update", "candidate_install_failed"), ("qualify-update", "delivery_credentials_unavailable")])
def test_operator_update_failure_codes_are_specific_and_content_free(outbox, tmp_path, monkeypatch, action, code):
    candidate = update.pin_runtime(outbox, str(vendor(tmp_path, "vendor")))
    outbox.metadata("update", {"latest_version": "1.0.0", "candidate": {"binary": candidate, "version": "1.0.0", "binary_sha256": hashlib.sha256(Path(candidate).read_bytes()).hexdigest(), "runtime_sha256": update.runtime_digest(Path(candidate))}})
    def failed(*_args, **_kwargs):
        raise update.subprocess.CalledProcessError(1, "npm", stderr="PRIVATE CREDENTIAL PAYLOAD")
    monkeypatch.setattr(update.subprocess, "run", failed)
    monkeypatch.setattr(importlib.import_module("codex_managed_delivery"), "owner_credentials", lambda: (None, None))
    with pytest.raises(update.ManagedUpdateError) as caught:
        update.update_action(outbox, action)
    assert caught.value.code == code and caught.value.stage == action
    status = update.update_status(outbox)
    assert status["error_code"] == code and status["error_stage"] == action
    assert "PRIVATE" not in json.dumps(status)


@pytest.fixture(autouse=True)
def isolated_managed_host_settings(tmp_path, monkeypatch):
    """Host policy must never make unit tests initialize the owner's real spools."""
    home = tmp_path / "isolated-home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda _cls: home))
    for key in ("SUMMITFLOW_CODEX_MANAGED_CAPTURE", "SUMMITFLOW_CODEX_OUTBOX", "SUMMITFLOW_CODEX_OUTBOXES_JSON", "SUMMITFLOW_CODEX_OUTBOX_MAX_BYTES", "SUMMITFLOW_CODEX_RAW_RETENTION_SECONDS", "SUMMITFLOW_CODEX_PROTOCOL_QUALIFICATION"):
        monkeypatch.delenv(key, raising=False)
