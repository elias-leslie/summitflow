from __future__ import annotations

from pathlib import Path

import pytest

from app.utils import pg_client as module


def _client(root: Path, major: int, name: str) -> Path:
    binary = root / str(major) / "bin" / name
    binary.parent.mkdir(parents=True)
    binary.write_text("")
    return binary


def test_dump_client_matches_the_server_major(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(module, "CLIENT_ROOT", tmp_path)
    monkeypatch.setattr(module, "server_major", lambda **_: 16)
    binary = _client(tmp_path, 16, "pg_dump")
    assert module.pg_client("pg_dump", host="h", port="5432", user="u", password="p") == str(binary)


def test_dump_client_falls_back_to_the_command_name(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(module, "CLIENT_ROOT", tmp_path)
    monkeypatch.setattr(module, "server_major", lambda **_: 16)
    assert module.pg_client("pg_dump", host="h", port="5432", user="u", password="p") == "pg_dump"
    monkeypatch.setattr(module, "server_major", lambda **_: None)
    assert module.pg_client("pg_dump", host="h", port="5432", user="u", password="p") == "pg_dump"
