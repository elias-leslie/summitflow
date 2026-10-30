"""Nightly security alert: fixable runtime advisories only, one push per new finding."""
from __future__ import annotations

import json
import os
import pwd
import subprocess
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


def text(notice: dict[str, Any]) -> str:
    return "\n".join(part for part in (notice["body"], notice.get("detail")) if part)


def finding(package_name: str, advisory: str, version: str = "1.0", fixed: str = "1.1") -> dict[str, str]:
    return {"package": package_name, "version": version, "fixed": fixed, "advisory": advisory, "lockfile": "uv.lock"}


def test_one_summary_push_covers_every_project(monkeypatch: pytest.MonkeyPatch, two_projects: None) -> None:
    scans = {
        Path("/a"): [finding("aiohttp", "A-1", "3.14.3", "3.14.4"), finding("aiohttp", "A-2", "3.14.3", "3.14.4"),
                     finding("jinja2", "A-3", "2.10", "2.11.3"), finding("flask", "A-4")],
        Path("/b"): [finding("lodash", "A-5", "4.17.15", "4.17.21")],
    }
    pushed: list[dict[str, Any]] = []
    monkeypatch.setattr(alert, "scan_project", lambda root: scans[root])
    monkeypatch.setattr(alert, "push_summary", lambda notice: pushed.append(notice) or True)

    result = alert.run_nightly_security_alert()

    assert len(pushed) == 1 and result["alerts_sent"] == 1
    assert text(pushed[0]).splitlines() == [
        "5 fixable security advisories in 2 projects.",
        "other: 1 package, lodash 4.17.15 -> 4.17.21",
        "summitflow: 3 packages, aiohttp 3.14.3 -> 3.14.4, jinja2 2.10 -> 2.11.3, +1 more",
    ]
    assert result["summary"] == text(pushed[0])
    assert len(pushed[0]["body"]) <= 180  # the lock-screen part of a Nightshift push
    assert pushed[0]["open"] == "https://dev.summitflow.dev/git"  # two projects: the Git overview


def test_the_same_findings_are_summarized_again_the_next_night(monkeypatch: pytest.MonkeyPatch, two_projects: None) -> None:
    pushed: list[str] = []
    monkeypatch.setattr(alert, "scan_project", lambda root: [finding("jinja2", "A-1")] if root == Path("/a") else [])
    monkeypatch.setattr(alert, "push_summary", lambda notice: pushed.append(text(notice)) or True)
    alert.run_nightly_security_alert()
    alert.run_nightly_security_alert()
    assert len(pushed) == 2 and pushed[0] == pushed[1]
    assert pushed[0].startswith("1 fixable security advisory in 1 project.")


def test_nothing_is_sent_when_every_project_is_clean(monkeypatch: pytest.MonkeyPatch, two_projects: None) -> None:
    resolved: list[bool] = []
    monkeypatch.setattr(alert, "scan_project", lambda root: [])
    monkeypatch.setattr(alert, "push_summary", lambda *args, **kwargs: pytest.fail("clean night must not push"))
    monkeypatch.setattr(alert, "resolve_summary", lambda: resolved.append(True) or True)
    result = alert.run_nightly_security_alert()
    assert result["alerts_sent"] == 0 and "summary" not in result
    assert [row["state"] for row in result["projects"]] == ["scanned", "scanned"]
    assert resolved == [True] and result["resolved"] is True  # a clean night says the advisories are over


def test_dry_run_builds_the_summary_without_pushing(monkeypatch: pytest.MonkeyPatch, two_projects: None) -> None:
    monkeypatch.setattr(alert, "scan_project", lambda root: [finding("jinja2", "A-1")])
    monkeypatch.setattr(alert, "push_summary", lambda *args, **kwargs: pytest.fail("dry run must not push"))
    result = alert.run_nightly_security_alert(send=False)
    assert result["alerts_sent"] == 0 and result["summary"].startswith("2 fixable security advisories in 2 projects.")


def test_a_failed_scan_is_skipped_and_the_rest_still_summarized(monkeypatch: pytest.MonkeyPatch, two_projects: None) -> None:
    pushed: list[str] = []
    monkeypatch.setattr(alert, "scan_project", lambda root: None if root == Path("/a") else [finding("lodash", "A-1")])
    monkeypatch.setattr(alert, "push_summary", lambda notice: pushed.append(text(notice)) or True)
    result = alert.run_nightly_security_alert()
    assert [row["state"] for row in result["projects"]] == ["scan_failed", "scanned"]
    assert len(pushed) == 1 and "other: 1 package" in pushed[0]


def test_a_clean_night_with_a_failed_scan_does_not_call_it_over(monkeypatch: pytest.MonkeyPatch,
                                                                two_projects: None) -> None:
    monkeypatch.setattr(alert, "scan_project", lambda root: None if root == Path("/a") else [])
    monkeypatch.setattr(alert, "resolve_summary", lambda: pytest.fail("unknown is not clean"))
    assert alert.run_nightly_security_alert()["resolved"] is False


def test_a_very_long_summary_stays_inside_the_nightshift_detail_limit() -> None:
    many = {f"project-{n:03d}": [finding(f"package-{n}", f"A-{n}")] for n in range(400)}
    _, message = alert.summarize(many) or ("", "")
    assert len(message) <= 4000 and message.endswith("+ more projects")


def test_push_is_one_nightshift_notice_on_stdin(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[list[str], str | None]] = []

    class Done:
        returncode = 0

    monkeypatch.setattr(alert, "_nightshift", lambda: "/bin/nightshift")
    monkeypatch.setattr(alert.subprocess, "run", lambda command, **kw: calls.append((command, kw.get("input"))) or Done())
    notice = alert.build_notice("Security fixes available", "1 fixable security advisory in 1 project.\naico: x",
                                ["aico"])
    assert alert.push_summary(notice)
    assert alert.resolve_summary()
    (push, stdin), (resolve, _) = calls
    assert push == ["/bin/nightshift", "push", "--json"] and json.loads(stdin or "") == notice
    assert resolve[:3] == ["/bin/nightshift", "resolve", alert.NOTICE_KEY]
    assert notice["open"] == "https://dev.summitflow.dev/projects/aico/git"  # one project: its own Git page
    assert notice["push"] == "tray" and notice["actions"] == ["look-into"] and notice["primary"] == "look-into"


def _installed_nightshift() -> str | None:
    """The task's own lookup, else the account's real ~/.local/bin (isolated acceptance runs with another HOME)."""
    found = alert._nightshift()
    fallback = Path(pwd.getpwuid(os.getuid()).pw_dir) / ".local" / "bin" / "nightshift"
    return found or (str(fallback) if fallback.is_file() else None)


@pytest.mark.skipif(_installed_nightshift() is None, reason="nightshift is not installed here")
def test_the_real_notice_passes_the_nightshift_contract(monkeypatch: pytest.MonkeyPatch, two_projects: None) -> None:
    """Conformance: the notice the nightly run really builds is accepted by nightshift push --json --dry-run."""
    pushed: list[dict[str, Any]] = []
    many = {Path("/a"): [finding(f"package-{n}", f"A-{n}") for n in range(60)], Path("/b"): [finding("lodash", "B")]}
    monkeypatch.setattr(alert, "scan_project", lambda root: many[root])
    monkeypatch.setattr(alert, "push_summary", lambda notice: pushed.append(notice) or True)
    alert.run_nightly_security_alert()
    checked = subprocess.run([str(_installed_nightshift()), "push", "--json", "--dry-run"], input=json.dumps(pushed[0]),
                             capture_output=True, text=True, timeout=60, check=False)
    assert checked.returncode == 0, checked.stderr
