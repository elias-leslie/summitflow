"""Canonical manifest lifecycle controls discovery, never explicit history."""
from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import project_identity
from app.api import projects
from app.api.projects import listing
from cli.lib import service_ops


@pytest.fixture
def identities(tmp_path, monkeypatch):
    monkeypatch.setattr(project_identity, '_PROJECTS_ROOT', tmp_path)
    monkeypatch.setattr(project_identity, '_local_manifest_paths', lambda: ())
    project_identity._workspace_manifest_paths.cache_clear()
    roots = {}
    for name, lifecycle in [('current', None), ('old', 'retired'), ('test-only', None)]:
        root = tmp_path / name
        root.mkdir()
        project = {'id': name, 'legacy_ids': [name + '-alias']}
        if lifecycle:
            project['lifecycle'] = lifecycle
        (root / 'project.identity.json').write_text(json.dumps({'project': project}))
        roots[name] = root
    yield roots
    project_identity._workspace_manifest_paths.cache_clear()
    project_identity._read_manifest.cache_clear()


def test_lifecycle_defaults_aliases_and_manifest_updates(identities):
    assert project_identity.get_project_lifecycle('current') == 'active'
    assert project_identity.get_project_lifecycle('missing') == 'active'
    assert project_identity.get_project_lifecycle('old-alias') == 'retired'
    identity = project_identity.get_project_identity('old')
    assert identity is not None
    assert identity['project']['id'] == 'old'
    new_root = identities['current'].parent / 'added'
    new_root.mkdir()
    assert project_identity.get_project_lifecycle('added-alias') == 'active'
    (new_root / 'project.identity.json').write_text(json.dumps({
        'project': {'id': 'added', 'legacy_ids': ['added-alias'], 'lifecycle': 'retired'}}))
    assert project_identity.get_project_lifecycle('added-alias') == 'retired'
    (new_root / 'project.identity.json').unlink()
    assert project_identity.get_project_lifecycle('added-alias') == 'active'
    manifest = identities['current'] / 'project.identity.json'
    manifest.write_text(json.dumps({'project': {'id': 'current', 'lifecycle': 'retired'}}))
    assert project_identity.get_project_lifecycle('current') == 'retired'
    manifest.write_text(json.dumps({'project': {'id': 'current', 'lifecycle': 'typo'}}))
    with pytest.raises(ValueError, match='lifecycle'):
        project_identity.get_project_lifecycle('current')


def test_unscoped_services_skip_retired_and_fixtures(identities, monkeypatch):
    monkeypatch.setattr("app.storage.projects.testing_project_ids", lambda: {"test-only"})
    assert service_ops.project_ids() == ['current']
    assert service_ops.project_ids(include_inactive=True) == ['current', 'old', 'test-only']


def test_routes_filter_before_health_and_allow_explicit_inventory(identities, monkeypatch):
    rows: list[listing.ProjectListRow] = [(name, name, 'http://localhost:1', None, '/health', str(root), 'testing' if name == 'test-only' else 'dev', None, datetime.now(UTC))
            for name, root in identities.items()]
    cursor = Mock()
    cursor.fetchall.return_value = rows

    @contextmanager
    def get_cursor():
        yield cursor

    monkeypatch.setattr(listing, 'get_cursor', get_cursor)
    health = AsyncMock(return_value={'current': 'healthy'})
    monkeypatch.setattr(projects, '_resolve_project_health_statuses', health)
    app = FastAPI()
    app.include_router(projects.router, prefix='/projects')
    client = TestClient(app)
    response = client.get('/projects')
    assert response.status_code == 200
    assert [row['id'] for row in response.json()] == ['current']
    assert list(health.call_args.args[0]) == [('current', 'http://localhost:1', '/health')]
    response = client.get('/projects?include_inactive=true')
    assert response.status_code == 200
    assert {row['id']: row['lifecycle'] for row in response.json()} == {
        'current': 'active', 'old': 'retired', 'test-only': 'active'}
    assert list(health.call_args.args[0]) == [('current', 'http://localhost:1', '/health')]
    from app.api.projects.models import ProjectStats
    monkeypatch.setattr(projects, 'fetch_project_stats', lambda ids: {name: ProjectStats() for name in ids})
    monkeypatch.setattr(projects, '_get_quality_summaries', lambda ids: {
        name: {'project_id': name, 'overall_pass': True, 'total_unfixed': 0, 'checks': {}} for name in ids})
    monkeypatch.setattr(projects, 'get_active_checkpoint_map', lambda: {})
    response = client.get('/projects/with-stats')
    assert response.status_code == 200
    assert [row['id'] for row in response.json()['projects']] == ['current']
    response = client.get('/projects/with-stats?include_inactive=true')
    assert response.status_code == 200
    assert response.json()['total'] == 3
    assert list(health.call_args.args[0]) == [('current', 'http://localhost:1', '/health')]
    monkeypatch.setattr(projects, 'get_project_from_db' , lambda _: listing.build_project_response(rows[1]))
    response = client.get('/projects/old')
    assert response.status_code == 200
    assert response.json()['lifecycle'] == 'retired'
