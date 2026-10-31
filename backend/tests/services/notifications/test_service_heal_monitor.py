"""The health monitor's heal pass: fixed problems need nobody; unfixed ones push once and resolve later."""

from __future__ import annotations

import json
import subprocess
from unittest.mock import Mock

import pytest

from app.services.notifications import service_heal


class _Redis:
    def __init__(self) -> None:
        self.members: set[str] = set()

    def smembers(self, _key):
        return set(self.members)

    def sadd(self, _key, value):
        self.members.add(value)

    def srem(self, _key, value):
        self.members.discard(value)


@pytest.fixture
def heal(monkeypatch):
    redis = _Redis()
    calls: list[tuple[list[str], str | None]] = []
    results: list[dict] = []
    monkeypatch.setattr(service_heal, "get_redis", lambda: redis)
    monkeypatch.setattr(service_heal.shutil, "which", lambda _name: "/bin/st")
    monkeypatch.setattr(service_heal, "_nightshift", lambda: "/bin/nightshift")

    def run(command, **kwargs):
        if command[0] == "/bin/st":
            assert command[1:] == ["service", "heal", "--json"]
            return subprocess.CompletedProcess(command, 0, "\n".join(json.dumps(r) for r in results), "")
        calls.append((command[1:], kwargs.get("input")))
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(service_heal.safe_subprocess, "run", Mock(side_effect=run))
    return redis, calls, results


FAILED = {"project": "aico", "status": "failed", "restarted": ["aico-web.service"],
          "detail": "the restart onto the current release did not fix it",
          "problems": [{"unit": "aico-web.service", "kind": "page_down",
                        "detail": "/ answers 404 while /health answers 200", "restartable": True}]}


def test_a_healed_project_reaches_nobody(heal):
    redis, calls, results = heal
    results.append({"project": "aico", "status": "healed", "restarted": ["aico-web.service"], "problems": []})
    summary = service_heal.run_service_heal()
    assert summary["healed"] == ["aico"] and calls == [] and redis.members == set()


def test_an_unfixed_project_pushes_through_nightshift_then_resolves(heal):
    redis, calls, results = heal
    results.append(FAILED)
    assert service_heal.run_service_heal()["alerted"] == ["aico"]
    arguments, stdin = calls[0]
    assert arguments == ["push", "--json"]
    notice = json.loads(stdin)
    assert notice["key"] == "service-heal:aico" and notice["source"] == "summitflow"
    assert notice["body"] == "aico-web.service: / answers 404 while /health answers 200"
    assert redis.members == {"aico"}
    results[0] = {"project": "aico", "status": "ok", "problems": []}
    assert service_heal.run_service_heal()["resolved"] == ["aico"]
    assert calls[-1][0][:2] == ["resolve", "service-heal:aico"]
    assert redis.members == set()
    service_heal.run_service_heal()
    assert len(calls) == 2  # healthy and never alerted: no Nightshift call


def test_busy_or_skipped_projects_neither_push_nor_resolve(heal):
    redis, calls, results = heal
    redis.members.add("aico")
    results.extend([{"project": "aico", "status": "busy"}, {"project": "x", "status": "skipped"}])
    service_heal.run_service_heal()
    assert calls == [] and redis.members == {"aico"}
