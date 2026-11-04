"""The Tether-backed coordination store (coord_store) behind leases, and the Aico delegation seam."""

from __future__ import annotations

import copy

import pytest

from cli.lib import aico_delegate, coord_store, leases


class FakeTether:
    """Tether's /v1/coordination/docs routes in memory: documents with versions and compare-and-set writes."""

    def __init__(self) -> None:
        self.docs: dict[str, dict] = {}
        self.versions: dict[str, int] = {}
        self.down = False
        self.before_put = None  # called with the name before a write is judged: another process saving first
        self.conflicts = 0

    def put(self, name, doc):
        self.docs[name] = doc
        self.versions[name] = self.versions.get(name, 0) + 1

    def request(self, method, path, body=None):
        if self.down:
            raise coord_store.Unavailable("ConnectionRefusedError")
        rest = path.removeprefix("/v1/coordination/docs")
        if not rest:
            return 200, {"items": [{"name": n} for n in self.docs]}
        name = rest.removeprefix("/")
        if "/" in name:
            return 404, {"error": "not_found"}
        if method == "GET":
            return 200, {"doc": copy.deepcopy(self.docs.get(name, {})), "version": self.versions.get(name, 0)}
        if self.before_put:
            self.before_put(name)
        assert body is not None
        if body.get("version") != self.versions.get(name, 0):
            self.conflicts += 1
            return 409, {"error": "version_conflict", "version": self.versions.get(name, 0)}
        self.put(name, copy.deepcopy(body["doc"]))
        return 200, {"name": name, "version": self.versions[name]}


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
    assert "proj" in tether.docs
    assert leases.release("proj", None, project_root="/srv/p") == 1
    assert leases.list_active("proj") == []


def test_a_write_that_lost_a_race_is_redone_and_loses_nothing(tether):
    leases.acquire("proj", ["/srv/p/a/**"], project_root="/srv/p")
    other = {**tether.docs["proj"]["leases"][0], "lease_id": "other001", "agent_id": "codex:999999",
             "globs": ["/srv/p/c/**"]}

    def another_process_saves_first(name):
        tether.before_put = None
        tether.put(name, {**tether.docs[name], "leases": [*tether.docs[name]["leases"], other]})

    tether.before_put = another_process_saves_first
    leases.acquire("proj", ["/srv/p/b/**"], project_root="/srv/p")
    assert tether.conflicts == 1
    assert sorted(g for lease in tether.docs["proj"]["leases"] for g in lease["globs"]) == [
        "/srv/p/a/**", "/srv/p/b/**", "/srv/p/c/**"]


def test_a_store_that_does_not_answer_is_never_read_as_empty(tether):
    leases.acquire("proj", ["/srv/p/a/**"], project_root="/srv/p")
    tether.put("_coord", {"messages": [{"id": "m1"}], "identities": {"cc:aaaaaa": {"anchor": "1:1"}}})
    before = copy.deepcopy(tether.docs)
    tether.down = True
    with pytest.raises(coord_store.Unavailable, match="coordination store unavailable"):
        coord_store.read("_coord")
    with pytest.raises(coord_store.Unavailable):
        leases.acquire("proj", ["/srv/p/b/**"], project_root="/srv/p")
    with pytest.raises(coord_store.Unavailable):
        leases.release_paths("proj", ["/srv/p/a/x"])
    tether.down = False
    assert tether.docs == before


def test_a_failed_read_inside_a_change_skips_the_write(tether, monkeypatch):
    tether.put("_coord", {"messages": [{"id": "m1"}]})
    calls = iter([tether.request, lambda *a, **k: (500, {"error": "internal"})])
    monkeypatch.setattr(coord_store, "_request", lambda *a, **k: next(calls)(*a, **k))
    with pytest.raises(coord_store.Unavailable), coord_store.lock("_coord"):
        coord_store.write("_coord", {**coord_store.read("_coord"), "notes": []})
    assert tether.docs["_coord"] == {"messages": [{"id": "m1"}]}
    monkeypatch.setattr(coord_store, "_request", lambda *a, **k: (503, {}))
    with pytest.raises(coord_store.Unavailable), coord_store.lock("_coord"):
        raise AssertionError("the change must not run on a document it could not read")


def test_safety_checks_refuse_when_the_store_is_down(tether, monkeypatch, tmp_path):
    from cli.lib import commit_workflow, coord
    from cli.lib.snapshots import _saved_work

    tether.down = True
    monkeypatch.setattr(coord, "project_for_path", lambda repo: ("proj", tmp_path))
    with pytest.raises(commit_workflow.CommitError, match="coordination store unavailable"):
        commit_workflow._require_no_sweep(tmp_path, ["."], ["a.py"])
    with pytest.raises(coord.CoordBlocked, match="coordination store unavailable"):
        coord.guard(tmp_path, "commit")
    coord.guard(tmp_path, "rebuild")  # warns: a rebuild is how a broken Tether is put back
    with pytest.raises(_saved_work.SnapshotError, match="coordination store unavailable"):
        _saved_work.require_owned("proj", tmp_path, ["a.py"], ["a.py"])


def test_response_limit_fits_a_full_document():
    from app.services import tether as tether_client

    assert coord_store.MAX_DOC_BYTES > 2 * 1024 * 1024 > tether_client.MAX_RESPONSE_BYTES


def test_older_tether_keeps_the_file_store(monkeypatch):
    monkeypatch.delenv("ST_LEASES_DIR", raising=False)
    monkeypatch.setattr(coord_store, "_has_routes", None)
    monkeypatch.setattr(coord_store, "_request", lambda *a, **k: (404, {}))
    assert coord_store.enabled() is False


def test_a_silent_tether_does_not_switch_store(monkeypatch):
    monkeypatch.delenv("ST_LEASES_DIR", raising=False)
    monkeypatch.setattr(coord_store, "_has_routes", None)

    def silent(*a, **k):
        raise coord_store.Unavailable("ConnectionRefusedError")

    monkeypatch.setattr(coord_store, "_request", silent)
    assert coord_store.enabled() is True
    with pytest.raises(coord_store.Unavailable):
        coord_store.read("proj")


def test_delegation_is_off_in_tests_and_when_rolled_back(monkeypatch):
    monkeypatch.setenv("ST_LEASES_DIR", "/tmp/x")
    assert aico_delegate.enabled() is False
    monkeypatch.delenv("ST_LEASES_DIR")
    monkeypatch.setenv("ST_AICO_COORD", "0")
    assert aico_delegate.enabled() is False
