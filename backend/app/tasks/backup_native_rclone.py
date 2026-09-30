"""Native ciphertext transfer using the existing private Google Drive remote."""

from __future__ import annotations

import configparser
import hashlib
import json
import os
import re
import stat
from collections.abc import Callable, Collection, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .backup_activity import check_backup_cancelled, run_bulk_process

_ID = re.compile(r"[A-Za-z0-9_-]+")
_REMOTE = re.compile(r"[A-Za-z0-9_-]+:(.+)")
_HASHES = (("sha256", 64), ("sha1", 40), ("md5", 32))


class NativeRcloneProvider:
    """Fail closed on ambiguous objects, credentials, or absent provider hashes."""

    def __init__(self, env: Mapping[str, str]) -> None:
        self.root = env.get("BACKUP_OFFSITE_RCLONE_REMOTE", "").strip()
        match = _REMOTE.fullmatch(self.root)
        if not match or any(part in {"", ".", ".."} for part in match[1].split("/")):
            raise RuntimeError("Native rclone offsite requires a dedicated remote folder")
        expiry = env.get("BACKUP_OFFSITE_RCLONE_PERMANENT_EXPIRY", "false").lower()
        if expiry not in {"true", "false"}:
            raise RuntimeError("Native Drive permanent expiry must be a boolean")
        self.permanent_expiry = expiry == "true"
        self.root_id = env.get("BACKUP_OFFSITE_RCLONE_ROOT_ID", "").strip()
        if self.root_id and not _ID.fullmatch(self.root_id):
            raise RuntimeError("Native Drive root identity is invalid")
        if self.permanent_expiry and not self.root_id:
            raise RuntimeError("Permanent expiry requires an approved Drive root identity")
        raw_config = env.get("BACKUP_OFFSITE_RCLONE_CONFIG", "")
        self.config = Path(raw_config)
        if not raw_config or not self.config.is_absolute():
            raise RuntimeError("Native rclone offsite requires an absolute private config reference")
        # Reuse the same credential protection as the established authorization
        # script: no symlink components, private parent, private user-owned file.
        if any(path.is_symlink() for path in (self.config, *self.config.parents)):
            raise RuntimeError("Native rclone config must not traverse symbolic links")
        metadata = self.config.stat()
        parent = self.config.parent.stat()
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.getuid()
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or parent.st_uid != os.getuid()
            or stat.S_IMODE(parent.st_mode) != 0o700
        ):
            raise RuntimeError("Native rclone config requires a private user-owned file and directory")
        # Only the dedicated configured Drive remote is valid. Never return or
        # log the configuration, which contains OAuth credentials.
        settings = configparser.ConfigParser(interpolation=None)
        try:
            settings.read(self.config)
        except (configparser.Error, UnicodeError):
            raise RuntimeError("Native rclone private config is invalid") from None
        remote_name = self.root.split(":", 1)[0]
        if not settings.has_section(remote_name) or settings.get(remote_name, "type", fallback="") != "drive":
            raise RuntimeError("Native rclone offsite requires a configured Google Drive remote")

    def _run(self, *args: str, phase: str = "verification") -> Any:
        check_backup_cancelled()
        # Inherited inline tokens and backend options can override the approved
        # credential file; retain neither tool's namespace.
        env = {key: value for key, value in os.environ.items() if not key.startswith(("RCLONE_", "RESTIC_"))}
        env["LC_ALL"] = "C"
        result = run_bulk_process(
            ["rclone", *args, "--config", str(self.config)], env=env,
            phase=phase, object_name="Native Drive archive", attention_after=600,
        )
        if result.returncode:
            # Provider diagnostics can contain OAuth material. Keep them out of
            # durable backup records and the agent transcript.
            raise RuntimeError(f"rclone {phase} failed (exit {result.returncode}); inspect private operator diagnostics")
        return result

    def _json(self, *args: str) -> Any:
        try:
            return json.loads(self._run(*args).stdout)
        except (ValueError, TypeError) as exc:
            raise RuntimeError("Native rclone returned invalid provider metadata") from exc

    def ensure_folder(self, source_id: str) -> str:
        folder = f"{self.root}/{source_id}"
        # Resolve/validate the root before any mutation. A deleted or mistyped
        # root must not silently create another backup destination.
        root = self.probe()
        existing = self._directory_entry(self.root, source_id)
        if existing is None:
            self._run("mkdir", folder, phase="upload")
        metadata = self._directory_entry(self.root, source_id)
        if metadata is None:
            raise RuntimeError("Native Drive source folder was not discoverable")
        if existing and metadata["ID"] != existing["ID"]:
            raise RuntimeError("Native Drive source folder identity changed")
        if self.probe()["provider_id"] != root["provider_id"]:
            raise RuntimeError("Native Drive destination folder identity changed")
        return folder

    def probe(self) -> dict[str, Any]:
        """Read only the existing root; never create a probe file or folder."""
        # lsjson --stat describes the virtual Fs root for a directory target:
        # Path/Name can be empty, Size=-1, and ID absent. Resolve real directory
        # identities through their unique exact-name entries in parent lists.
        # Walk every component so an ambiguous ancestor cannot hide a duplicate
        # destination behind rclone's directory-path resolution.
        remote, relative = self.root.split(":", 1)
        parent = remote + ":"
        root: dict[str, Any] | None = None
        for name in relative.split("/"):
            root = self._directory_entry(parent, name)
            if root is None:
                raise RuntimeError("Native Drive destination directory is missing")
            parent = f"{parent}{name}" if parent == remote + ":" else f"{parent}/{name}"
        if root is None:
            raise RuntimeError("Native Drive destination directory is missing")
        if self.root_id and root["ID"] != self.root_id:
            raise RuntimeError("Native Drive destination differs from its approved identity")
        return {"reachable": True, "provider_id": root["ID"], "remote_path": self.root}

    def _directory_entry(self, parent: str, name: str) -> dict[str, Any] | None:
        directories = self._json("lsjson", parent, "--dirs-only")
        if not isinstance(directories, list):
            raise RuntimeError("Native Drive directory inventory is invalid")
        matches = [entry for entry in directories if isinstance(entry, dict) and entry.get("Name") == name]
        if len(matches) > 1:
            raise RuntimeError("Native Drive directory identity is ambiguous")
        if not matches:
            return None
        self._validate_identity(matches[0], directory=True)
        return matches[0]

    @staticmethod
    def _validate_identity(metadata: Any, *, directory: bool = False) -> None:
        if (
            not isinstance(metadata, dict)
            or metadata.get("IsDir") is not directory
            or not isinstance(metadata.get("ID"), str)
            or not _ID.fullmatch(metadata["ID"])
        ):
            raise RuntimeError("Native Drive object identity is missing or ambiguous")

    def children(self, folder: str) -> list[dict[str, Any]]:
        entries = self._json("lsjson", folder, "--files-only")
        if not isinstance(entries, list):
            raise RuntimeError("Native Drive folder inventory is invalid")
        seen: set[str] = set()
        for entry in entries:
            self._validate_identity(entry)
            name = entry.get("Name")
            if not isinstance(name, str) or not name or name in seen or "/" in name:
                raise RuntimeError("Native Drive folder contains ambiguous display names")
            seen.add(name)
        return entries

    def find(self, folder: str, name: str) -> dict[str, Any] | None:
        return next((entry for entry in self.children(folder) if entry["Name"] == name), None)

    def _stat(self, target: str, provider_id: str) -> dict[str, Any]:
        metadata = self._json(
            "lsjson", target, "--stat", "--files-only",
            "--hash-type", "SHA-256", "--hash-type", "SHA-1", "--hash-type", "MD5",
        )
        self._validate_identity(metadata)
        if metadata["ID"] != provider_id:
            raise RuntimeError("Native Drive object identity changed during verification")
        if type(metadata.get("Size")) is not int or metadata["Size"] < 0:
            raise RuntimeError("Native Drive object size is invalid")
        return metadata

    @staticmethod
    def _provider_hash(metadata: dict[str, Any]) -> tuple[str, str]:
        raw_hashes = metadata.get("Hashes")
        if not isinstance(raw_hashes, dict):
            raise RuntimeError("Fresh Native Drive provider checksum is unavailable")
        hashes = {str(key).lower().replace("-", ""): value for key, value in raw_hashes.items()}
        for algorithm, length in _HASHES:
            value = hashes.get(algorithm)
            if value:
                if not isinstance(value, str) or not re.fullmatch(f"[0-9a-fA-F]{{{length}}}", value):
                    raise RuntimeError("Fresh Native Drive provider checksum is invalid")
                return algorithm, value.lower()
        raise RuntimeError("Fresh Native Drive provider checksum is unavailable")

    def _matches(self, path: Path, target: str, entry: dict[str, Any], expected: str) -> tuple[bool, dict[str, Any]]:
        metadata = self._stat(target, entry["ID"])
        algorithm, observed = self._provider_hash(metadata)
        if algorithm == "sha256":
            expected_hash = expected.removeprefix("sha256:")
        else:
            # Available Drive hashes still avoid a remote payload download.
            # Bind their local digest to the recorded ciphertext SHA-256 in
            # this same read, so a changed local file cannot be accepted.
            sha256 = hashlib.sha256()
            digest = hashlib.new(algorithm, usedforsecurity=False)
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    check_backup_cancelled()
                    sha256.update(chunk)
                    digest.update(chunk)
            if "sha256:" + sha256.hexdigest() != expected:
                raise RuntimeError("Local archive changed while verifying Native Drive object")
            expected_hash = digest.hexdigest()
            after = self._stat(target, entry["ID"])
            if after["Size"] != metadata["Size"] or self._provider_hash(after) != (algorithm, observed):
                raise RuntimeError("Native Drive object changed during verification")
        evidence = {
            "provider_id": metadata["ID"], "remote_path": target,
            "provider_checksum": f"{algorithm}:{observed}",
            "verification_method": f"provider-{algorithm}",
        }
        return metadata["Size"] == path.stat().st_size and observed == expected_hash, evidence

    def remove(self, folder: str, entry: dict[str, Any], *, permanent: bool = False) -> None:
        if permanent:
            # Only the retention caller opts in. Repair/replacement continues
            # using trash, even when permanent expiry is enabled.
            source = folder.removeprefix(self.root + "/")
            if (
                not self.permanent_expiry or folder == source or source in {".", ".."}
                or not re.fullmatch(r"[A-Za-z0-9._-]+", source)
            ):
                raise RuntimeError("Permanent expiry is outside the approved Drive source folder")
            self.probe()  # Recheck the pinned root before irreversible deletion.
        current = self.find(folder, entry["Name"])
        if not current or current["ID"] != entry["ID"]:
            raise RuntimeError("Native Drive object identity changed before removal")
        self._run("deletefile", f"{folder}/{entry['Name']}",
                  f"--drive-use-trash={str(not permanent).lower()}", phase="retention")

    def publish(
        self, local_path: Path, *, folder_uri: str, remote_name: str,
        expected_checksum: str, verification_path: Path, retry: bool,
        before_replace: Callable[[], None] | None = None,
    ) -> dict[str, Any]:
        del verification_path  # Provider hashes require no verification download.
        target = f"{folder_uri}/{remote_name}"
        entry = self.find(folder_uri, remote_name)
        uploaded_bytes = 0
        preexisting = entry is not None
        if entry:
            matches, evidence = self._matches(local_path, target, entry, expected_checksum)
            if matches:
                return {"location": f"gdrive://{entry['ID']}", "uploaded_bytes": 0,
                        "downloaded_bytes": 0, "reused": True, **evidence}
            if not retry:
                raise RuntimeError("Offsite verification checksum mismatch")
            if before_replace:
                before_replace()
            self.remove(folder_uri, entry)
        elif before_replace:
            before_replace()
        # Do not let copyto silently reuse an object based only on modtime/size.
        # A same-name concurrent appearance is also not permission to overwrite.
        if self.find(folder_uri, remote_name):
            raise RuntimeError("Native Drive object appeared before upload")
        self._run("copyto", str(local_path), target, "--immutable", phase="upload")
        uploaded_bytes = local_path.stat().st_size
        entry = self.find(folder_uri, remote_name)
        if not entry:
            raise RuntimeError("Uploaded Native Drive object id could not be resolved")
        matches, evidence = self._matches(local_path, target, entry, expected_checksum)
        if not matches:
            raise RuntimeError("Offsite verification checksum mismatch")
        return {"location": f"gdrive://{entry['ID']}", "uploaded_bytes": uploaded_bytes,
                "downloaded_bytes": 0, "reused": preexisting, **evidence}

    def retention(
        self, folder: str, retention_days: int, preserve_uri: str,
        timestamp_pattern: re.Pattern[str], pending_archive_names: Collection[str] = (),
    ) -> list[str]:
        cutoff = datetime.now(UTC) - timedelta(days=retention_days)
        groups: dict[str, tuple[datetime, list[dict[str, Any]]]] = {}
        complete: dict[str, datetime] = {}
        for entry in self.children(folder):
            match = timestamp_pattern.fullmatch(entry["Name"])
            if not match:
                continue
            try:
                created = datetime.strptime(match["timestamp"], "%Y%m%d-%H%M%S").replace(tzinfo=UTC)
            except ValueError:
                continue
            groups.setdefault(match["archive"], (created, []))[1].append(entry)
            if match["suffix"] in {None, ".parts.json"} and match["archive"] not in pending_archive_names:
                complete[match["archive"]] = created
        if not complete:
            return []
        retained = set(sorted(complete, key=lambda name: (complete[name], name), reverse=True)[:3])
        deleted: list[str] = []
        for archive_name, (created, targets) in groups.items():
            if (
                created >= cutoff or archive_name in retained or archive_name in pending_archive_names
                or any(f"gdrive://{entry['ID']}" == preserve_uri for entry in targets)
            ):
                continue
            # Completion first, then parts, matching the native GIO contract.
            for entry in sorted(targets, key=lambda item: not item["Name"].endswith(".parts.json")):
                self.remove(folder, entry, permanent=self.permanent_expiry)
                deleted.append(f"gdrive://{entry['ID']}")
        return deleted


def probe_rclone_destination(env: Mapping[str, str]) -> dict[str, Any]:
    """Validate credential references and read existing destination metadata."""
    return NativeRcloneProvider(env).probe()
