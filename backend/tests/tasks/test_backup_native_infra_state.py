"""Recovery-state coverage for native infrastructure archives."""

from __future__ import annotations

import json
import os
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
    credentials = roots["home"] / ".config" / "credstore" / "summitflow" / "compose.env"
    credentials.parent.mkdir(parents=True)
    credentials.write_text("secret=compose\n")
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

    assert "infrastructure/state/host-ingress/cloudflared/config.yml" in names
    assert "infrastructure/state/host-ingress/caddy/Caddyfile" in names
    assert "infrastructure/state/host-ingress/cloudflared/tunnel.json" not in names
    assert "infrastructure/state/host-ingress/cloudflared/unrelated.json" not in names
    assert "infrastructure/state/host-ingress/caddy/env" not in names
    with tarfile.open(archive_path, "r:gz") as archive:
        for member in archive.getmembers():
            if member.isfile():
                content = cast(tarfile.ExFileObject, archive.extractfile(member)).read()
                assert b'"credential":"private"' not in content
                assert b"SECRET=private" not in content
        ingress_file = archive.extractfile("infrastructure/state/host-ingress/manifest.json")
        assert ingress_file is not None
        ingress = json.load(ingress_file)
    assert ingress["status"] == "captured"
    assert set(ingress["secrets"]) == {"cloudflared_credentials", "caddy_env"}
    assert ingress["secrets"]["cloudflared_credentials"]["path"] == str(credential_file)
    assert ingress["secrets"]["caddy_env"]["size"] == len("SECRET=private\n")
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


def test_infrastructure_archive_reads_compose_credentials_from_credstore_and_config_from_host_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    roots = _configure_recovery_roots(tmp_path, monkeypatch)
    release_root = tmp_path / "immutable-release"
    release_compose = release_root / "docker" / "compose"
    release_compose.mkdir(parents=True)
    (release_compose / ".env").write_text("wrong=release\n")
    credentials = roots["home"] / ".config" / "credstore" / "summitflow" / "compose.env"
    credentials.parent.mkdir(parents=True)
    credentials.write_text("right=host\n")
    host_root = tmp_path / "stable-host-checkout"
    host_compose = host_root / "docker" / "compose"
    host_compose.mkdir(parents=True)
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


def _write_ingress(roots: dict[str, Path], credential_file: Path) -> None:
    (roots["cloudflared"] / "config.yml").write_text(
        f"tunnel: recovery\ncredentials-file: {credential_file}\n"
    )
    (roots["caddy"] / "Caddyfile").write_text("example.invalid { respond ok }\n")


