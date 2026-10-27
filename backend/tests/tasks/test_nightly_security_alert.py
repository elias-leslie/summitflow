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
def two_projects(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(alert, "_projects", lambda ids: [("summitflow", Path("/a")), ("other", Path("/b"))])


def finding(package_name: str, advisory: str, version: str = "1.0", fixed: str = "1.1") -> dict[str, str]:
    return {"package": package_name, "version": version, "fixed": fixed, "advisory": advisory, "lockfile": "uv.lock"}


def test_one_summary_push_covers_every_project(monkeypatch: pytest.MonkeyPatch, two_projects: None) -> None:
    scans = {
        Path("/a"): [finding("aiohttp", "A-1", "3.14.3", "3.14.4"), finding("aiohttp", "A-2", "3.14.3", "3.14.4"),
                     finding("jinja2", "A-3", "2.10", "2.11.3"), finding("flask", "A-4")],
        Path("/b"): [finding("lodash", "A-5", "4.17.15", "4.17.21")],
    }
    pushed: list[tuple[str, str, str]] = []
    monkeypatch.setattr(alert, "scan_project", lambda root: scans[root])
    monkeypatch.setattr(alert, "push_summary",
                        lambda title, message, *, night: pushed.append((title, message, night)) or True)

    result = alert.run_nightly_security_alert()

    assert len(pushed) == 1 and result["alerts_sent"] == 1
    assert pushed[0][1].splitlines() == [
        "5 fixable security advisories in 2 projects.",
        "other: 1 package, lodash 4.17.15 -> 4.17.21",
        "summitflow: 3 packages, aiohttp 3.14.3 -> 3.14.4, jinja2 2.10 -> 2.11.3, +1 more",
    ]
    assert result["summary"] == pushed[0][1]
    assert len(pushed[0][1].splitlines()[0]) <= 180  # the lock-screen part of a Nightshift push


def test_the_same_findings_are_summarized_again_the_next_night(monkeypatch: pytest.MonkeyPatch, two_projects: None) -> None:
    pushed: list[str] = []
    monkeypatch.setattr(alert, "scan_project", lambda root: [finding("jinja2", "A-1")] if root == Path("/a") else [])
    monkeypatch.setattr(alert, "push_summary", lambda title, message, *, night: pushed.append(message) or True)
    alert.run_nightly_security_alert()
    alert.run_nightly_security_alert()
    assert len(pushed) == 2 and pushed[0] == pushed[1]
    assert pushed[0].startswith("1 fixable security advisory in 1 project.")


def test_nothing_is_sent_when_every_project_is_clean(monkeypatch: pytest.MonkeyPatch, two_projects: None) -> None:
    monkeypatch.setattr(alert, "scan_project", lambda root: [])
    monkeypatch.setattr(alert, "push_summary", lambda *args, **kwargs: pytest.fail("clean night must not push"))
    result = alert.run_nightly_security_alert()
    assert result["alerts_sent"] == 0 and "summary" not in result
    assert [row["state"] for row in result["projects"]] == ["scanned", "scanned"]


def test_dry_run_builds_the_summary_without_pushing(monkeypatch: pytest.MonkeyPatch, two_projects: None) -> None:
    monkeypatch.setattr(alert, "scan_project", lambda root: [finding("jinja2", "A-1")])
    monkeypatch.setattr(alert, "push_summary", lambda *args, **kwargs: pytest.fail("dry run must not push"))
    result = alert.run_nightly_security_alert(send=False)
    assert result["alerts_sent"] == 0 and result["summary"].startswith("2 fixable security advisories in 2 projects.")


def test_a_failed_scan_is_skipped_and_the_rest_still_summarized(monkeypatch: pytest.MonkeyPatch, two_projects: None) -> None:
    pushed: list[str] = []
    monkeypatch.setattr(alert, "scan_project", lambda root: None if root == Path("/a") else [finding("lodash", "A-1")])
    monkeypatch.setattr(alert, "push_summary", lambda title, message, *, night: pushed.append(message) or True)
    result = alert.run_nightly_security_alert()
    assert [row["state"] for row in result["projects"]] == ["scan_failed", "scanned"]
    assert len(pushed) == 1 and "other: 1 package" in pushed[0]


def test_a_very_long_summary_stays_inside_the_nightshift_detail_limit() -> None:
    many = {f"project-{n:03d}": [finding(f"package-{n}", f"A-{n}")] for n in range(400)}
    _, message = alert.summarize(many) or ("", "")
    assert len(message) <= 4000 and message.endswith("+ more projects")


def test_push_is_one_nightshift_call_keyed_by_the_night(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    class Done:
        returncode = 0

    monkeypatch.setattr(alert, "_nightshift", lambda: "/bin/nightshift")
    monkeypatch.setattr(alert.subprocess, "run", lambda command, **_: calls.append(command) or Done())
    assert alert.push_summary("Security fixes available", "summary text", night="2026-10-28")
    assert len(calls) == 1
    command = calls[0]
    assert command[:2] == ["/bin/nightshift", "push"] and command[-1] == "summary text"
    assert command[command.index("--key") + 1] == "dependency-advisory-summary:2026-10-28"
    assert command[command.index("--severity") + 1] == "warning"
