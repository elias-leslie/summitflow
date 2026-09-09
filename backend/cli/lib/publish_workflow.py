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
            'reason': '' if complete else f'remote_ci_{state}',
            'deployment': {'state': 'not_run'}}


def publish_git(repo: Path, *, sha: str, task_id: str, message: str,
                run_git: Callable[..., Any], push_revision: Callable[[str | None], Any] | None = None,
                remote_name: str = "origin") -> dict[str, Any]:
    remote = run_git(repo, ['remote', 'get-url', '--push', remote_name])
    if remote.returncode:
        raise PublishError('Cannot resolve origin push remote')
    name = github_name(remote.stdout.strip())
    client = GitHub(repo, name) if name else None
    try:
        plan = client.plan() if client else None
        remote_sha = client.base_sha(plan["base"]) if client and plan else None
        if client and plan and remote_sha is None and plan['requires_pr']:
            raise GitHubError('Empty repository requires a pull request; initialize its default branch under the applicable repository rules first')
        already_remote = bool(client and plan and remote_sha == sha)
    except GitHubError as exc:
        raise PublishError(str(exc)) from exc
    if client and plan and already_remote:
        try:
            client.push_scope = push_scope(repo, name or '', plan['base'], sha)
            evidence = client.observe(sha, [], branch=plan['base'])
            if client.push_scope:
                evidence['push_scope'] = client.push_scope
        except GitHubError as exc:
            evidence = {'state': 'unavailable', 'sha': sha, 'checks': [], 'detail': str(exc)}
        return {'pushed': False, 'sha': sha, 'reason': 'already_on_remote', **evidence_result(evidence)}
    destination_branch: str | None = None
    head = 'st/' + (re.sub(r'[^a-zA-Z0-9_-]', '-', task_id) if task_id else sha[:16])
    if plan and plan['requires_pr']:
        args = ['push', remote_name, f'{sha}:refs/heads/{head}']
    elif push_revision:
        args = []  # JJ callback supplies its explicit remote and bookmark.
    else:
        current = run_git(repo, ['branch', '--show-current'])
        if current.returncode or not current.stdout.strip():
            raise PublishError('Cannot publish detached Git HEAD without an explicit branch')
        # Inspect and push the same remote; do not let push.default select another destination.
        destination_branch = current.stdout.strip()
        args = ['push', *(['--porcelain'] if client else []), remote_name, f'{sha}:refs/heads/{destination_branch}']
    pushed = push_revision(head if plan and plan['requires_pr'] else None) if push_revision else run_git(repo, args)
    if pushed.returncode:
        raise PublishError(pushed.stderr.strip() or pushed.stdout.strip() or 'git push failed')
    result: dict[str, Any] = {'pushed': True, 'sha': sha}
    try:
        if client and plan:
            if destination_branch:
                client.push_scope = push_scope(repo, name or '', destination_branch, sha, pushed.stdout or '')
                if client.push_scope:
                    result['push_scope'] = client.push_scope
            if plan['requires_pr']:
                pull = client.pull_request(head, plan['base'], message, sha)
                result.update({'pr_url': pull['html_url'], 'publish_branch': head})
                evidence = client.finish_pr(pull['number'], sha, plan)
                if evidence.get('merge_sha'):
                    result['merge_sha'] = evidence['merge_sha']
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
        evidence = {'state': 'unavailable', 'sha': sha, 'checks': [], 'detail': str(exc)}
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
    # Squash/rebase changes commit identities. Retain old main under a local ref;
    # never reset, force-update, or discard the user's original commits.
    sha = run_git(repo, ['rev-parse', 'HEAD']).stdout.strip()
    if not sha:
        return {'state': 'deferred', 'reason': 'local_revision_unavailable'}
    preserved = f'st-preserved/{sha[:16]}'
    exists = run_git(repo, ['show-ref', '--verify', '--quiet', f'refs/heads/{preserved}'])
    if exists.returncode != 1:
        return {'state': 'deferred', 'reason': 'preservation_ref_already_exists', 'preserved_branch': preserved}
    renamed = run_git(repo, ['branch', '-m', preserved])
    if renamed.returncode:
        return {'state': 'deferred', 'reason': 'preservation_failed', 'detail': renamed.stderr.strip()}
    switched = run_git(repo, ['switch', '-c', base, '--track', target])
    return {'state': 'success' if switched.returncode == 0 else 'deferred',
            'preserved_branch': preserved, 'detail': switched.stderr.strip()}