def test_ingress_secrets_are_recorded_as_stat_facts_without_reading_them(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    roots = _configure_recovery_roots(tmp_path, monkeypatch)
    credential_file = tmp_path / "host-secrets" / "tunnel.json"
    credential_file.parent.mkdir()
    credential_file.write_text("TOP-SECRET-TUNNEL\n")
    caddy_env = roots["caddy"] / "env"
    caddy_env.write_text("CLOUDFLARE_API_TOKEN=TOP-SECRET-TOKEN\n")
    _write_ingress(roots, credential_file)
    # After the ACL removal neither file is readable by the backup's uid.
    credential_file.chmod(0o000)
    caddy_env.chmod(0o000)
    copied: list[Path] = []
    original = infra._copy_regular_path

    def record_copy(source: Path, destination: Path, **kwargs):
        copied.append(source)
        return original(source, destination, **kwargs)

    monkeypatch.setattr(infra, "_copy_regular_path", record_copy)
    capture = tmp_path / "capture"
    try:
        result = infra._capture_host_ingress(capture)
    finally:
        credential_file.chmod(0o600)
        caddy_env.chmod(0o600)

    assert result["status"] == "captured", result
    assert result["missing"] == []
    assert result["credential_file"] == "tunnel.json"
    assert credential_file not in copied
    assert caddy_env not in copied
    facts = result["secrets"]["cloudflared_credentials"]
    assert facts["path"] == str(credential_file)
    assert facts["exists"] is True
    assert facts["size"] == len("TOP-SECRET-TUNNEL\n")
    assert facts["mode"] == "0000"
    assert facts["owner"] and facts["group"] and facts["mtime"]
    assert result["secrets"]["caddy_env"]["path"] == str(caddy_env)
    staged = sorted(path.relative_to(capture).as_posix() for path in capture.rglob("*") if path.is_file())
    assert staged == ["caddy/Caddyfile", "cloudflared/config.yml", "manifest.json"]
    manifest = (capture / "manifest.json").read_text()
    assert "TOP-SECRET" not in manifest
    assert json.loads(manifest)["secrets"] == result["secrets"]


def test_ingress_capture_purges_secret_copies_already_in_staging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    roots = _configure_recovery_roots(tmp_path, monkeypatch)
    credential_file = roots["cloudflared"] / "tunnel.json"
    credential_file.write_text("TOP-SECRET-TUNNEL\n")
    (roots["caddy"] / "env").write_text("TOP-SECRET-TOKEN\n")
    _write_ingress(roots, credential_file)
    capture = tmp_path / "capture"
    (capture / "cloudflared" / "nested").mkdir(parents=True)
    (capture / "cloudflared" / "tunnel.json").write_text("TOP-SECRET-TUNNEL\n")
    (capture / "cloudflared" / "nested" / "old.json").write_text("TOP-SECRET-TUNNEL\n")
    (capture / "caddy").mkdir()
    (capture / "caddy" / "env").write_text("TOP-SECRET-TOKEN\n")

    result = infra._capture_host_ingress(capture)

    assert result["status"] == "captured"
    for path in capture.rglob("*"):
        if path.is_file():
            assert "TOP-SECRET" not in path.read_text()
    assert not (capture / "cloudflared" / "tunnel.json").exists()
    assert not (capture / "caddy" / "env").exists()


@pytest.mark.parametrize("target", ["credential", "caddy_env"])
def test_ingress_secret_symlink_is_never_followed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    target: str,
) -> None:
    roots = _configure_recovery_roots(tmp_path, monkeypatch)
    decoy = tmp_path / "readable-decoy"
    decoy.write_text("TOP-SECRET-DECOY\n")
    credential_file = roots["cloudflared"] / "tunnel.json"
    caddy_env = roots["caddy"] / "env"
    credential_file.write_text("{}\n")
    caddy_env.write_text("X=1\n")
    link = credential_file if target == "credential" else caddy_env
    link.unlink()
    link.symlink_to(decoy)
    _write_ingress(roots, credential_file)
    capture = tmp_path / "capture"

    result = infra._capture_host_ingress(capture)

    assert result["status"] == "error"
    label = "cloudflared_credentials" if target == "credential" else "caddy_env"
    assert result["error"] == f"{label} is not a regular file"
    assert label not in result["secrets"]
    for path in capture.rglob("*"):
        if path.is_file():
            assert "TOP-SECRET" not in path.read_text()


def test_missing_ingress_secrets_are_listed_as_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    roots = _configure_recovery_roots(tmp_path, monkeypatch)
    _write_ingress(roots, roots["cloudflared"] / "absent.json")

    result = infra._capture_host_ingress(tmp_path / "capture")

    assert result["status"] == "missing"
    assert result["missing"] == ["cloudflared_credentials", "caddy_env"]
    assert result["secrets"] == {}


def test_unreadable_ingress_state_is_flagged_without_losing_other_capture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    roots = _configure_recovery_roots(tmp_path, monkeypatch)
    credential_file = tmp_path / "credential.json"
    credential_file.write_text("TOP-SECRET-CONTENT\n")
    _write_ingress(roots, credential_file)
    (roots["caddy"] / "env").write_text("private\n")
    original = infra._copy_regular_path

    def deny_config(source: Path, destination: Path, **kwargs):
        if source.name == "Caddyfile":
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


def test_restic_point_reads_coverage_from_nested_capture_evidence() -> None:
    names = (
        "env_local", "compose_env", "smb_credentials", "hatchet_config", "redis_state",
        "host_ingress", "systemd_user", "agent_hub_state", "managed_service_state",
    )
    result = verify_archive_coverage(
        {
            "format": "restic-v1",
            "has_db": True,
            "capture": {
                "has_db": True,
                "tree": {"configs": {"count": 7}, "state": {"count": 10}, "pgdumpall.sql": {"count": 1}},
                "coverage": {
                    "schema_version": 1,
                    "components": {name: {"status": "captured"} for name in names},
                },
            },
        }
    )

    assert result.complete is True
    assert (result.present_count, result.required_count) == (10, 10)


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


