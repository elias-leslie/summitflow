from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Literal
from unittest.mock import Mock

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.access_control import AccessPrincipal
from app.api.backups import key_endpoints


@contextmanager
def _client(role: Literal["owner", "viewer", "local", "none"]) -> Iterator[TestClient]:
    app = FastAPI()

    @app.middleware("http")
    async def principal(request: Request, call_next):
        values = {
            "owner": AccessPrincipal("owner@example.test", "owner", True),
            "viewer": AccessPrincipal("viewer@example.test", "viewer", True),
            "local": AccessPrincipal(
                "local@example.test", "owner", True, is_local_bypass=True
            ),
            "none": None,
        }
        request.state.principal = values[role]
        return await call_next(request)

    app.include_router(key_endpoints.router)
    with TestClient(app, base_url="https://summitflow.example") as client:
        yield client


def _status() -> dict[str, object]:
    return {
        "configured": True,
        "ready": False,
        "key_id": "age:fixture",
        "roundtrip_verified_at": None,
        "recipient_file": "/private/recipient.txt",
        "identity_exported": False,
        "protection_limit": "host compromise can expose the key",
    }


def test_status_allows_owner_bypass_but_marks_management_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(key_endpoints.backup_keys, "get_backup_key_status", _status)

    with _client("local") as client:
        response = client.get("/backups/encryption")

    assert response.status_code == 200
    assert response.json()["can_manage_key"] is False
    assert response.headers["cache-control"].startswith("no-store")
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "recovery_key" not in response.json()


@pytest.mark.parametrize("role", ["viewer", "none"])
def test_status_rejects_non_owner(role: Literal["viewer", "none"], monkeypatch) -> None:
    monkeypatch.setattr(key_endpoints.backup_keys, "get_backup_key_status", _status)

    with _client(role) as client:
        response = client.get("/backups/encryption")

    assert response.status_code == 403


@pytest.mark.parametrize("path", ["setup", "export", "import", "verify"])
def test_key_mutations_reject_local_owner_bypass(path: str, monkeypatch) -> None:
    monkeypatch.setattr(key_endpoints.backup_keys, "setup_backup_key", Mock())
    monkeypatch.setattr(key_endpoints.backup_keys, "export_backup_recovery_key", Mock())
    monkeypatch.setattr(key_endpoints.backup_keys, "import_backup_recovery_key", Mock())
    monkeypatch.setattr(key_endpoints.backup_keys, "verify_backup_recovery_key", Mock())
    body = (
        {"recovery_key": "AGE-SECRET-KEY-test"}
        if path in {"import", "verify"}
        else None
    )

    with _client("local") as client:
        response = client.post(
            f"/backups/encryption/{path}",
            json=body,
            headers={"Sec-Fetch-Site": "same-origin"},
        )

    assert response.status_code == 403
    assert response.headers["cache-control"].startswith("no-store")


def test_setup_is_same_origin_and_never_returns_key(monkeypatch) -> None:
    setup = Mock(return_value=_status())
    monkeypatch.setattr(key_endpoints.backup_keys, "setup_backup_key", setup)

    with _client("owner") as client:
        rejected = client.post(
            "/backups/encryption/setup",
            headers={"Origin": "https://evil.example", "Sec-Fetch-Site": "cross-site"},
        )
        accepted = client.post(
            "/backups/encryption/setup",
            headers={"Origin": "https://summitflow.example"},
        )
        wrong_port = client.post(
            "/backups/encryption/setup",
            headers={"Origin": "https://summitflow.example:444"},
        )

    assert rejected.status_code == 403
    assert wrong_port.status_code == 403
    assert accepted.status_code == 200
    assert accepted.json()["can_manage_key"] is True
    assert "recovery_key" not in accepted.json()
    setup.assert_called_once_with()


def test_forwarded_same_origin_is_accepted_without_fetch_metadata(monkeypatch) -> None:
    setup = Mock(return_value=_status())
    monkeypatch.setattr(key_endpoints.backup_keys, "setup_backup_key", setup)

    with _client("owner") as client:
        response = client.post(
            "/backups/encryption/setup",
            headers={
                "Host": "internal-service:8001",
                "X-Forwarded-Host": "summitflow.example",
                "Origin": "https://summitflow.example",
            },
        )

    assert response.status_code == 200
    setup.assert_called_once_with()


