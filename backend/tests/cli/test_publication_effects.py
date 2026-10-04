from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from cli.lib.publication_effects import delivery_workflow_authority, workflow_effects


def inspect_workflow(tmp_path: Path, content: str, **options) -> dict[str, list[str]]:
    def git(repo, *args):
        if args[0] == "ls-tree":
            output = ".github/workflows/release.yml\n"
        else:
            assert args == ("show", "a" * 40 + ":.github/workflows/release.yml")
            output = content
        return subprocess.CompletedProcess(args, 0, output, "")
    return workflow_effects(tmp_path, "a" * 40, "main", git=git, **options)


@pytest.mark.parametrize("trigger", ["push: {tags: [v*]}", "workflow_dispatch:", "push: {branches: [release]}"])
def test_untriggered_release_effects_require_no_authority(tmp_path, trigger):
    content = f"on:\n  {trigger}\njobs:\n  deploy:\n    environment: production\n    steps:\n      - run: scripts/deploy.sh\n"
    assert inspect_workflow(tmp_path, content) == {}


@pytest.mark.parametrize("trigger", ["push:", "pull_request:", "pull_request_target:", "workflow_run: {workflows: [CI], types: [completed]}"])
def test_triggered_deployment_effects_are_source_bound(tmp_path, trigger):
    content = f"on:\n  {trigger}\njobs:\n  deploy:\n    environment: production\n    steps:\n      - run: scripts/deploy.sh\n"
    assert inspect_workflow(tmp_path, content) == {".github/workflows/release.yml": ["deployment_command", "environment"]}


@pytest.mark.parametrize('event', ['push', 'workflow_run'])
def test_staging_branch_effects_require_authority(tmp_path, event):
    content = f"on:\n  {event}: {{branches: ['st/**']}}\njobs:\n  deploy:\n    environment: production\n"
    assert inspect_workflow(tmp_path, content, push_branches=('st/manual-project-source',)) == {".github/workflows/release.yml": ["environment"]}


def test_pr_target_base_effects_cannot_be_hidden_by_selected_source(tmp_path):
    base = 'b' * 40
    path = '.github/workflows/deploy.yml'
    def git(repo, *args):
        if args[0] == 'ls-tree':
            output = path if args[3] == base else ''
        elif args[0] == 'show':
            output = 'on: pull_request_target\njobs:\n  deploy:\n    environment: production\n'
        else:
            return subprocess.CompletedProcess(args, 1, '', '')
        return subprocess.CompletedProcess(args, 0, output, '')
    required = delivery_workflow_authority(tmp_path, 'a' * 40, base, 'main', 'st/manual', git=git, authorized=())
    token = base + ':' + path
    assert required['unauthorized_workflows'] == [token]
    allowed = delivery_workflow_authority(tmp_path, 'a' * 40, base, 'main', 'st/manual', git=git, authorized=(token,))
    assert allowed['unauthorized_workflows'] == []


def test_checks_with_read_only_steps_have_no_known_effect(tmp_path):
    assert inspect_workflow(tmp_path, "on: [push, pull_request]\njobs:\n  check:\n    steps:\n      - uses: actions/checkout@pinned\n      - run: python -m compileall app\n") == {}


def test_reusable_workflow_effects_require_explicit_authority(tmp_path):
    assert inspect_workflow(tmp_path, "on: push\njobs:\n  delegated:\n    uses: owner/repo/.github/workflows/deploy.yml@pinned\n") == {".github/workflows/release.yml": ["delegated_workflow"]}


@pytest.mark.parametrize("value,expected", [("true", True), ("false", False), ("'${{ inputs.push }}'", True)])
def test_image_publication_is_distinct_from_build_only(tmp_path, value, expected):
    result = inspect_workflow(tmp_path, f"on: push\njobs:\n  image:\n    steps:\n      - uses: docker/build-push-action@pinned\n        with:\n          push: {value}\n")
    assert bool(result) is expected


def test_invalid_workflow_effects_remain_unknown(tmp_path):
    with pytest.raises(ValueError, match="could not be inspected"):
        inspect_workflow(tmp_path, "on: [invalid")
