"""Backup API client operations."""

from __future__ import annotations

from typing import Any

import httpx

from ..client import APIError


class BackupAPI:
    """API client for backup operations."""

    def __init__(self, base_url: str, project_id: str):
        """Initialize API client.

        Args:
            base_url: Base API URL
            project_id: Project ID
        """
        self.base_url = base_url
        self.project_id = project_id
        self.timeout = 30.0

    def list_backups(self, limit: int = 20, status: str | None = None) -> dict[str, Any]:
        """List backups for the project.

        Args:
            limit: Maximum number of results
            status: Filter by status

        Returns:
            Dict with backups and total count

        Raises:
            APIError: If the request fails
        """
        url = f"{self.base_url}/projects/{self.project_id}/backups?limit={limit}"
        if status:
            url += f"&status={status}"

        response = httpx.get(url, timeout=self.timeout)
        if response.status_code >= 400:
            raise self._make_error(response)
        return response.json()

    def create_backup(self, note: str | None = None, keep_local: bool = False) -> dict[str, Any]:
        """Create a new backup.

        Args:
            note: Optional backup note
            keep_local: Whether to keep local copy

        Returns:
            Dict with task_id and backup info

        Raises:
            APIError: If the request fails
        """
        url = f"{self.base_url}/projects/{self.project_id}/backups"
        data = {"note": note, "keep_local": keep_local}
        response = httpx.post(url, json=data, timeout=self.timeout)
        if response.status_code >= 400:
            raise self._make_error(response)
        return response.json()

    def get_backup(self, backup_id: str) -> dict[str, Any]:
        """Get backup details.

        Args:
            backup_id: Backup ID

        Returns:
            Backup data

        Raises:
            APIError: If the request fails
        """
        url = f"{self.base_url}/projects/{self.project_id}/backups/{backup_id}"
        response = httpx.get(url, timeout=self.timeout)
        if response.status_code >= 400:
            raise self._make_error(response)
        return response.json()

    def restore_backup(self, backup_id: str, dry_run: bool = False) -> dict[str, Any]:
        """Restore from a backup.

        Args:
            backup_id: Backup ID to restore
            dry_run: Preview without restoring

        Returns:
            Dict with task_id

        Raises:
            APIError: If the request fails
        """
        url = f"{self.base_url}/projects/{self.project_id}/backups/{backup_id}/restore"
        response = httpx.post(url, json={"dry_run": dry_run}, timeout=self.timeout)
        if response.status_code >= 400:
            raise self._make_error(response)
        return response.json()

    def delete_backup(self, backup_id: str) -> dict[str, Any]:
        """Delete a backup.

        Args:
            backup_id: Backup ID to delete

        Returns:
            Confirmation dict

        Raises:
            APIError: If the request fails
        """
        url = f"{self.base_url}/projects/{self.project_id}/backups/{backup_id}"
        response = httpx.delete(url, timeout=self.timeout)
        if response.status_code >= 400:
            raise self._make_error(response)
        return response.json()

    def get_schedule(self) -> dict[str, Any] | None:
        """Get backup schedule.

        Returns:
            Schedule data or None if not configured

        Raises:
            APIError: If the request fails
        """
        url = f"{self.base_url}/projects/{self.project_id}/backups/schedule"
        response = httpx.get(url, timeout=self.timeout)
        if response.status_code == 404 or response.text == "null":
            return None
        if response.status_code >= 400:
            raise self._make_error(response)
        return response.json()

    def update_schedule(
        self,
        enabled: bool | None = None,
        frequency: str | None = None,
        retention_days: int | None = None,
    ) -> dict[str, Any]:
        """Update backup schedule.

        Args:
            enabled: Enable or disable schedule
            frequency: Backup frequency (daily, weekly, monthly)
            retention_days: Days to retain backups

        Returns:
            Updated schedule data

        Raises:
            APIError: If the request fails
        """
        # Get current schedule to preserve values
        current = self.get_schedule() or {}

        data = {
            "enabled": enabled if enabled is not None else current.get("enabled", False),
            "frequency": frequency if frequency else current.get("frequency", "daily"),
            "retention_days": retention_days if retention_days is not None else current.get("retention_days", 14),
        }

        url = f"{self.base_url}/projects/{self.project_id}/backups/schedule"
        response = httpx.put(url, json=data, timeout=self.timeout)
        if response.status_code >= 400:
            raise self._make_error(response)
        return response.json()

    def _make_error(self, response: httpx.Response) -> APIError:
        """Create APIError from response.

        Args:
            response: HTTP response

        Returns:
            APIError instance
        """
        try:
            detail = response.json().get("detail", response.text)
        except Exception:
            detail = response.text
        return APIError(response.status_code, detail)
