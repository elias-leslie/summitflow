"""Backup API client operations."""

from __future__ import annotations

from typing import Any, cast

import httpx

from ..client import APIError

_DEFAULT_TIMEOUT = 30.0


def _make_api_error(response: httpx.Response) -> APIError:
    """Create APIError from an HTTP response."""
    try:
        detail = response.json().get("detail", response.text)
    except Exception:
        detail = response.text
    return APIError(response.status_code, detail)


class BackupProjectAPI:
    """API client for project-level backup operations."""

    def __init__(self, base_url: str, project_id: str) -> None:
        self.base_url = base_url
        self.project_id = project_id
        self.timeout = _DEFAULT_TIMEOUT

    def list_backups(self, limit: int = 20, status: str | None = None) -> dict[str, Any]:
        """List backups for the project."""
        url = f"{self.base_url}/projects/{self.project_id}/backups?limit={limit}"
        if status:
            url += f"&status={status}"
        response = httpx.get(url, timeout=self.timeout)
        if response.status_code >= 400:
            raise _make_api_error(response)
        return cast(dict[str, Any], response.json())

    def create_backup(self, note: str | None = None, keep_local: bool = False) -> dict[str, Any]:
        """Create a new backup."""
        url = f"{self.base_url}/projects/{self.project_id}/backups"
        data = {"note": note, "keep_local": keep_local}
        response = httpx.post(url, json=data, timeout=self.timeout)
        if response.status_code >= 400:
            raise _make_api_error(response)
        return cast(dict[str, Any], response.json())

    def get_backup(self, backup_id: str) -> dict[str, Any]:
        """Get backup details."""
        url = f"{self.base_url}/projects/{self.project_id}/backups/{backup_id}"
        response = httpx.get(url, timeout=self.timeout)
        if response.status_code >= 400:
            raise _make_api_error(response)
        return cast(dict[str, Any], response.json())

    def restore_backup(self, backup_id: str, dry_run: bool = False) -> dict[str, Any]:
        """Restore from a backup."""
        url = f"{self.base_url}/projects/{self.project_id}/backups/{backup_id}/restore"
        response = httpx.post(url, json={"dry_run": dry_run}, timeout=self.timeout)
        if response.status_code >= 400:
            raise _make_api_error(response)
        return cast(dict[str, Any], response.json())

    def delete_backup(self, backup_id: str) -> dict[str, Any]:
        """Delete a backup."""
        url = f"{self.base_url}/projects/{self.project_id}/backups/{backup_id}"
        response = httpx.delete(url, timeout=self.timeout)
        if response.status_code >= 400:
            raise _make_api_error(response)
        return cast(dict[str, Any], response.json())


class BackupSourceAPI:
    """API client for backup-source-level operations."""

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url
        self.timeout = _DEFAULT_TIMEOUT

    def list_sources(self, source_type: str | None = None) -> list[dict[str, Any]]:
        """List all backup sources."""
        url = f"{self.base_url}/backup-sources"
        if source_type:
            url += f"?source_type={source_type}"
        response = httpx.get(url, timeout=self.timeout)
        if response.status_code >= 400:
            raise _make_api_error(response)
        return cast(list[dict[str, Any]], response.json())

    def get_source(self, source_id: str) -> dict[str, Any]:
        """Get a backup source by ID."""
        url = f"{self.base_url}/backup-sources/{source_id}"
        response = httpx.get(url, timeout=self.timeout)
        if response.status_code >= 400:
            raise _make_api_error(response)
        return cast(dict[str, Any], response.json())

    def update_source(
        self,
        source_id: str,
        enabled: bool | None = None,
        frequency: str | None = None,
        retention_days: int | None = None,
    ) -> dict[str, Any]:
        """Update a backup source."""
        data: dict[str, Any] = {}
        if enabled is not None:
            data["enabled"] = enabled
        if frequency is not None:
            data["frequency"] = frequency
        if retention_days is not None:
            data["retention_days"] = retention_days
        url = f"{self.base_url}/backup-sources/{source_id}"
        response = httpx.put(url, json=data, timeout=self.timeout)
        if response.status_code >= 400:
            raise _make_api_error(response)
        return cast(dict[str, Any], response.json())

    def create_source_backup(
        self, source_id: str, note: str | None = None, keep_local: bool = False
    ) -> dict[str, Any]:
        """Create a backup for a specific source."""
        url = f"{self.base_url}/backup-sources/{source_id}/backups"
        data = {"note": note, "keep_local": keep_local}
        response = httpx.post(url, json=data, timeout=self.timeout)
        if response.status_code >= 400:
            raise _make_api_error(response)
        return cast(dict[str, Any], response.json())

    def restore_source_backup(
        self, source_id: str, backup_id: str, dry_run: bool = False
    ) -> dict[str, Any]:
        """Restore a backup via source endpoint."""
        url = f"{self.base_url}/backup-sources/{source_id}/backups/{backup_id}/restore"
        response = httpx.post(url, json={"dry_run": dry_run}, timeout=self.timeout)
        if response.status_code >= 400:
            raise _make_api_error(response)
        return cast(dict[str, Any], response.json())

    def list_source_backups(
        self, source_id: str, limit: int = 20, status: str | None = None
    ) -> dict[str, Any]:
        """List backups for a specific source."""
        url = f"{self.base_url}/backup-sources/{source_id}/backups?limit={limit}"
        if status:
            url += f"&status={status}"
        response = httpx.get(url, timeout=self.timeout)
        if response.status_code >= 400:
            raise _make_api_error(response)
        return cast(dict[str, Any], response.json())


# BackupAPI preserved as an alias for backward-compatibility; prefer BackupProjectAPI directly.
BackupAPI = BackupProjectAPI


class BackupSystemImageAPI:
    """API client for host system-image backup operations."""

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url
        self.timeout = _DEFAULT_TIMEOUT

    def status(self) -> dict[str, Any]:
        """Return Veeam system-image backup status."""
        response = httpx.get(f"{self.base_url}/backups/system-image", timeout=self.timeout)
        if response.status_code >= 400:
            raise _make_api_error(response)
        return cast(dict[str, Any], response.json())

    def start(self) -> dict[str, Any]:
        """Start the configured Veeam system-image backup job."""
        response = httpx.post(f"{self.base_url}/backups/system-image/start", timeout=self.timeout)
        if response.status_code >= 400:
            raise _make_api_error(response)
        return cast(dict[str, Any], response.json())

    def stop(self) -> dict[str, Any]:
        """Stop the active Veeam system-image backup session."""
        response = httpx.post(f"{self.base_url}/backups/system-image/stop", timeout=self.timeout)
        if response.status_code >= 400:
            raise _make_api_error(response)
        return cast(dict[str, Any], response.json())
