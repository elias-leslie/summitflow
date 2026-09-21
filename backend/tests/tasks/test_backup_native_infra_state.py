"""Recovery-state coverage for native infrastructure archives."""

from __future__ import annotations

import json
import tarfile
from pathlib import Path
from typing import cast

import pytest

from app.tasks import backup_native_infra as infra
from app.tasks.backup_coverage import verify_archive_coverage


def _configure_recovery_roots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    home = tmp_path / "home"
    state_home = home / ".local" / "state"
    config_home = home / ".config"
    cloudflared = tmp_path / "etc" / "cloudflared"
    caddy = tmp_path / "etc" / "caddy"
    services = home / ".summitflow" / "services"
    for directory in (home, state_home, config_home, cloudflared, caddy, services):
        directory.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setenv("XDG_STATE_HOME", str(state_home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_home))
    monkeypatch.setenv("SUMMITFLOW_SERVICE_STATE_ROOT", str(services))
    monkeypatch.setenv("CLOUDFLARED_CONFIG", str(cloudflared / "config.yml"))
    monkeypatch.setenv("CADDY_CONFIG", str(caddy / "Caddyfile"))
    monkeypatch.setenv("CADDY_ENV_FILE", str(caddy / "env"))
    return {
        "home": home,
        "state_home": state_home,
        "config_home": config_home,
        "cloudflared": cloudflared,
        "caddy": caddy,
        "services": services,
    }


def test_infrastructure_archive_captures_required_recovery_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    roots = _configure_recovery_roots(tmp_path, monkeypatch)
    project = tmp_path / "summitflow"
    compose = project / "docker" / "compose"
    compose.mkdir(parents=True)
    (roots["home"] / ".env.local").write_text("secret=global\n")
    (compose / ".env").write_text("secret=compose\n")
    (compose / "hatchet-config").mkdir()
    (compose / "hatchet-config" / "server.yaml").write_text("server: local\n")
    (roots["home"] / ".smbcredentials").write_text("secret=smb\n")

    credential_file = tmp_path / "host-secrets" / "tunnel.json"
    credential_file.parent.mkdir()
    credential_file.write_text('{"credential":"private"}\n')
    (roots["cloudflared"] / "config.yml").write_text(
        f"tunnel: recovery\ncredentials-file: {credential_file}\n"
    )
    (roots["cloudflared"] / "unrelated.json").write_text('{"not":"a credential"}\n')
    (roots["caddy"] / "Caddyfile").write_text("example.invalid { respond ok }\n")
    (roots["caddy"] / "env").write_text("SECRET=private\n")

    systemd = roots["config_home"] / "systemd" / "user"
    wants = systemd / "default.target.wants"
    wants.mkdir(parents=True)
    (systemd / "agent-hub.service").write_text("[Service]\nExecStart=/bin/true\n")
    (wants / "agent-hub.service").symlink_to("../agent-hub.service")

    agent_state = roots["state_home"] / "agent-hub"
    agent_state.mkdir()
    (agent_state / "memory_failures.jsonl").write_text('{"failure":"kept"}\n')
    key_dir = agent_state / "backup-keys"
    key_dir.mkdir()
    (key_dir / "identity.txt").write_text("AGE-SECRET-KEY-test\n")
    monkeypatch.setenv("SUMMITFLOW_BACKUP_KEY_DIR", str(key_dir))

    service_project = roots["services"] / "projects" / "summitflow"
    receipts = service_project / "receipts"
    release = service_project / "releases" / "build-1"
    previous_release = service_project / "releases" / "build-0"
    receipts.mkdir(parents=True)
    release.mkdir(parents=True)
    previous_release.mkdir(parents=True)
    (receipts / "build-1.json").write_text('{"state":"succeeded"}\n')
    (release / "large-runtime-file").write_text("must not be duplicated\n")
    (service_project / "current").symlink_to(release)
    (service_project / "previous").symlink_to(previous_release)
    jobs = roots["services"] / "jobs"
    jobs.mkdir()
    (jobs / "job-1.json").write_text('{"state":"succeeded"}\n')

    monkeypatch.setattr(
        infra,
        "_dump_infra_database",
        lambda path: path.write_bytes(b"compressed database") or path.stat().st_size,
    )
    monkeypatch.setattr(
        infra,
        "_collect_redis_dump",
        lambda path: path.write_bytes(b"REDIS0011"),
    )

    staging = tmp_path / "staging"
    staging.mkdir()
    archive_path, _db_size, result = infra._build_infra_archive(
        project, staging, "infrastructure-test.tar.gz"
    )

    with tarfile.open(archive_path, "r:gz") as archive:
        names = {member.name for member in archive.getmembers() if member.isfile()}
        service_manifest_file = archive.extractfile(
            "infrastructure/state/managed-services/manifest.json"
        )
        systemd_manifest_file = archive.extractfile(
            "infrastructure/state/systemd-user/manifest.json"
        )
        assert service_manifest_file is not None
        assert systemd_manifest_file is not None
        service_manifest = json.load(service_manifest_file)
        systemd_manifest = json.load(systemd_manifest_file)

    assert "infrastructure/state/host-ingress/cloudflared/tunnel.json" in names
    assert "infrastructure/state/host-ingress/cloudflared/unrelated.json" not in names
    assert "infrastructure/state/host-ingress/caddy/env" in names
    assert "infrastructure/state/systemd-user/files/agent-hub.service" in names
    assert "infrastructure/state/agent-hub/files/memory_failures.jsonl" in names
    assert "infrastructure/state/managed-services/projects/summitflow/receipts/build-1.json" in names
    assert "infrastructure/state/managed-services/jobs/job-1.json" in names
    assert all("backup-keys" not in name for name in names)
    assert all("large-runtime-file" not in name for name in names)
    assert service_manifest["projects"]["summitflow"]["current_build"] == "build-1"
    assert service_manifest["projects"]["summitflow"]["previous_build"] == "build-0"
    assert systemd_manifest["enablement"] == [
        {"path": "default.target.wants/agent-hub.service", "target": "../agent-hub.service"}
    ]

    coverage = verify_archive_coverage(result["verification"])
    assert coverage.complete is True
    assert not coverage.missing


