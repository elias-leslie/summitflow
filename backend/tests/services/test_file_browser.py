"""Tests for file browser helpers."""

from __future__ import annotations

from io import BytesIO
from typing import cast

import pytest

from app.services import file_browser


def test_write_uploaded_file_writes_into_valid_directory(tmp_path) -> None:
    (tmp_path / 'docs').mkdir()

    result = file_browser.write_uploaded_file(
        tmp_path,
        'docs',
        'note.txt',
        BytesIO(b'hello world'),
    )

    assert result == {
        'path': 'docs/note.txt',
        'directory': 'docs',
        'name': 'note.txt',
        'size': 11,
    }
    assert (tmp_path / 'docs' / 'note.txt').read_text() == 'hello world'


def test_write_uploaded_file_rejects_existing_target(tmp_path) -> None:
    target_dir = tmp_path / 'docs'
    target_dir.mkdir()
    (target_dir / 'note.txt').write_text('old')

    with pytest.raises(FileExistsError, match=r'File already exists: note\.txt'):
        file_browser.write_uploaded_file(
            tmp_path,
            'docs',
            'note.txt',
            BytesIO(b'new value'),
        )


def test_resolve_safe_path_blocks_escape(tmp_path) -> None:
    with pytest.raises(ValueError):
        file_browser.resolve_safe_path(tmp_path, '../outside.txt')


def test_list_directory_includes_hidden_and_previously_skipped_entries(tmp_path) -> None:
    (tmp_path / '.git').mkdir()
    (tmp_path / '.hidden').mkdir()
    (tmp_path / 'references').mkdir()
    (tmp_path / 'node_modules').mkdir()

    result = file_browser.list_directory(tmp_path)
    entries = result['entries']
    assert isinstance(entries, list)
    names = {
        str(cast(dict[str, object], entry).get('name'))
        for entry in entries
        if isinstance(entry, dict)
    }

    assert '.git' in names
    assert '.hidden' in names
    assert 'references' in names
    assert 'node_modules' in names


def test_read_file_allows_dotfiles(tmp_path) -> None:
    (tmp_path / '.env').write_text('TOKEN=test\n')

    result = file_browser.read_file(tmp_path, '.env')

    assert result['name'] == '.env'
    assert result['content'] == 'TOKEN=test\n'
    assert result['is_binary'] is False
