"""The read-only GitHub adapter classifies outages from the HTTP envelope, never diagnostics."""
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest

from cli.lib.github_publish import GitHub, GitHubError


@pytest.mark.parametrize('status,headers,unavailable,reason', [
    (401, '', True, 'remote_authentication_unavailable'),
    (403, '', True, 'remote_authentication_unavailable'),
    (403, 'X-RateLimit-Remaining: 0\r\n', True, 'remote_rate_limited'),
    (403, 'Retry-After: 60\r\n', True, 'remote_rate_limited'),
    (404, '', True, 'remote_api_unavailable'),
    (429, '', True, 'remote_rate_limited'),
    (503, '', True, 'remote_api_unavailable'),
    (422, '', False, 'remote_publication_failed'),
])
def test_api_outages_use_http_envelope_not_diagnostics(monkeypatch, status, headers, unavailable, reason):
    from cli.lib import github_publish
    output = f'HTTP/2.0 {status} Response\r\n{headers}\r\n{{"message":"fixture-private-diagnostic"}}'
    monkeypatch.setattr(github_publish.subprocess, 'run', Mock(return_value=subprocess.CompletedProcess([], 1, output, 'fixture-secret-token')))
    with pytest.raises(GitHubError) as exc:
        GitHub(Path('/repo'), 'owner/repo').api('')
    assert exc.value.unavailable is unavailable
    assert exc.value.reason == reason and exc.value.status_code == status
    assert 'fixture' not in str(exc.value)


@pytest.mark.parametrize('code,reason', [(1, 'remote_api_unavailable'), (4, 'remote_authentication_unavailable')])
def test_cli_failure_without_http_response_is_unknown_not_source_failure(monkeypatch, code, reason):
    from cli.lib import github_publish
    monkeypatch.setattr(github_publish.subprocess, 'run', Mock(return_value=subprocess.CompletedProcess([], code, '', 'do not interpret this diagnostic')))
    with pytest.raises(GitHubError) as exc:
        GitHub(Path('/repo'), 'owner/repo').api('')
    assert exc.value.unavailable and exc.value.reason == reason


def test_success_parses_included_headers_and_reads_only(monkeypatch):
    from cli.lib import github_publish
    runner = Mock(return_value=subprocess.CompletedProcess([], 0, 'HTTP/2.0 200 OK\nX-Request: fixture\n\n{"default_branch":"main"}', ''))
    monkeypatch.setattr(github_publish.subprocess, 'run', runner)
    assert GitHub(Path('/repo'), 'owner/repo').api('') == {'default_branch': 'main'}
    command = runner.call_args.args[0]
    assert '--include' in command and command[command.index('--method') + 1] == 'GET'


def test_pages_refuse_silent_truncation(monkeypatch):
    client = GitHub(Path('/repo'), 'owner/repo')
    monkeypatch.setattr(client, 'api', Mock(side_effect=lambda path: [{}] * 100 if 'page=1&' in path or path.endswith('page=1') else [{}]))
    assert len(client.pages('code-scanning/alerts?state=open')) == 101
    monkeypatch.setattr(client, 'api', Mock(return_value=[{}] * 100))
    with pytest.raises(GitHubError, match='pagination limit'):
        client.pages('code-scanning/alerts')