def test_infrastructure_archive_reads_compose_state_from_stable_host_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_recovery_roots(tmp_path, monkeypatch)
    release_root = tmp_path / "immutable-release"
    release_compose = release_root / "docker" / "compose"
    release_compose.mkdir(parents=True)
    (release_compose / ".env").write_text("wrong=release\n")
    host_root = tmp_path / "stable-host-checkout"
    host_compose = host_root / "docker" / "compose"
    host_compose.mkdir(parents=True)
    (host_compose / ".env").write_text("right=host\n")
    (host_compose / "hatchet-config").mkdir()
    (host_compose / "hatchet-config" / "server.yaml").write_text("host: true\n")
    monkeypatch.setattr(
        infra,
        "_dump_infra_database",
        lambda path: path.write_bytes(b"compressed database") or path.stat().st_size,
    )
    monkeypatch.setattr(infra, "_collect_redis_dump", lambda _path: None)

    staging = tmp_path / "staging"
    staging.mkdir()
    archive_path, _db_size, _result = infra._build_infra_archive(
        release_root,
        staging,
        "infrastructure-test.tar.gz",
        host_config_root=host_root,
    )

    with tarfile.open(archive_path, "r:gz") as archive:
        compose_env = archive.extractfile("infrastructure/configs/compose-env")
        hatchet_config = archive.extractfile(
            "infrastructure/configs/hatchet-config/server.yaml"
        )
        assert compose_env is not None
        assert hatchet_config is not None
        assert compose_env.read() == b"right=host\n"
        assert hatchet_config.read() == b"host: true\n"


def test_unreadable_ingress_state_is_flagged_without_losing_other_capture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    roots = _configure_recovery_roots(tmp_path, monkeypatch)
    credential_file = tmp_path / "credential.json"
    credential_file.write_text("TOP-SECRET-CONTENT\n")
    (roots["cloudflared"] / "config.yml").write_text(
        f"tunnel: recovery\ncredentials-file: {credential_file}\n"
    )
    (roots["caddy"] / "Caddyfile").write_text("private\n")
    (roots["caddy"] / "env").write_text("private\n")
    original = infra._copy_regular_path

    def deny_config(source: Path, destination: Path, **kwargs):
        if source == credential_file:
            raise PermissionError("TOP-SECRET-CONTENT")
        return original(source, destination, **kwargs)

    monkeypatch.setattr(infra, "_copy_regular_path", deny_config)

    result = infra._capture_host_ingress(tmp_path / "capture")

    assert result["status"] == "error"
    assert result["error"] == "required ingress state is unreadable"
    assert "TOP-SECRET-CONTENT" not in json.dumps(result)


