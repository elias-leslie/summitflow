"""Tests for file browser API endpoints."""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.storage.connection import get_connection


@pytest.fixture
def file_api_project(db_schema_initialized: None, tmp_path: Path) -> Generator[tuple[str, Path]]:
    project_id = 'files-api-test'
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO projects (id, name, base_url, root_path)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE
            SET name = EXCLUDED.name,
                base_url = EXCLUDED.base_url,
                root_path = EXCLUDED.root_path
            """,
            (project_id, 'Files API Test', 'http://localhost:3001', str(tmp_path)),
        )
        conn.commit()

    yield project_id, tmp_path

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute('DELETE FROM projects WHERE id = %s', (project_id,))
        conn.commit()


def test_project_file_upload_and_download(
    client: TestClient,
    file_api_project: tuple[str, Path],
) -> None:
    project_id, root_path = file_api_project
    (root_path / 'docs').mkdir()

    upload_response = client.post(
        f'/api/projects/{project_id}/files/upload',
        params={'path': 'docs'},
        files={'upload': ('note.txt', b'hello world', 'text/plain')},
    )

    assert upload_response.status_code == 200
    assert upload_response.json() == {
        'path': 'docs/note.txt',
        'directory': 'docs',
        'name': 'note.txt',
        'size': 11,
    }

    content_response = client.get(
        f'/api/projects/{project_id}/files/content',
        params={'path': 'docs/note.txt'},
    )

    assert content_response.status_code == 200
    assert content_response.json()['content'] == 'hello world'
    assert content_response.json()['is_binary'] is False

    download_response = client.get(
        f'/api/projects/{project_id}/files/download',
        params={'path': 'docs/note.txt'},
    )

    assert download_response.status_code == 200
    assert download_response.content == b'hello world'
    assert download_response.headers['content-disposition'].startswith('attachment;')

    overwrite_response = client.post(
        f'/api/projects/{project_id}/files/upload',
        params={'path': 'docs'},
        files={'upload': ('note.txt', b'new value', 'text/plain')},
    )
    assert overwrite_response.status_code == 200
    assert (root_path / 'docs' / 'note.txt').read_text() == 'new value'


def test_project_files_support_crud_and_workspace_root_paths(
    client: TestClient,
    file_api_project: tuple[str, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id, root_path = file_api_project
    monkeypatch.setenv('ST_WORKSPACES_ROOT', str(root_path.parent))
    (root_path / 'docs').mkdir()
    server_sibling = root_path.parent / 'server-sibling'
    server_sibling.mkdir()
    (server_sibling / 'outside.txt').write_text('outside')

    tree_response = client.get(f'/api/projects/{project_id}/files/tree')
    assert tree_response.status_code == 200
    assert tree_response.json()['absolute_path'] == str(root_path)

    server_tree_response = client.get(
        f'/api/projects/{project_id}/files/tree',
        params={'path': str(root_path.parent)},
    )
    assert server_tree_response.status_code == 200
    assert server_tree_response.json()['path'] == str(root_path.parent)
    assert str(server_sibling) in {
        entry['path'] for entry in server_tree_response.json()['entries']
    }

    create_dir_response = client.post(
        f'/api/projects/{project_id}/files/directory',
        json={'directory': 'docs', 'name': 'new'},
    )
    assert create_dir_response.status_code == 200
    assert create_dir_response.json()['path'] == 'docs/new'

    create_file_response = client.post(
        f'/api/projects/{project_id}/files/file',
        json={'directory': 'docs/new', 'name': 'draft.txt', 'content': 'draft'},
    )
    assert create_file_response.status_code == 200
    assert (root_path / 'docs' / 'new' / 'draft.txt').read_text() == 'draft'

    write_response = client.put(
        f'/api/projects/{project_id}/files/file',
        json={'path': 'docs/new/draft.txt', 'content': 'final'},
    )
    assert write_response.status_code == 200
    assert (root_path / 'docs' / 'new' / 'draft.txt').read_text() == 'final'

    rename_response = client.patch(
        f'/api/projects/{project_id}/files/path/rename',
        json={'path': 'docs/new/draft.txt', 'name': 'final.txt'},
    )
    assert rename_response.status_code == 200
    assert rename_response.json()['path'] == 'docs/new/final.txt'

    delete_response = client.delete(
        f'/api/projects/{project_id}/files/path',
        params={'path': 'docs/new/final.txt'},
    )
    assert delete_response.status_code == 200
    assert delete_response.json()['deleted'] is True

    absolute_write = client.put(
        f'/api/projects/{project_id}/files/file',
        json={'path': str(server_sibling / 'outside.txt'), 'content': 'changed'},
    )
    assert absolute_write.status_code == 200
    assert (server_sibling / 'outside.txt').read_text() == 'changed'


def test_workspace_file_routes_use_global_root_helper(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace_root = tmp_path / 'workspace'
    workspace_root.mkdir()
    (workspace_root / 'outside.txt').write_text('global file')
    (workspace_root / 'drop').mkdir()

    monkeypatch.setattr('app.api.files._get_global_files_root', lambda: workspace_root)

    tree_response = client.get('/api/files/tree')
    assert tree_response.status_code == 200
    assert {entry['name'] for entry in tree_response.json()['entries']} == {'drop', 'outside.txt'}

    upload_response = client.post(
        '/api/files/upload',
        params={'path': 'drop'},
        files={'upload': ('global.txt', b'workspace upload', 'text/plain')},
    )
    assert upload_response.status_code == 200
    assert upload_response.json()['path'] == 'drop/global.txt'

    content_response = client.get('/api/files/content', params={'path': 'drop/global.txt'})
    assert content_response.status_code == 200
    assert content_response.json()['content'] == 'workspace upload'


def test_server_root_is_not_a_files_root(
    client: TestClient,
    file_api_project: tuple[str, Path],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    project_id, _root_path = file_api_project
    workspaces = tmp_path / 'workspaces'
    workspaces.mkdir()
    (workspaces / 'inside.txt').write_text('inside')
    outside = tmp_path / 'outside'
    outside.mkdir()
    (outside / 'keep.txt').write_text('keep')
    monkeypatch.setenv('ST_WORKSPACES_ROOT', str(workspaces))

    from app.api import files

    assert files._get_global_files_root() == workspaces.resolve()

    # Navigating to '/' lands on the workspaces root instead of the server root.
    for response in (
        client.get('/api/files/tree', params={'path': '/'}),
        client.get(f'/api/projects/{project_id}/files/tree', params={'path': '/'}),
    ):
        assert response.status_code == 200
        assert response.json()['absolute_path'] == str(workspaces.resolve())
        assert {entry['name'] for entry in response.json()['entries']} == {'inside.txt'}

    assert client.get('/api/files/content', params={'path': '/etc/hostname'}).status_code == 400
    assert (
        client.get(f'/api/projects/{project_id}/files/content', params={'path': '/etc/hostname'}).status_code
        == 400
    )
    for response in (
        client.delete('/api/files/path', params={'path': str(outside / 'keep.txt')}),
        client.delete(f'/api/projects/{project_id}/files/path', params={'path': str(outside / 'keep.txt')}),
        client.delete('/api/files/path', params={'path': '../outside/keep.txt'}),
        # Project root lies outside the workspaces root here: the delete guard refuses it.
        client.delete(f'/api/projects/{project_id}/files/path', params={'path': 'outside/keep.txt'}),
    ):
        assert response.status_code in {400, 403}
    assert (outside / 'keep.txt').read_text() == 'keep'
