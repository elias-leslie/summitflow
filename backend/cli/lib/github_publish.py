"""Small read-only GitHub REST adapter (repository metadata, code scanning)."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any


class GitHubError(RuntimeError):
    """GitHub could not answer a request safely."""

    def __init__(self, message: str, *, unavailable: bool = False,
                 reason: str = 'remote_publication_failed', status_code: int | None = None,
                 response_message: str | None = None, request_path: str | None = None):
        super().__init__(message)
        self.unavailable = unavailable
        self.reason = reason
        self.status_code = status_code
        self.response_message = response_message
        self.request_path = request_path


def _response(output: str) -> tuple[int | None, dict[str, str], str]:
    """Read gh --include's structured HTTP envelope, never stderr diagnostics."""
    if not output.startswith('HTTP/'):
        return None, {}, output
    envelope, separator, body = output.replace('\r\n', '\n').partition('\n\n')
    try:
        code = int(envelope.splitlines()[0].split()[1])
        headers = {key.lower(): value.strip() for key, value in (
            line.split(':', 1) for line in envelope.splitlines()[1:] if ':' in line)}
    except (ValueError, IndexError) as exc:
        raise GitHubError('GitHub HTTP envelope is unreadable', unavailable=True,
                          reason='remote_api_unavailable') from exc
    if not separator:
        raise GitHubError('GitHub HTTP envelope is incomplete', unavailable=True,
                          reason='remote_api_unavailable')
    return code, headers, body


class GitHub:
    def __init__(self, repo: Path, name: str):
        self.repo = repo
        self.name = name

    def api(self, path: str) -> Any:
        args = ['gh', 'api', f'repos/{self.name}/{path}' if path else f'repos/{self.name}', '--method', 'GET', '--include']
        try:
            result = subprocess.run(args, cwd=self.repo, capture_output=True, text=True, check=False, timeout=60)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise GitHubError('GitHub request unavailable', unavailable=True,
                              reason='remote_api_unavailable') from exc
        status, headers, body_text = _response(result.stdout)
        if result.returncode or (status is not None and status >= 400):
            try:
                body_data = json.loads(body_text)
            except ValueError:
                body_data = {}
            message = body_data.get('message') if isinstance(body_data, dict) else None
            unavailable = status is None or status in {401, 403, 404, 429} or status >= 500
            rate_limited = status == 429 or (status == 403 and (
                headers.get('x-ratelimit-remaining') == '0' or 'retry-after' in headers))
            unavailable = unavailable or rate_limited
            reason = ('remote_rate_limited' if rate_limited else
                      'remote_authentication_unavailable' if status in {401, 403} or (status is None and result.returncode == 4) else
                      'remote_api_unavailable' if unavailable else 'remote_publication_failed')
            raise GitHubError('GitHub request unavailable' if unavailable else 'GitHub request rejected',
                              unavailable=unavailable, reason=reason, status_code=status, response_message=message,
                              request_path=path)
        try:
            return json.loads(body_text)
        except ValueError as exc:
            raise GitHubError('GitHub returned unreadable JSON', unavailable=True,
                              reason='remote_api_unavailable') from exc

    def pages(self, path: str, key: str | None = None) -> list[dict[str, Any]]:
        rows = []
        # GitHub lists are intrinsically paginated; refuse silent truncation.
        for page in range(1, 101):
            data = self.api(f'{path}{"&" if "?" in path else "?"}per_page=100&page={page}')
            batch = data[key] if key else data
            rows.extend(batch)
            if len(batch) < 100:
                return rows
        raise GitHubError(f'GitHub pagination limit reached for {path}')
