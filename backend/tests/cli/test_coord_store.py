"""The Tether-backed coordination store (coord_store) behind leases, and the Aico delegation seam."""

from __future__ import annotations

import itertools

import pytest

from cli.lib import aico_delegate, coord_store, leases


class FakeTether:
    """Tether's /v1/coordination/docs routes in memory: documents, and a lock a write must present."""

    def __init__(self) -> None:
        self.docs: dict[str, dict] = {}
        self.locks: dict[str, str] = {}
        self.ids = itertools.count(1)

    def request(self, method, path, body=None, timeout=0):
        rest = path.removeprefix("/v1/coordination/docs")
        if not rest:
            return 200, {"items": [{"name": n} for n in self.docs]}
        name, _, tail = rest.removeprefix("/").partition("/")
        if tail == "lock" and method == "POST":
            token = f"t{next(self.ids)}"
            self.locks[name] = token
            return 200, {"lock": token}
        if tail.startswith("lock") and method == "DELETE":
            self.locks.pop(name, None)
            return 200, {}
        if method == "GET":
            return 200, {"doc": self.docs.get(name, {})}
        if self.locks.get(name) != (body or {}).get("lock"):
            return 423, {}
        self.docs[name] = (body or {})["doc"]
        return 200, {}


@pytest.fixture
def tether(monkeypatch):
    fake = FakeTether()
    monkeypatch.delenv("ST_LEASES_DIR", raising=False)
    monkeypatch.setattr(coord_store, "_has_routes", None)
    monkeypatch.setattr(coord_store, "_request", fake.request)
    monkeypatch.setenv("CLAUDE_SESSION_ID", "")
    return fake


def test_leases_live_in_tether_documents(tether):
    leases.acquire("proj", ["/srv/p/a/**"], project_root="/srv/p")
    assert [lease.globs for lease in leases.list_active("proj")] == [["/srv/p/a/**"]]
    assert "proj" in tether.docs and not tether.locks
    assert leases.release("proj", None, project_root="/srv/p") == 1
    assert leases.list_active("proj") == []


def test_older_tether_keeps_the_file_store(monkeypatch):
    monkeypatch.delenv("ST_LEASES_DIR", raising=False)
    monkeypatch.setattr(coord_store, "_has_routes", None)
    monkeypatch.setattr(coord_store, "_request", lambda *a, **k: (404, {}))
    assert coord_store.enabled() is False


def test_a_silent_tether_does_not_switch_store(monkeypatch):
    monkeypatch.delenv("ST_LEASES_DIR", raising=False)
    monkeypatch.setattr(coord_store, "_has_routes", None)
    monkeypatch.setattr(coord_store, "_request", lambda *a, **k: None)
    assert coord_store.enabled() is True
    assert coord_store.read("proj") == {}


def test_delegation_is_off_in_tests_and_when_rolled_back(monkeypatch):
    monkeypatch.setenv("ST_LEASES_DIR", "/tmp/x")
    assert aico_delegate.enabled() is False
    monkeypatch.delenv("ST_LEASES_DIR")
    monkeypatch.setenv("ST_AICO_COORD", "0")
    assert aico_delegate.enabled() is False
