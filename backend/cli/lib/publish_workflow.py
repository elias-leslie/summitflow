"""Deliver an existing Git revision without confusing push with verified CI."""
from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .github_publish import GitHub, GitHubError
from .publish_scope import push_scope


class PublishError(RuntimeError):
    """Publication failed before remote delivery."""

    def __init__(self, message: str, *, unavailable: bool = False,
                 reason: str = 'remote_publication_failed'):
        super().__init__(message)
        self.unavailable = unavailable
        self.reason = reason


def _error_evidence(exc: GitHubError | PublishError, sha: str) -> dict[str, Any]:
    return {'state': 'pending' if exc.unavailable else 'unavailable', 'sha': sha,
            'checks': [], 'failure_reason': exc.reason, 'detail': str(exc)}


def github_name(remote: str) -> str | None:
    if remote.startswith('git@github.com:'):
        path = remote.split(':', 1)[1]
    else:
        parsed = urlparse(remote)
        if parsed.hostname != 'github.com':
            return None
        path = parsed.path.lstrip('/')
    path = path.removesuffix('.git').rstrip('/')
    return path if re.fullmatch(r'[\w.-]+/[\w.-]+', path) else None


def evidence_result(evidence: dict[str, Any]) -> dict[str, Any]:
    state = evidence['state']
    complete = state in {'success', 'not_applicable'}
    return {'status': 'SUCCESS' if complete else ('PENDING' if state == 'pending' else 'BLOCKED'),
            'publication_complete': complete, 'ci': evidence,
            'reason': '' if complete else evidence.get('failure_reason', f'remote_ci_{state}'),
            'deployment': {'state': 'not_run'}}


