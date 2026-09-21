"""Host-local age key management for encrypted backup and recovery workflows."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import shutil
import stat
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..utils import safe_subprocess


class BackupKeyUnavailableError(RuntimeError):
    """A usable backup encryption key is unavailable."""


class BackupKeyVerificationError(RuntimeError):
    """A supplied recovery key does not prove recovery for the configured recipient."""


_IDENTITY_NAME = "backup-identity.agekey"
_RECIPIENT_NAME = "backup-recipient.txt"
_STATE_NAME = "backup-key-state.json"
_LOCK_NAME = ".backup-key.lock"
_SECRET_PREFIX = "AGE-SECRET-KEY-"
_PROTECTION_LIMIT = (
    "Protected by host directory and file permissions; compromise of the service account "
    "or host can expose the recovery key."
)


def backup_key_directory() -> Path:
    """Return the private host directory excluded from backup archives."""
    configured = os.environ.get("SUMMITFLOW_BACKUP_KEY_DIR", "").strip()
    if configured:
        return Path(os.path.abspath(os.fspath(Path(configured).expanduser())))
    state_home = os.environ.get("XDG_STATE_HOME", "").strip()
    base = Path(state_home).expanduser() if state_home else Path.home() / ".local" / "state"
    return Path(os.path.abspath(os.fspath(base / "summitflow" / "backup-keys")))


def _paths() -> tuple[Path, Path, Path]:
    directory = backup_key_directory()
    return (
        directory / _RECIPIENT_NAME,
        directory / _IDENTITY_NAME,
        directory / _STATE_NAME,
    )


def _reject_symlink_components(path: Path) -> None:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        try:
            metadata = current.lstat()
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise BackupKeyUnavailableError("backup_key_directory_unsafe") from exc
        if stat.S_ISLNK(metadata.st_mode):
            raise BackupKeyUnavailableError("backup_key_directory_unsafe")


def _reject_broad_key_directory(directory: Path) -> None:
    state_home = os.environ.get("XDG_STATE_HOME", "").strip()
    state_root = (
        Path(os.path.abspath(os.fspath(Path(state_home).expanduser())))
        if state_home
        else Path(os.path.abspath(os.fspath(Path.home() / ".local" / "state")))
    )
    protected_roots = {
        Path(directory.anchor),
        Path(os.path.abspath(os.fspath(Path.home()))),
        Path(os.path.abspath(os.fspath(Path.home() / ".local"))),
        state_root,
        state_root / "summitflow",
    }
    if directory in protected_roots:
        raise BackupKeyUnavailableError("backup_key_directory_unsafe")


def _validate_private_directory(directory: Path, *, allow_missing: bool) -> bool:
    _reject_broad_key_directory(directory)
    _reject_symlink_components(directory)
    try:
        metadata = directory.lstat()
    except FileNotFoundError:
        if allow_missing:
            return False
        raise BackupKeyUnavailableError("backup_key_directory_missing") from None
    except OSError as exc:
        raise BackupKeyUnavailableError("backup_key_directory_unsafe") from exc
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) != 0o700
    ):
        raise BackupKeyUnavailableError("backup_key_directory_unsafe")
    return True


def _ensure_private_directory() -> Path:
    directory = backup_key_directory()
    if _validate_private_directory(directory, allow_missing=True):
        return directory
    try:
        if os.environ.get("SUMMITFLOW_BACKUP_KEY_DIR", "").strip():
            directory.mkdir(mode=0o700, parents=False)
        else:
            directory.mkdir(mode=0o700, parents=True)
    except FileExistsError:
        pass
    except OSError as exc:
        raise BackupKeyUnavailableError("backup_key_directory_unavailable") from exc
    _validate_private_directory(directory, allow_missing=False)
    return directory


@contextmanager
def _key_lock() -> Iterator[None]:
    directory = _ensure_private_directory()
    lock_path = directory / _LOCK_NAME
    descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "r+", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except Exception:
        with suppress(OSError):
            os.close(descriptor)
        raise


def _secure_write_new(path: Path, content: bytes) -> None:
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        0o600,
    )
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        path.unlink(missing_ok=True)
        raise


def _atomic_private_json(path: Path, value: dict[str, Any]) -> None:
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        delete=False,
    ) as handle:
        temporary = Path(handle.name)
        os.fchmod(handle.fileno(), 0o600)
        json.dump(value, handle, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)
    path.chmod(0o600)


def _run_age(command: list[str], *, input_bytes: bytes | None = None) -> bytes:
    try:
        result = safe_subprocess.run(
            command,
            input=input_bytes,
            capture_output=True,
            check=False,
        )
    except OSError as exc:
        raise BackupKeyUnavailableError("backup_key_tool_unavailable") from exc
    if result.returncode != 0:
        raise BackupKeyUnavailableError("backup_key_tool_failed")
    return result.stdout


def _age_binary(name: str) -> str:
    executable = shutil.which(name)
    if not executable:
        raise BackupKeyUnavailableError("backup_key_tool_unavailable")
    return executable


def _safe_file(path: Path) -> bool:
    try:
        metadata = path.stat()
        return (
            path.is_file()
            and not path.is_symlink()
            and metadata.st_uid == os.geteuid()
            and (metadata.st_mode & 0o077) == 0
        )
    except OSError:
        return False


def _recipient_for_identity(identity_file: Path) -> str:
    if not _safe_file(identity_file):
        raise BackupKeyUnavailableError("backup_key_invalid")
    output = _run_age([_age_binary("age-keygen"), "-y", str(identity_file)])
    recipient = output.decode("utf-8", errors="strict").strip()
    if not recipient.startswith("age1") or any(char.isspace() for char in recipient):
        raise BackupKeyUnavailableError("backup_key_invalid")
    return recipient


def _key_id(recipient: str) -> str:
    return "age:" + hashlib.sha256(recipient.encode()).hexdigest()[:16]


def _read_recipient(path: Path) -> str:
    if not _safe_file(path):
        raise BackupKeyUnavailableError("backup_key_invalid")
    try:
        recipient = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise BackupKeyUnavailableError("backup_key_invalid") from exc
    if not recipient.startswith("age1") or any(char.isspace() for char in recipient):
        raise BackupKeyUnavailableError("backup_key_invalid")
    return recipient


def _configured_identity() -> tuple[Path, Path, str]:
    recipient_file, identity_file, _state_file = _paths()
    if not recipient_file.exists() and not identity_file.exists():
        raise BackupKeyUnavailableError("backup_key_not_configured")
    if not recipient_file.exists() or not identity_file.exists():
        raise BackupKeyUnavailableError("backup_key_incomplete")
    recipient = _read_recipient(recipient_file)
    if _recipient_for_identity(identity_file) != recipient:
        raise BackupKeyUnavailableError("backup_key_invalid")
    return recipient_file, identity_file, recipient


def _read_state() -> dict[str, Any]:
    _recipient_file, _identity_file, state_file = _paths()
    if not state_file.exists():
        return {}
    if not _safe_file(state_file):
        raise BackupKeyUnavailableError("backup_key_invalid")
    try:
        value = json.loads(state_file.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BackupKeyUnavailableError("backup_key_invalid") from exc
    if not isinstance(value, dict):
        raise BackupKeyUnavailableError("backup_key_invalid")
    return value


def _write_state(*, key_id: str, identity_exported: bool, verified_at: str | None) -> None:
    _recipient_file, _identity_file, state_file = _paths()
    _atomic_private_json(
        state_file,
        {
            "key_id": key_id,
            "identity_exported": identity_exported,
            "roundtrip_verified_at": verified_at,
        },
    )


def get_backup_key_status() -> dict[str, Any]:
    """Return non-secret backup key readiness and recovery evidence."""
    recipient_file, identity_file, _state_file = _paths()
    configured = recipient_file.exists() or identity_file.exists() or _state_file.exists()
    try:
        _validate_private_directory(backup_key_directory(), allow_missing=True)
        _recipient_path, _identity_path, recipient = _configured_identity()
        state = _read_state()
        key_id = _key_id(recipient)
        verified_at = (
            state.get("roundtrip_verified_at")
            if state.get("key_id") == key_id
            and isinstance(state.get("roundtrip_verified_at"), str)
            else None
        )
        exported = state.get("identity_exported") is True and state.get("key_id") == key_id
        return {
            "configured": True,
            "ready": verified_at is not None,
            "key_id": key_id,
            "roundtrip_verified_at": verified_at,
            "recipient_file": str(recipient_file),
            "identity_exported": exported,
            "protection_limit": _PROTECTION_LIMIT,
        }
    except BackupKeyUnavailableError as exc:
        return {
            "configured": configured,
            "ready": False,
            "key_id": None,
            "roundtrip_verified_at": None,
            "recipient_file": str(recipient_file),
            "identity_exported": False,
            "error": str(exc),
            "protection_limit": _PROTECTION_LIMIT,
        }


def setup_backup_key() -> dict[str, Any]:
    """Create the host-local age identity once; never rotate an existing key."""
    with _key_lock():
        status = get_backup_key_status()
        if status["configured"]:
            if status.get("key_id"):
                return status
            raise BackupKeyUnavailableError(str(status.get("error") or "backup_key_invalid"))
        recipient_file, identity_file, _state_file = _paths()
        identity = _run_age([_age_binary("age-keygen")])
        if _SECRET_PREFIX.encode() not in identity:
            raise BackupKeyUnavailableError("backup_key_generation_failed")
        try:
            _secure_write_new(identity_file, identity)
            recipient = _recipient_for_identity(identity_file)
            _secure_write_new(recipient_file, f"{recipient}\n".encode())
            _write_state(key_id=_key_id(recipient), identity_exported=False, verified_at=None)
        except Exception:
            recipient_file.unlink(missing_ok=True)
            identity_file.unlink(missing_ok=True)
            _state_file.unlink(missing_ok=True)
            raise
        return get_backup_key_status()


def _secret_line(content: str) -> str:
    values = [line.strip() for line in content.splitlines() if line.strip().startswith(_SECRET_PREFIX)]
    if len(values) != 1 or len(values[0]) > 200:
        raise BackupKeyVerificationError("recovery_key_invalid")
    return values[0]


def _identity_recipient_and_roundtrip(identity_file: Path) -> str:
    try:
        recipient = _recipient_for_identity(identity_file)
        challenge = b"summitflow-backup-recovery-check\0" + os.urandom(32)
        ciphertext = _run_age([_age_binary("age"), "-r", recipient], input_bytes=challenge)
        plaintext = _run_age(
            [_age_binary("age"), "-d", "-i", str(identity_file)],
            input_bytes=ciphertext,
        )
    except BackupKeyUnavailableError as exc:
        raise BackupKeyVerificationError("recovery_key_invalid") from exc
    if plaintext != challenge:
        raise BackupKeyVerificationError("recovery_key_roundtrip_failed")
    return recipient


def import_backup_recovery_key(recovery_key: str) -> dict[str, Any]:
    """Install owner-supplied recovery material only when no key exists."""
    secret = _secret_line(recovery_key)
    with _key_lock():
        status = get_backup_key_status()
        if status["configured"]:
            raise BackupKeyUnavailableError("backup_key_already_configured")
        recipient_file, identity_file, _state_file = _paths()
        with tempfile.NamedTemporaryFile(
            mode="w+",
            encoding="utf-8",
            dir=_ensure_private_directory(),
            prefix=".recovery-import-",
            delete=True,
        ) as handle:
            os.fchmod(handle.fileno(), 0o600)
            handle.write(secret + "\n")
            handle.flush()
            recipient = _identity_recipient_and_roundtrip(Path(handle.name))
        key_id = _key_id(recipient)
        verified_at = datetime.now(UTC).isoformat()
        try:
            _secure_write_new(identity_file, f"{secret}\n".encode())
            _secure_write_new(recipient_file, f"{recipient}\n".encode())
            _write_state(
                key_id=key_id,
                identity_exported=True,
                verified_at=verified_at,
            )
        except Exception:
            recipient_file.unlink(missing_ok=True)
            identity_file.unlink(missing_ok=True)
            _state_file.unlink(missing_ok=True)
            raise
        return get_backup_key_status()


def export_backup_recovery_key() -> tuple[str, str]:
    """Return the configured secret identity for an explicitly authorized export."""
    with _key_lock():
        _recipient_file, identity_file, recipient = _configured_identity()
        try:
            recovery_key = _secret_line(identity_file.read_text(encoding="utf-8"))
        except OSError as exc:
            raise BackupKeyUnavailableError("backup_key_invalid") from exc
        state = _read_state()
        key_id = _key_id(recipient)
        _write_state(
            key_id=key_id,
            identity_exported=True,
            verified_at=(
                state.get("roundtrip_verified_at")
                if state.get("key_id") == key_id
                and isinstance(state.get("roundtrip_verified_at"), str)
                else None
            ),
        )
        return key_id, recovery_key


def verify_backup_recovery_key(recovery_key: str) -> dict[str, Any]:
    """Prove that supplied recovery material decrypts a fresh age challenge."""
    secret = _secret_line(recovery_key)
    with _key_lock():
        _recipient_file, _identity_file, recipient = _configured_identity()
        with tempfile.NamedTemporaryFile(
            mode="w+",
            encoding="utf-8",
            dir=_ensure_private_directory(),
            prefix=".recovery-check-",
            delete=True,
        ) as handle:
            os.fchmod(handle.fileno(), 0o600)
            handle.write(secret + "\n")
            handle.flush()
            try:
                supplied_recipient = _recipient_for_identity(Path(handle.name))
            except BackupKeyUnavailableError as exc:
                raise BackupKeyVerificationError("recovery_key_invalid") from exc
            if supplied_recipient != recipient:
                raise BackupKeyVerificationError("recovery_key_does_not_match")
            _identity_recipient_and_roundtrip(Path(handle.name))
        state = _read_state()
        key_id = _key_id(recipient)
        verified_at = datetime.now(UTC).isoformat()
        _write_state(
            key_id=key_id,
            identity_exported=state.get("identity_exported") is True
            and state.get("key_id") == key_id,
            verified_at=verified_at,
        )
        return get_backup_key_status()


def get_backup_key_paths(
    *, require_validated: bool = True
) -> tuple[Path, Path]:
    """Return public recipient and private identity paths for backup workers."""
    recipient_file, identity_file, recipient = _configured_identity()
    if require_validated:
        state = _read_state()
        if state.get("key_id") != _key_id(recipient) or not isinstance(
            state.get("roundtrip_verified_at"), str
        ):
            raise BackupKeyUnavailableError("backup_key_not_verified")
    return recipient_file, identity_file