def test_export_returns_deliberate_no_store_json_and_safe_audit(monkeypatch) -> None:
    secret = "AGE-SECRET-KEY-fixture-only"
    monkeypatch.setattr(
        key_endpoints.backup_keys,
        "export_backup_recovery_key",
        lambda: ("age:fixture", secret),
    )
    audit = Mock()
    monkeypatch.setattr(key_endpoints.logger, "info", audit)

    with _client("owner") as client:
        response = client.post(
            "/backups/encryption/export",
            headers={"Sec-Fetch-Site": "same-origin"},
        )

    assert response.status_code == 200
    assert response.json() == {"key_id": "age:fixture", "recovery_key": secret}
    assert response.headers["cache-control"].startswith("no-store")
    assert response.headers["referrer-policy"] == "no-referrer"
    assert secret not in repr(audit.call_args)
    assert audit.call_args.kwargs == {
        "action": "export",
        "actor": "owner@example.test",
        "key_id": "age:fixture",
    }


def test_import_uses_secret_value_and_returns_only_status(monkeypatch) -> None:
    secret = "AGE-SECRET-KEY-import-fixture"
    imported_status = {**_status(), "ready": True, "identity_exported": True}
    imported = Mock(return_value=imported_status)
    monkeypatch.setattr(key_endpoints.backup_keys, "import_backup_recovery_key", imported)
    audit = Mock()
    monkeypatch.setattr(key_endpoints.logger, "info", audit)

    with _client("owner") as client:
        response = client.post(
            "/backups/encryption/import",
            json={"recovery_key": secret},
            headers={"Sec-Fetch-Site": "same-origin"},
        )

    assert response.status_code == 200
    assert response.json()["ready"] is True
    assert "recovery_key" not in response.json()
    assert response.headers["cache-control"].startswith("no-store")
    imported.assert_called_once_with(secret)
    assert secret not in repr(audit.call_args)
    assert audit.call_args.kwargs == {
        "action": "import",
        "actor": "owner@example.test",
        "key_id": "age:fixture",
    }


def test_verify_uses_secret_value_without_echoing_failures(monkeypatch) -> None:
    verify = Mock(side_effect=key_endpoints.backup_keys.BackupKeyVerificationError("recovery_key_invalid"))
    monkeypatch.setattr(key_endpoints.backup_keys, "verify_backup_recovery_key", verify)
    secret = "AGE-SECRET-KEY-do-not-echo"

    with _client("owner") as client:
        response = client.post(
            "/backups/encryption/verify",
            json={"recovery_key": secret},
            headers={"Sec-Fetch-Site": "same-origin"},
        )

    assert response.status_code == 400
    assert secret not in response.text
    assert response.headers["cache-control"].startswith("no-store")
    verify.assert_called_once_with(secret)


@pytest.mark.parametrize(
    "payload,sentinel",
    [
        ({"recovery_key": ["SENTINEL-RECOVERY-LIST"]}, "SENTINEL-RECOVERY-LIST"),
        ({"secret_extra": "SENTINEL-RECOVERY-EXTRA"}, "SENTINEL-RECOVERY-EXTRA"),
    ],
)
def test_malformed_secret_payload_is_sanitized_and_never_logged(
    payload: dict[str, object], sentinel: str, monkeypatch, caplog
) -> None:
    verify = Mock()
    monkeypatch.setattr(key_endpoints.backup_keys, "verify_backup_recovery_key", verify)

    with _client("owner") as client:
        response = client.post(
            "/backups/encryption/verify",
            json=payload,
            headers={"Sec-Fetch-Site": "same-origin"},
        )

    assert response.status_code == 422
    assert response.json() == {"detail": "Invalid backup encryption request"}
    assert sentinel not in response.text
    assert sentinel not in caplog.text
    assert response.headers["cache-control"].startswith("no-store")
    assert response.headers["referrer-policy"] == "no-referrer"
    verify.assert_not_called()


def test_unexpected_verify_failure_does_not_echo_or_log_secret(monkeypatch) -> None:
    secret = "AGE-SECRET-KEY-SENTINEL-UNEXPECTED"
    monkeypatch.setattr(
        key_endpoints.backup_keys,
        "verify_backup_recovery_key",
        Mock(side_effect=RuntimeError(f"failed with {secret}")),
    )
    audit = Mock()
    monkeypatch.setattr(key_endpoints.logger, "error", audit)

    with _client("owner") as client:
        response = client.post(
            "/backups/encryption/verify",
            json={"recovery_key": secret},
            headers={"Sec-Fetch-Site": "same-origin"},
        )

    assert response.status_code == 500
    assert secret not in response.text
    assert secret not in repr(audit.call_args)
    assert response.headers["cache-control"].startswith("no-store")
    assert audit.call_args.kwargs == {"path": "/backups/encryption/verify"}
