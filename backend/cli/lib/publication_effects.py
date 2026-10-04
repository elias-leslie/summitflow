"""Selected-source workflow effects that need explicit publication authority."""
from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml

from .workflow_filters import document_applies

_COMMAND = re.compile(r"(?:^|[\s;/])(?:ssh|scp|rsync|kubectl|helm|terraform|ansible-playbook|vercel|netlify|flyctl|wrangler|gcloud|az)(?:\s|$)|(?:^|[\s/])(?:deploy|publish|release)[\w.-]*\.(?:sh|py|js)\b|\b(?:npm|pnpm|yarn)\s+publish\b", re.MULTILINE)


def workflow_effects(repo: Path, sha: str, branch: str, *, git: Callable[..., Any],
                     push_branches: tuple[str, ...] = (),
                     events: tuple[str, ...] = ('push', 'pull_request', 'pull_request_target', 'workflow_run')) -> dict[str, list[str]]:
    """Read committed YAML; exclude dispatch/tag-only workflows, never execute it.

    Environments, publishing actions, explicit deployment commands, and reusable
    workflow calls carry effects or unknown delegated effects. This inspection
    does not claim to prove arbitrary shell scripts free of side effects.
    """
    listed = git(repo, 'ls-tree', '-r', '--name-only', sha, '--', '.github/workflows')
    if listed.returncode:
        raise ValueError('Committed workflow effects could not be inspected')
    result: dict[str, list[str]] = {}
    for path in listed.stdout.splitlines():
        if not re.fullmatch(r'\.github/workflows/[^/]+\.ya?ml', path):
            continue
        content = git(repo, 'show', sha + ':' + path)
        if content.returncode:
            raise ValueError('Committed workflow effects could not be inspected')
        try:
            document = yaml.safe_load(content.stdout)
        except yaml.YAMLError as exc:
            raise ValueError('Committed workflow effects could not be inspected') from exc
        if not isinstance(document, dict):
            raise ValueError('Committed workflow effects could not be inspected')
        if not any(document_applies(document, event=event, branch=target)
                   for event in events
                   for target in ((branch, *push_branches) if event in {'push', 'workflow_run'} else (branch,))):
            continue
        jobs = document.get('jobs') or {}
        if not isinstance(jobs, dict):
            raise ValueError('Committed workflow effects could not be inspected')
        effects: set[str] = set()
        for job in jobs.values():
            if not isinstance(job, dict):
                raise ValueError('Committed workflow effects could not be inspected')
            if job.get('environment'):
                effects.add('environment')
            if job.get('uses'):
                effects.add('delegated_workflow')
            for step in job.get('steps') or []:
                if not isinstance(step, dict):
                    raise ValueError('Committed workflow effects could not be inspected')
                action = str(step.get('uses') or '').lower()
                options = step.get('with') or {}
                if ('deploy' in action or 'release' in action
                        or ('docker/build-push-action@' in action and isinstance(options, dict)
                            and options.get('push') not in (None, False, 'false'))):
                    effects.add('publication_action')
                if _COMMAND.search(str(step.get('run') or '')):
                    effects.add('deployment_command')
        if effects:
            result[path] = sorted(effects)
    return result


def delivery_workflow_authority(repo: Path, sha: str, base_sha: str | None, branch: str,
                                staging_branch: str | None, *, git: Callable[..., Any],
                                authorized: tuple[str, ...]) -> dict[str, Any]:
    """Bind authority to source/staging pushes and current base-triggered workflows."""
    source = workflow_effects(repo, sha, branch, git=git,
                              push_branches=(staging_branch,) if staging_branch else ())
    required = set(source)
    base: dict[str, list[str]] = {}
    if base_sha is not None:
        if not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', base_sha):
            raise ValueError('Remote workflow base is unknown')
        base = workflow_effects(repo, base_sha, branch, git=git,
                                push_branches=(staging_branch,) if staging_branch else (),
                                events=('pull_request_target', 'workflow_run'))
        for path in base:
            selected = git(repo, 'rev-parse', '--verify', f'{sha}:{path}')
            existing = git(repo, 'rev-parse', '--verify', f'{base_sha}:{path}')
            if (selected.returncode == existing.returncode == 0
                    and selected.stdout.strip() == existing.stdout.strip()):
                required.add(path)
            else:
                required.add(f'{base_sha}:{path}')
    return {'source_commit': sha, 'base_commit': base_sha, 'staging_branch': staging_branch,
            'source_effects': source, 'base_effects': base,
            'required_workflows': sorted(required),
            'unauthorized_workflows': sorted(required - set(authorized))}