def test_unsupported_cloudflared_credential_reference_is_explicit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    roots = _configure_recovery_roots(tmp_path, monkeypatch)
    (roots["cloudflared"] / "config.yml").write_text(
        "tunnel: recovery\ncredentials-file:\n  nested: unsupported\n"
    )
    (roots["caddy"] / "Caddyfile").write_text("example.invalid\n")
    (roots["caddy"] / "env").write_text("SECRET=private\n")

    result = infra._capture_host_ingress(tmp_path / "capture")

    assert result["status"] == "error"
    assert result["error"] == (
        "cloudflared credential reference is missing or unsupported"
    )


def test_explicit_capture_error_is_reported_as_incomplete_coverage() -> None:
    result = verify_archive_coverage(
        {
            "has_db": True,
            "tree": {"configs": {"count": 8}, "state": {"count": 4}},
            "coverage": {
                "schema_version": 1,
                "components": {
                    "host_ingress": {
                        "status": "error",
                        "error": "required state unreadable",
                    },
                    "systemd_user": {"status": "captured"},
                    "agent_hub_state": {"status": "captured"},
                    "managed_service_state": {"status": "captured"},
                },
            },
        }
    )

    assert result.complete is False
    assert "host_ingress" in result.missing
    component = next(item for item in result.components if item.key == "host_ingress")
    assert component.error == "required state unreadable"


def test_top_level_config_count_cannot_prove_individual_required_components() -> None:
    result = verify_archive_coverage(
        {
            "has_db": True,
            "tree": {"configs": {"count": 1}, "state": {"count": 4}},
            "coverage": {
                "schema_version": 1,
                "components": {
                    "env_local": {"status": "captured"},
                    "host_ingress": {"status": "captured"},
                    "systemd_user": {"status": "captured"},
                    "agent_hub_state": {"status": "captured"},
                    "managed_service_state": {"status": "captured"},
                },
            },
        }
    )

    assert result.complete is False
    assert "env_local" not in result.missing
    assert {
        "compose_env",
        "smb_credentials",
        "hatchet_config",
        "redis_state",
    }.issubset(result.missing)


def test_infrastructure_backup_records_encryption_duration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plaintext = tmp_path / "infrastructure-test.tar.gz"

    def build(_project, _staging, _name, *, host_config_root):
        assert host_config_root == tmp_path / "host-config"
        plaintext.write_bytes(b"plaintext archive")
        return plaintext, 1, {
            "archive_name": plaintext.name,
            "archive_path": plaintext,
            "total_bytes": plaintext.stat().st_size,
            "verification": {"verified": True},
        }

    def encrypt(_source, destination, _env):
        destination.write_bytes(b"encrypted archive")
        return {
            "checksum": "sha256:cipher",
            "content_checksum": "sha256:plain",
            "encrypted_bytes": destination.stat().st_size,
            "duration_ms": 37,
        }

    captured: dict[str, object] = {}

    def finish(_project, _source_id, result, *_args, **_kwargs):
        captured.update(result)
        return result

    monkeypatch.setattr(infra, "get_repo_root", lambda: tmp_path / "release")
    monkeypatch.setattr(
        infra,
        "get_host_config_root",
        lambda: tmp_path / "host-config",
    )
    monkeypatch.setattr(infra, "_storage_config", lambda *_args: object())
    monkeypatch.setattr(infra, "_build_infra_archive", build)
    monkeypatch.setattr(infra, "encrypt_completed_archive", encrypt)
    monkeypatch.setattr(infra, "storage_backend_type", lambda _env: "local")
    monkeypatch.setattr(infra, "_finish_infra_backup", finish)

    infra.run_infra_backup()

    verification = cast(dict[str, object], captured["verification"])
    assert verification["encryption"] == {"duration_ms": 37}


def test_generic_infrastructure_copy_hard_excludes_backup_key_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source"
    key_dir = source / "nested" / "backup-keys"
    key_dir.mkdir(parents=True)
    (source / "kept.txt").write_text("recoverable\n")
    (key_dir / "identity.txt").write_text("AGE-SECRET-KEY-test\n")
    monkeypatch.setenv("SUMMITFLOW_BACKUP_KEY_DIR", str(key_dir))
    destination = tmp_path / "destination"

    assert infra._copy_if_exists(source, destination) == 1
    assert (destination / "kept.txt").is_file()
    assert not (destination / "nested" / "backup-keys").exists()
