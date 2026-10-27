"""Nightly security alert: fixable runtime advisories only, one push per new finding."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.tasks import nightly_security_alert as alert

UV_LOCK = """version = 1
requires-python = ">=3.12"

[[package]]
name = "demo"
version = "0.1.0"
source = { virtual = "." }
dependencies = [{ name = "jinja2" }]

[package.dev-dependencies]
dev = [{ name = "requests" }]

[[package]]
name = "jinja2"
version = "2.10"
source = { registry = "https://pypi.org/simple" }
dependencies = [{ name = "markupsafe" }]

[[package]]
name = "markupsafe"
version = "1.0"
source = { registry = "https://pypi.org/simple" }

[[package]]
name = "requests"
version = "2.19.0"
source = { registry = "https://pypi.org/simple" }
"""

PNPM_LOCK = """lockfileVersion: '9.0'
importers:
  .:
    dependencies:
      lodash:
        specifier: 4.17.15
        version: 4.17.15
    devDependencies:
      minimist:
        specifier: 1.2.0
        version: 1.2.0
snapshots:
  lodash@4.17.15: {}
  minimist@1.2.0: {}
"""


def vulnerability(advisory: str, package: str, ecosystem: str, introduced: str, fixed: str | None) -> dict[str, Any]:
    events: list[dict[str, str]] = [{"introduced": introduced}] + ([{"fixed": fixed}] if fixed else [])
    return {"id": advisory, "affected": [{"package": {"name": package, "ecosystem": ecosystem},
                                          "ranges": [{"type": "ECOSYSTEM", "events": events}]}]}


def package(name: str, version: str, ecosystem: str, advisory: str, fixed: str | None, groups: list[str] | None = None,
            introduced: str = "0") -> dict[str, Any]:
    return {"package": {"name": name, "version": version, "ecosystem": ecosystem},
            **({"dependency_groups": groups} if groups else {}),
            "groups": [{"ids": [advisory]}],
            "vulnerabilities": [vulnerability(advisory, name, ecosystem, introduced, fixed)]}


def test_fixed_version_needs_a_range_covering_the_locked_version() -> None:
    advisory = {"affected": [{"package": {"name": "Foo_Bar"}, "ranges": [
        {"type": "ECOSYSTEM", "events": [{"introduced": "0"}, {"fixed": "1.2.0"}, {"introduced": "2.0"}, {"fixed": "2.5.1"}]}]}]}
    assert alert._fixed_version(advisory, "foo-bar", "1.0.3") == "1.2.0"
    assert alert._fixed_version(advisory, "foo-bar", "2.1") == "2.5.1"
    assert alert._fixed_version(advisory, "foo-bar", "3.0") is None
    assert alert._fixed_version({"affected": [{"package": {"name": "x"}, "ranges": [
        {"type": "ECOSYSTEM", "events": [{"introduced": "0"}]}]}]}, "x", "1.0") is None  # no fix released


def test_only_fixable_runtime_findings_are_reported(tmp_path: Path) -> None:
    (tmp_path / "backend").mkdir()
    (tmp_path / "backend/uv.lock").write_text(UV_LOCK)
    (tmp_path / "pnpm-lock.yaml").write_text(PNPM_LOCK)
    (tmp_path / "web").mkdir()
    (tmp_path / "web/package-lock.json").write_text("{}")
    data = {"results": [
        {"source": {"path": str(tmp_path / "backend/uv.lock")}, "packages": [
            package("jinja2", "2.10", "PyPI", "PYSEC-1", "2.11.3"),
            package("markupsafe", "1.0", "PyPI", "GHSA-transitive", "2.0"),
            package("requests", "2.19.0", "PyPI", "GHSA-dev", "2.20.0"),  # dev group only
        ]},
        {"source": {"path": str(tmp_path / "pnpm-lock.yaml")}, "packages": [
            package("lodash", "4.17.15", "npm", "GHSA-lodash", "4.17.21"),
            package("minimist", "1.2.0", "npm", "GHSA-dev2", "1.2.6"),  # devDependency
        ]},
        {"source": {"path": str(tmp_path / "web/package-lock.json")}, "packages": [
            package("express", "4.0.0", "npm", "GHSA-express", "4.19.2"),
            package("jest", "1.0.0", "npm", "GHSA-jest", "2.0.0", groups=["dev"]),
            package("left-pad", "1.0.0", "npm", "GHSA-nofix", None),
        ]},
    ]}
    found = alert.findings_from_osv(data, tmp_path)
    assert [(item["package"], item["version"], item["fixed"], item["advisory"]) for item in found] == [
        ("express", "4.0.0", "4.19.2", "GHSA-express"),
        ("jinja2", "2.10", "2.11.3", "PYSEC-1"),
        ("lodash", "4.17.15", "4.17.21", "GHSA-lodash"),
        ("markupsafe", "1.0", "2.0", "GHSA-transitive"),
    ]


@pytest.fixture
def stored(monkeypatch: pytest.MonkeyPatch) -> dict[str, dict[str, Any]]:
    configs: dict[str, dict[str, Any]] = {"summitflow": {}, "other": {}}
    monkeypatch.setattr("app.storage.agent_configs.get_agent_config", lambda project_id: dict(configs[project_id]))
    monkeypatch.setattr("app.storage.agent_configs.update_agent_config",
                        lambda project_id, config: configs[project_id].update(config))
    monkeypatch.setattr(alert, "_projects", lambda ids: [("summitflow", Path("/a")), ("other", Path("/b"))])
    return configs


def finding(package_name: str, advisory: str) -> dict[str, str]:
    return {"package": package_name, "version": "1.0", "fixed": "1.1", "advisory": advisory, "lockfile": "uv.lock"}


def test_each_new_finding_is_pushed_once_and_a_cleared_one_can_return(
        monkeypatch: pytest.MonkeyPatch, stored: dict[str, dict[str, Any]]) -> None:
    scans = {"summitflow": [finding("jinja2", "A-1"), finding("flask", "A-2")], "other": [finding("jinja2", "A-1")]}
    pushed: list[tuple[str, str, str]] = []
    monkeypatch.setattr(alert, "scan_project", lambda root: scans["summitflow" if root == Path("/a") else "other"])
    monkeypatch.setattr(alert, "push_alert", lambda project, item: pushed.append((project, item["package"], item["advisory"])) or True)

    first = alert.run_nightly_security_alert()
    assert first["alerts_sent"] == 3 and len(pushed) == 3  # the same advisory in two projects is two alerts
    assert alert.run_nightly_security_alert()["alerts_sent"] == 0  # nothing new the next night

    scans["summitflow"] = [finding("jinja2", "A-1")]  # flask fixed, then regresses
    alert.run_nightly_security_alert()
    assert stored["summitflow"]["security_alerts_seen"] == ["jinja2|A-1"]
    scans["summitflow"] = [finding("jinja2", "A-1"), finding("flask", "A-2")]
    assert alert.run_nightly_security_alert()["alerts_sent"] == 1


def test_failed_push_is_retried_and_the_nightly_cap_defers_the_rest(
        monkeypatch: pytest.MonkeyPatch, stored: dict[str, dict[str, Any]]) -> None:
    scans = [finding("a", "1"), finding("b", "2"), finding("c", "3")]
    monkeypatch.setattr(alert, "scan_project", lambda root: scans if root == Path("/a") else [])
    outcomes = iter([False, True, True])
    monkeypatch.setattr(alert, "push_alert", lambda project, item: next(outcomes))
    stored["summitflow"]["security_alert_max_per_run"] = 2
    assert alert.run_nightly_security_alert()["alerts_sent"] == 1  # the failed push spent budget; "c" waits for the next night
    assert stored["summitflow"]["security_alerts_seen"] == ["b|2"]


def test_a_failed_scan_changes_nothing(monkeypatch: pytest.MonkeyPatch, stored: dict[str, dict[str, Any]]) -> None:
    stored["other"]["security_alerts_seen"] = ["x|1"]
    monkeypatch.setattr(alert, "scan_project", lambda root: None)
    result = alert.run_nightly_security_alert()
    assert [row["state"] for row in result["projects"]] == ["scan_failed", "scan_failed"]
    assert stored["other"]["security_alerts_seen"] == ["x|1"]


def test_push_uses_nightshift_with_a_key_per_project_package_advisory(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    class Done:
        returncode = 0

    monkeypatch.setattr(alert, "_nightshift", lambda: "/bin/nightshift")
    monkeypatch.setattr(alert.subprocess, "run", lambda command, **_: calls.append(command) or Done())
    assert alert.push_alert("summitflow", finding("jinja2", "A-1"))
    command = calls[0]
    assert command[:2] == ["/bin/nightshift", "push"]
    assert command[command.index("--key") + 1] == "dependency-advisory:summitflow:jinja2:A-1"
    for expected in ("summitflow", "jinja2", "1.0", "1.1", "A-1"):
        assert expected in command[-1]