def publish_git(repo: Path, *, sha: str, task_id: str, message: str,
                run_git: Callable[..., Any], push_revision: Callable[[str | None], Any] | None = None,
                remote_name: str = "origin", resume: bool = False,
                destination: str | None = None, reconcile_checkout: bool = True,
                activity_allowed: Callable[[], bool] | None = None) -> dict[str, Any]:
    if activity_allowed is not None and not activity_allowed():
        raise PublishError('Scheduled publication window is closed', unavailable=True,
                           reason='outside_publication_window')
    remote = run_git(repo, ['remote', 'get-url', '--push', remote_name])
    if remote.returncode:
        raise PublishError('Cannot resolve origin push remote')
    name = github_name(remote.stdout.strip())
    client = GitHub(repo, name) if name else None
    if client is not None and activity_allowed is not None:
        client.activity_allowed = activity_allowed
    try:
        plan = client.plan() if client else None
        if destination is not None and plan and destination != plan['base']:
            raise GitHubError('Scheduled destination does not match the remote default branch')
        remote_sha = client.base_sha(plan["base"]) if client and plan else None
        if client and plan and remote_sha is None and plan['requires_pr']:
            raise GitHubError('Empty repository requires a pull request; initialize its default branch under the applicable repository rules first')
        already_remote = bool(client and plan and remote_sha == sha)
        if resume and client and plan and not plan['requires_pr'] and not already_remote:
            comparison = client.api(f'compare/{sha}...{remote_sha}') if remote_sha else {}
            already_remote = comparison.get('status') in {'ahead', 'identical'}
            if not already_remote:
                raise GitHubError('Retained source is no longer on the remote default branch')
    except GitHubError as exc:
        raise PublishError(str(exc), unavailable=exc.unavailable, reason=exc.reason) from exc
    if client and plan and already_remote:
        try:
            client.push_scope = push_scope(repo, name or '', plan['base'], sha)
            evidence = client.observe(sha, [], branch=plan['base'])
            if client.push_scope:
                evidence['push_scope'] = client.push_scope
        except GitHubError as exc:
            evidence = _error_evidence(exc, sha)
        return {'pushed': False, 'sha': sha, 'reason': 'already_on_remote', **evidence_result(evidence)}
    destination_branch: str | None = None
    head = 'st/' + (re.sub(r'[^a-zA-Z0-9_-]', '-', task_id) if task_id else sha[:16])
    try:
        existing_pull = (
            client.source_pull_request(plan['base'], sha)
            if client and plan and plan['requires_pr'] and not already_remote
            else None
        )
    except GitHubError as exc:
        raise PublishError(str(exc), unavailable=exc.unavailable, reason=exc.reason) from exc
    if plan and plan['requires_pr']:
        args = ['push', remote_name, f'{sha}:refs/heads/{head}']
    elif push_revision:
        args = []  # JJ callback supplies its explicit remote and bookmark.
    else:
        current = run_git(repo, ['branch', '--show-current']) if destination is None else None
        if destination is None and (current is None or current.returncode or not current.stdout.strip()):
            raise PublishError('Cannot publish detached Git HEAD without an explicit branch')
        # Inspect and push the same remote; do not let push.default select another destination.
        if destination is None:
            assert current is not None
            destination_branch = current.stdout.strip()
        else:
            destination_branch = destination
        args = ['push', *(['--porcelain'] if client else []), remote_name, f'{sha}:refs/heads/{destination_branch}']
    if existing_pull is not None:
        pushed = None
    elif resume:
        if not client or not plan or not plan['requires_pr']:
            raise PublishError('Cannot resume publication without retained remote delivery')
        pushed = None
    else:
        if activity_allowed is not None and not activity_allowed():
            raise PublishError('Scheduled publication window is closed', unavailable=True,
                               reason='outside_publication_window')
        pushed = push_revision(head if plan and plan['requires_pr'] else None) if push_revision else run_git(repo, args)
        if pushed.returncode:
            raise PublishError(pushed.stderr.strip() or pushed.stdout.strip() or 'git push failed')
    result: dict[str, Any] = {'pushed': not resume and existing_pull is None, 'sha': sha}
    try:
        if client and plan:
            if destination_branch:
                client.push_scope = push_scope(repo, name or '', destination_branch, sha, pushed.stdout or '' if pushed else '')
                if client.push_scope:
                    result['push_scope'] = client.push_scope
            if plan['requires_pr']:
                pull = existing_pull or client.pull_request(head, plan['base'], message, sha)
                publish_branch = pull.get('head', {}).get('ref') if existing_pull else head
                result.update({'pr_url': pull['html_url'], 'publish_branch': publish_branch})
                evidence = client.finish_pr(pull['number'], sha, plan)
                if evidence.get('merge_sha'):
                    result['merge_sha'] = evidence['merge_sha']
                    current = run_git(repo, ['rev-parse', 'HEAD']) if resume and reconcile_checkout else None
                    if not reconcile_checkout:
                        result['local_reconciliation'] = {'state': 'deferred', 'reason': 'isolated_publication'}
                    elif resume and (current is None or current.returncode or current.stdout.strip() != sha):
                        result['local_reconciliation'] = {'state': 'deferred', 'reason': 'later_checkout_work_preserved'}
                    else:
                        result['local_reconciliation'] = reconcile(repo, plan['base'], run_git, remote=remote_name)
            else:
                if destination_branch and destination_branch != plan['base']:
                    evidence = client.observe_feature_branch(sha, plan['required'], destination_branch)
                    if evidence.get('pull_requests'):
                        result['pr_url'] = evidence['pull_requests'][0]['url']
                else:
                    evidence = client.observe(sha, plan['required'], branch=destination_branch)
        else:
            evidence = {'state': 'not_applicable', 'sha': sha, 'checks': [], 'reason': 'non_github_remote'}
    except (GitHubError, PublishError) as exc:
        evidence = _error_evidence(exc, sha)
    return {**result, **evidence_result(evidence)}


def reconcile(repo: Path, base: str, run_git: Callable[..., Any], *, remote: str = "origin") -> dict[str, Any]:
    """Preserve local work and history while returning the base checkout to remote."""
    current = run_git(repo, ['branch', '--show-current'])
    if current.returncode or current.stdout.strip() != base:
        return {'state': 'not_applicable', 'reason': 'not_base_checkout'}
    dirty = run_git(repo, ['status', '--porcelain'])
    if dirty.returncode or dirty.stdout.strip():
        return {'state': 'deferred', 'reason': 'uncommitted_work_preserved'}
    fetched = run_git(repo, ['fetch', remote, base])
    if fetched.returncode:
        return {'state': 'deferred', 'reason': 'fetch_failed', 'detail': fetched.stderr.strip()}
    target = f'{remote}/{base}'
    ancestry = run_git(repo, ['merge-base', '--is-ancestor', 'HEAD', target])
    if ancestry.returncode == 0:
        result = run_git(repo, ['merge', '--ff-only', target])
        return {'state': 'success' if result.returncode == 0 else 'deferred', 'detail': result.stderr.strip()}
    if ancestry.returncode != 1:
        return {'state': 'deferred', 'reason': 'ancestry_unavailable'}
    return {'state': 'deferred', 'reason': 'diverged_history_preserved'}