def test_infrastructure_payload_contains_plain_sql_and_measured_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import gzip

    _configure_recovery_roots(tmp_path, monkeypatch)
    project = tmp_path / "project"
    project.mkdir()
    sql = b"-- PostgreSQL database cluster dump\nSELECT 1;\n"

    def dump(destination):
        assert destination.name == "pgdumpall.sql"
        destination.write_bytes(sql)
        return len(sql)

    monkeypatch.setattr(infra, "_dump_infra_database", dump)
    monkeypatch.setattr(infra, "_collect_redis_dump", lambda _path: None)
    payload = infra.prepare_infrastructure_payload(project, tmp_path / "stage")
    snapshot = payload["snapshot_dir"]
    assert (snapshot / "pgdumpall.sql").read_bytes() == sql
    assert not (snapshot / "pgdumpall.sql.gz").exists()
    assert payload["db_bytes"] == len(sql)
    assert payload["logical_bytes"] == sum(path.stat().st_size for path in snapshot.rglob("*") if path.is_file())
    assert payload["total_files"] == sum(path.is_file() for path in snapshot.rglob("*"))
    assert payload["verification"]["coverage"]["schema_version"] == 1
    assert payload["verification"]["verified"] is True
    legacy, db_bytes, result = infra._build_infra_archive(project, tmp_path / "legacy-stage", "fixture.tar.gz")
    with tarfile.open(legacy, "r:gz") as packed:
        database = packed.extractfile("infrastructure/pgdumpall.sql.gz")
        assert database is not None
        compressed = database.read()
        assert gzip.decompress(compressed) == sql
        assert "infrastructure/pgdumpall.sql" not in packed.getnames()
    assert db_bytes == len(compressed)
    assert result["verification"]["has_db"] is True


def test_infrastructure_payload_captures_home_credentials_without_links_or_sockets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import socket

    roots = _configure_recovery_roots(tmp_path, monkeypatch)
    home = roots["home"]
    (home / ".ssh").mkdir(mode=0o700)
    (home / ".ssh" / "id_ed25519").write_text("fixture-key\n")
    (home / ".ssh" / "linked").symlink_to(tmp_path)
    (home / ".gitconfig").write_text("[user]\n")
    (home / ".gnupg").mkdir(mode=0o700)
    agent = socket.socket(socket.AF_UNIX)
    # Bind by relative name: CI tmp paths can exceed the 108-byte AF_UNIX limit.
    cwd = Path.cwd()
    os.chdir(home / ".gnupg")
    try:
        agent.bind("S.gpg-agent")
    finally:
        os.chdir(cwd)
    (home / ".ssh" / "config").write_text("Host vault-backup\n")
    (home / ".aws").mkdir()
    (home / ".aws" / "credentials").write_text("[prod-archive]\n")
    canaries = [home / ".ssh" / "config", home / ".aws"]
    monkeypatch.setattr(infra, "canary_paths", lambda: canaries)
    monkeypatch.setattr(infra, "_dump_infra_database", lambda path: path.write_bytes(b"SELECT 1;\n"))
    monkeypatch.setattr(infra, "_collect_redis_dump", lambda _path: None)
    try:
        payload = infra.prepare_infrastructure_payload(tmp_path / "project", tmp_path / "stage")
    finally:
        agent.close()
    captured = payload["snapshot_dir"] / "configs" / "home"
    assert (captured / ".ssh" / "id_ed25519").read_text() == "fixture-key\n"
    assert (captured / ".gitconfig").is_file()
    assert not (captured / ".ssh" / "linked").exists()
    assert not (captured / ".gnupg" / "S.gpg-agent").exists()
    assert not (captured / ".ssh" / "config").exists()
    assert not (captured / ".aws").exists()
    assert payload["verification"]["coverage"]["components"]["home_config"] == {"status": "captured"}


