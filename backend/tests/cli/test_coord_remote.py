"""st sessions send across machines: to a window on an agent host, and from one."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from cli.commands import sessions_fleet
from cli.lib import coord, coord_remote, coordinators
from cli.main import app

runner = CliRunner()
REMOTE = {"id": "a810c7e0", "host": "agent-work", "generation": "g" * 64, "rootRequestId": "rh2b-live-1",
          "displayTitle": "Aico", "tmux": {"sessionName": "aico-a810c7e0"}}
LOCAL = {"id": "4a9a070d", "displayTitle": "Agent-Hub", "tmux": {"sessionName": "aico-4a9a070d"}}


@pytest.fixture
def tether(monkeypatch):
    from app.services import tether as service

    calls = []
    monkeypatch.delenv("ST_AGENT_HOST", raising=False)
    monkeypatch.setenv("AICO_WIDGET_ID", "ea3f2738")
    monkeypatch.setattr(coord_remote.leases, "identify_agent", lambda **_: ("cc:ea3f27", "", "", ""))
    monkeypatch.setattr(service, "request_all", lambda path: [(200, {"items": [REMOTE, LOCAL]})])

    def request(method, path, body=None, **_):
        calls.append((method, path, body))
        return 200, {"generation": (body or {}).get("generation"), "delivered": True}

    monkeypatch.setattr(service, "request", request)
    return calls


@pytest.mark.parametrize("target", ["a810c7e0", "rh2b-live-1", "aico-a810c7e0"])
def test_a_window_on_an_agent_host_gets_the_request_through_the_hub(monkeypatch, tether, target):
    monkeypatch.setattr(sessions_fleet, "_resolve_agent", lambda _: pytest.fail("used this computer's ledger"))
    result = runner.invoke(app, ["sessions", "send", target, "Run the check"])
    assert result.exit_code == 0, result.output
    assert "sent to window a810c7e0 on agent-work" in result.output
    [(method, path, body)] = tether
    assert (method, path) == ("POST", "/v1/sessions/a810c7e0/inject")
    assert body["generation"] == "g" * 64 and body["mode"] == "paste" and body["submit"] is True
    assert body["text"].startswith("[st sessions send from cc:ea3f27 (window ea3f2738) on ")
    assert "Run the check" in body["text"] and "st sessions send cc:ea3f27 '<answer>'" in body["text"]


def test_a_refused_inject_says_why(monkeypatch, tether):
    from app.services import tether as service

    monkeypatch.setattr(service, "request", lambda *a, **k: (409, {"error": "host_unavailable", "reason": "agent-work is offline"}))
    result = runner.invoke(app, ["sessions", "send", "a810c7e0", "Run the check"])
    assert result.exit_code == 2
    assert "did not take it (host_unavailable: agent-work is offline)" in result.output


def test_agent_ids_and_local_windows_keep_this_computers_ledger(monkeypatch, tether):
    sent = []
    monkeypatch.setattr(sessions_fleet, "_resolve_agent", lambda target: target)
    from cli.commands import sessions_handshake

    monkeypatch.setattr(sessions_handshake, "send_request", lambda to, text, key=None: sent.append(to))
    for target in ("cc:4a9a07", "Agent-Hub"):
        assert runner.invoke(app, ["sessions", "send", target, "x"]).exit_code == 0
    assert sent == ["cc:4a9a07", "Agent-Hub"] and tether == []


def test_on_an_agent_host_an_unknown_target_goes_to_the_workstation(monkeypatch, tether):
    from app.services import tether as service

    monkeypatch.setenv("ST_AGENT_HOST", "agent-work")
    monkeypatch.setenv("AICO_WIDGET_ID", "a810c7e0")
    monkeypatch.setattr(service, "request_all", lambda path: [(200, {"items": []})])
    posted = []

    class Client:
        def __init__(self, **_):
            pass

        def _global_url(self, path):
            return "http://127.0.0.1:8001/api" + path

        def post(self, url, json):
            posted.append((url, json))
            return {"id": "abc123", "to": "cc:4a9a07", "state": "open"}

    monkeypatch.setattr(sessions_fleet, "STClient", Client)
    monkeypatch.setattr(sessions_fleet, "_resolve_agent", lambda _: pytest.fail("used the host's ledger"))
    result = runner.invoke(app, ["sessions", "send", "cc:4a9a07", "Done: check passed"])
    assert result.exit_code == 0, result.output
    assert "sent abc123 -> cc:4a9a07 on the workstation" in result.output
    assert posted == [("http://127.0.0.1:8001/api/fleet/v1/coordination/requests", {
        "target": "cc:4a9a07", "text": "Done: check passed", "sender": "cc:ea3f27", "host": "agent-work",
        "reply_to": "a810c7e0"})]


def test_on_an_agent_host_its_own_agents_keep_its_ledger(monkeypatch, tether):
    monkeypatch.setenv("ST_AGENT_HOST", "agent-work")
    monkeypatch.setattr(coord, "known_target", lambda target: target == "cc:111111")
    assert coord_remote.names_local_agent("cc:111111")
    assert coord_remote.names_local_agent("Agent-Hub")  # a window without host is this machine's
    assert not coord_remote.names_local_agent("cc:4a9a07")


def test_a_host_request_lands_in_the_workstation_ledger_for_the_named_agent(monkeypatch, tether):
    monkeypatch.setattr(coordinators, "agent_for_widget", {"4a9a070d": "cc:4a9a07"}.get)
    row = coord_remote.record_from_host("Agent-Hub", "Done: check passed", sender="cc:9b1c2d",
                                        host="agent-work", reply_to="a810c7e0")
    assert row["to"] == "cc:4a9a07" and row["from"] == "cc:9b1c2d@agent-work"
    assert row["text"].startswith("Done: check passed (from cc:9b1c2d on agent-work; reply with: st sessions send a810c7e0")
    [stored] = coord._load_ledger()
    assert stored["id"] == row["id"]


@pytest.mark.parametrize("kwargs", [
    {"sender": "cc:9b1c2d", "host": "Agent Work"},
    {"sender": "anyone", "host": "agent-work"},
    {"sender": "cc:9b1c2d", "host": "agent-work", "reply_to": "../x"},
])
def test_a_malformed_host_request_is_refused(tether, kwargs):
    with pytest.raises(ValueError):
        coord_remote.record_from_host("cc:4a9a07", "x", **kwargs)


def test_a_host_request_from_a_shell_in_a_tether_root_is_recorded(monkeypatch, tether):
    """A root whose agent isn't running leaves a shell whose id is st:<root handle>."""
    monkeypatch.setattr(coordinators, "agent_for_widget", {"4a9a070d": "cc:4a9a07"}.get)
    row = coord_remote.record_from_host("Agent-Hub", "x", sender="st:aico-root-f36",
                                        host="agent-work", reply_to="c1338b32")
    assert row["from"] == "st:aico-root-f36@agent-work"


def test_a_host_request_for_no_agent_here_is_not_found(monkeypatch, tether):
    monkeypatch.setattr(coordinators, "agent_for_widget", lambda _: None)
    with pytest.raises(LookupError):
        coord_remote.record_from_host("nobody", "x", sender="cc:9b1c2d", host="agent-work")