def test_infrastructure_payload_skips_home_credentials_without_canary_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    roots = _configure_recovery_roots(tmp_path, monkeypatch)
    (roots["home"] / ".gitconfig").write_text("[user]\n")
    monkeypatch.setattr(infra, "canary_paths", lambda: None)
    monkeypatch.setattr(infra, "_dump_infra_database", lambda path: path.write_bytes(b"SELECT 1;\n"))
    monkeypatch.setattr(infra, "_collect_redis_dump", lambda _path: None)
    payload = infra.prepare_infrastructure_payload(tmp_path / "project", tmp_path / "stage")
    assert not (payload["snapshot_dir"] / "configs" / "home").exists()
    assert payload["verification"]["coverage"]["components"]["home_config"]["status"] != "captured"


def test_infrastructure_payload_rejects_empty_database_dump(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_recovery_roots(tmp_path, monkeypatch)
    monkeypatch.setattr(infra, "_dump_infra_database", lambda path: path.write_bytes(b""))
    with pytest.raises(RuntimeError, match="dump is empty"):
        infra.prepare_infrastructure_payload(tmp_path / "project", tmp_path / "stage")


def test_infrastructure_copy_preserves_live_sqlite_and_jsonl_prefix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sqlite3

    source = tmp_path / "source"
    source.mkdir()
    database = source / "state.db"
    log = source / "sessions.jsonl"
    prefix = b'{"before":true}\n'
    log.write_bytes(prefix)
    original = infra.copy_inventory_snapshot
    with sqlite3.connect(database) as writer:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("CREATE TABLE records (value TEXT)")
        writer.execute("INSERT INTO records VALUES ('before')")
        writer.commit()

        def copy_then_write(*args):
            original(*args)
            writer.execute("INSERT INTO records VALUES ('after')")
            writer.commit()
            with log.open("ab") as output:
                output.write(b'{"after":true}\n')

        monkeypatch.setattr(infra, "copy_inventory_snapshot", copy_then_write)
        destination = tmp_path / "destination"
        result = infra._copy_regular_path(source, destination)
    assert result["files"] == 2
    assert (destination / "sessions.jsonl").read_bytes() == prefix
    assert not (destination / "state.db-wal").exists()
    with sqlite3.connect(destination / "state.db") as restored:
        assert restored.execute("SELECT value FROM records").fetchall() == [("before",)]


def test_infrastructure_copy_rejects_concurrent_regular_file_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    file = source / "config.json"
    file.write_text("before")
    original = infra.copy_inventory_snapshot

    def copy_then_write(*args):
        original(*args)
        file.write_text("after")

    monkeypatch.setattr(infra, "copy_inventory_snapshot", copy_then_write)
    destination = tmp_path / "destination"
    with pytest.raises(RuntimeError, match="source changed during capture"):
        infra._copy_regular_path(source, destination)
    assert not destination.exists()


def test_redis_snapshot_authenticates_through_the_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    roots = _configure_recovery_roots(tmp_path, monkeypatch)
    credentials = roots["home"] / ".config" / "credstore" / "summitflow" / "compose.env"
    credentials.parent.mkdir(parents=True)
    credentials.write_text('POSTGRES_PASSWORD=x\nREDIS_PASSWORD="stack-redis-secret"\n')
    monkeypatch.delenv("REDIS_PASSWORD", raising=False)
    monkeypatch.setattr(infra.shutil, "which", lambda _name: "/usr/bin/redis-cli")
    seen: dict[str, object] = {}

    def fake_bulk(command: list[str], **kwargs: object) -> object:
        seen.update(command=command, env=kwargs["env"])
        Path(command[-1]).write_bytes(b"REDIS0012")
        return type("Result", (), {"returncode": 0})()

    monkeypatch.setattr(infra, "run_bulk_process", fake_bulk)
    destination = tmp_path / "redis-dump.rdb"

    infra._collect_redis_dump(destination)

    assert destination.read_bytes().startswith(b"REDIS")
    assert cast(dict[str, str], seen["env"])["REDISCLI_AUTH"] == "stack-redis-secret"
    assert "stack-redis-secret" not in " ".join(cast(list[str], seen["command"]))
