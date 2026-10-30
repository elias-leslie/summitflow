"""Proxmox guests stream into the Drive repository without staging, never stop a guest, and report freshness."""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from app.tasks import backup_alerts as alerts
from app.tasks import backup_offsite
from app.tasks import backup_proxmox as px

NOW = datetime(2026, 10, 11, 15, 0, tzinfo=UTC)
_RESOLVE_ALIAS = px._resolve_alias  # The real one; the autouse fixture replaces it.


def test_paths_parse_only_known_target_shapes():
    assert px.parse_target("proxmox://proxmox-gem/qemu/100") == px.ProxmoxTarget("proxmox-gem", "qemu", 100)
    assert px.ProxmoxTarget("proxmox-gem", "config").filename == "pve-cluster-config.sql"
    assert px.parse_target("proxmox://proxmox-gem/lxc/140") == px.ProxmoxTarget("proxmox-gem", "lxc", 140)
    assert px.ProxmoxTarget("proxmox-gem", "lxc", 140).filename == "vzdump-lxc-140.tar"
    for bad in ("proxmox://h/qemu/0", "proxmox://h/qemu/100;rm", "proxmox://-oProxyCommand=x/config", "/srv/x", None):
        assert px.parse_target(bad) is None


@pytest.fixture(autouse=True)
def backup_key(tmp_path, monkeypatch):
    """SummitFlow's own PVE key; the owner's ssh alias only supplies the address."""
    (tmp_path / px.PVE_BACKUP_KEY).write_text("")
    monkeypatch.setattr(px, "backup_key_directory", lambda: tmp_path)
    monkeypatch.setattr(px, "_resolve_alias", lambda host: ("192.0.2.39", "root", "22"))
    return tmp_path / px.PVE_BACKUP_KEY


def _guest(monkeypatch, status: str, *, prior: bool, thin: float | None = 50.0, kind: str = "qemu", vmid: int = 120):
    resources = [{"vmid": vmid, "type": kind, "status": status, "node": "davion-gem", "name": "g", "maxdisk": 35 * 1024**3, "template": 0}]
    monkeypatch.setattr(px, "_ssh", lambda host, *args, **_: json.dumps(resources) if args == ("guests",) else f" {thin}\n")
    monkeypatch.setattr(px, "_has_completed_backup", lambda source_id: prior)


def _verb(command: list[str]) -> list[str]:
    """What follows the ssh destination: the whole request the Proxmox host receives."""
    assert command[:3] == ["ssh", "-F", "/dev/null"]
    return command[command.index("root@192.0.2.39") + 1:]


def test_proxmox_host_is_reached_only_with_summitflows_own_key(backup_key):
    command = px.pve_ssh("proxmox-gem")
    assert command[command.index("-i") + 1] == str(backup_key)
    assert {"IdentitiesOnly=yes", "IdentityAgent=none", "BatchMode=yes"} <= set(command)
    assert command[-1] == "root@192.0.2.39" and "proxmox-gem" not in command  # the alias's IdentityFile (owner key) is never read
    backup_key.unlink()
    with pytest.raises(RuntimeError, match=r"install\.sh"):
        px.pve_ssh("proxmox-gem")


def test_alias_resolution_takes_only_the_address_user_and_port(monkeypatch):
    output = "user root\nhostname 192.168.86.39\nport 22\nidentityfile ~/.ssh/id_ed25519_davion_gem\n"
    monkeypatch.setattr(px.subprocess, "run", lambda argv, **_: subprocess.CompletedProcess(argv, 0, output, ""))
    assert _RESOLVE_ALIAS.__wrapped__("proxmox-gem") == ("192.168.86.39", "root", "22")


def test_file_targets_parse_only_safe_selections():
    agent = px.parse_target("proxmox://proxmox-gem/qemu/100/files?via=agent&path=/home/u/profiles&exclude=Code+Cache")
    assert agent is not None and agent.files == px.FileSelection("agent", ("/home/u/profiles",), ("Code Cache",))
    assert agent.filename == "files-qemu-100.tar.gz"
    chrome = px.parse_target("proxmox://proxmox-gem/qemu/100/files?via=agent&path=/p&exclude=Safe+Browsing&exclude=BrowserMetrics%2A&exclude=Dawn%2ACache&exclude=%2ACache")
    assert chrome is not None and chrome.files is not None and chrome.files.excludes == ("Safe Browsing", "BrowserMetrics*", "Dawn*Cache", "*Cache")
    host = px.parse_target("proxmox://proxmox-gem/host/files?path=/vault/identity")
    assert host is not None and host.files == px.FileSelection("host", ("/vault/identity",)) and host.filename == "files-host.tar"
    for bad in (
        "proxmox://h/qemu/100/files?via=agent",  # no path
        "proxmox://h/qemu/100/files?via=pct&path=/x",  # pct is for containers
        "proxmox://h/lxc/140/files?via=agent&path=/x",  # the agent is for VMs
        "proxmox://h/qemu/100/files?via=agent&path=/a/../etc",
        "proxmox://h/qemu/100/files?via=agent&path=relative",
        "proxmox://h/qemu/100/files?via=a;b&path=/x",
        "proxmox://h/qemu/100/files?via=agent&path=/x&other=1",
        "proxmox://h/host/files?via=neri-lab&path=/x",
        "proxmox://h/qemu/100?path=/x",
    ):
        assert px.parse_target(bad) is None, bad


def test_file_captures_send_the_host_a_verb_never_a_command(monkeypatch):
    _guest(monkeypatch, "running", prior=True, vmid=100)
    path = "proxmox://proxmox-gem/qemu/100/files?via=agent&path=/home/u/p&exclude=Cache"
    agent = px.plan_capture("vm100", path)
    assert _verb(agent["command"]) == ["capture", "vm100", px.path_digest(path)]
    assert agent["capture"]["compressed"] is True and agent["capture"]["node"] == "davion-gem"
    _guest(monkeypatch, "running", prior=True, kind="lxc", vmid=140)
    path = "proxmox://proxmox-gem/lxc/140/files?via=pct&path=/srv/data"
    assert _verb(px.plan_capture("ct140", path)["command"]) == ["capture", "ct140", px.path_digest(path)]
    host = "proxmox://proxmox-gem/host/files?path=/vault/identity"
    assert _verb(px.plan_capture("files", host)["command"]) == ["capture", "files", px.path_digest(host)]
    # No ssh alias via: an alias such as proxmox-gem may carry the owner's root key, so it is refused before any ssh.
    for alias in ("neri-lab", "proxmox-gem", "davion-gem"):
        with pytest.raises(RuntimeError, match="Invalid Proxmox source path"):
            px.plan_capture("ct140", f"proxmox://proxmox-gem/lxc/140/files?via={alias}&path=/var/lib/pve-cluster")
        assert px.dispatcher_entry(f"proxmox://proxmox-gem/qemu/100/files?via={alias}&path=/srv") is None
    _guest(monkeypatch, "stopped", prior=False, kind="lxc", vmid=140)
    with pytest.raises(px.ProxmoxGuestOffline):
        px.plan_capture("ct140", "proxmox://proxmox-gem/lxc/140/files?via=pct&path=/srv/data")


def test_running_guest_streams_uncompressed_in_snapshot_mode(monkeypatch):
    _guest(monkeypatch, "running", prior=True)
    plan = px.plan_capture("pve-vm-120", "proxmox://proxmox-gem/qemu/120")
    assert _verb(plan["command"]) == ["capture", "pve-vm-120", px.path_digest("proxmox://proxmox-gem/qemu/120")]
    assert plan["capture"]["mode"] == "snapshot" and plan["estimated_bytes"] == 35 * 1024**3


def test_stopped_guest_is_offline_once_backed_up_but_captured_first(monkeypatch):
    _guest(monkeypatch, "stopped", prior=True, kind="lxc", vmid=140)
    with pytest.raises(px.ProxmoxGuestOffline):
        px.plan_capture("pve-ct-140", "proxmox://proxmox-gem/lxc/140")
    _guest(monkeypatch, "stopped", prior=False, kind="lxc", vmid=140)
    plan = px.plan_capture("pve-ct-140", "proxmox://proxmox-gem/lxc/140")
    assert plan["capture"]["mode"] == "snapshot" and _verb(plan["command"])[0] == "capture"


def test_reused_guest_id_is_not_silently_excluded_and_full_thin_pool_is_refused(monkeypatch):
    # VM 101 was destroyed; a future guest reusing its id is backed up like any other.
    _guest(monkeypatch, "running", prior=True, vmid=101)
    assert px.plan_capture("x", "proxmox://proxmox-gem/qemu/101")["capture"]["vmid"] == 101
    _guest(monkeypatch, "running", prior=True, kind="lxc", vmid=140, thin=98.4)
    with pytest.raises(RuntimeError, match="insufficient host-policy headroom"):
        px.plan_capture("pve-ct-140", "proxmox://proxmox-gem/lxc/140")


def test_cluster_config_is_dumped_by_the_host_without_private_keys():
    plan = px.plan_capture("pve-cluster-config", "proxmox://proxmox-gem/config")
    assert _verb(plan["command"]) == ["capture", "pve-cluster-config", px.path_digest("proxmox://proxmox-gem/config")]
    assert plan["capture"]["excludes"] == ["priv/", "*.key"]


def _covered(monkeypatch, jobs: dict[str, dict[str, Any]], last_jobs: dict[str, dict[str, Any]] | None = None) -> list[str]:
    """Register one source per required target; ``jobs`` is the Drive job record by source id."""
    sources = []
    for index, matcher in enumerate(px.REQUIRED_TARGETS.values()):
        if matcher.startswith("source:"):
            sources.append({"id": matcher.removeprefix("source:"), "path": "/media/x", "enabled": True})
        else:
            sources.append({"id": f"s{index}", "path": matcher + "?via=agent&path=/x" if matcher.endswith("/files") else matcher, "enabled": True})
    monkeypatch.setattr(px.backup_store, "list_sources", lambda: sources)
    monkeypatch.setattr(backup_offsite, "read_state", lambda: {"jobs": jobs, "last_run": {"jobs": last_jobs or {}}})
    return [source["id"] for source in sources]


def _job(hours: float) -> dict[str, Any]:
    return {"time": (NOW - timedelta(hours=hours)).isoformat(), "snapshot_id": "c" * 64}


def test_freshness_receipt_requires_every_target_to_have_a_recent_drive_copy(monkeypatch, tmp_path):
    monkeypatch.setattr(px, "FRESHNESS_RECEIPT", tmp_path / "proxmox.json")
    ids = _covered(monkeypatch, {})
    fresh = {source_id: _job(2) for source_id in ids}
    _covered(monkeypatch, fresh)
    assert px.write_freshness_receipt(NOW)["ok"] is True
    assert json.loads((tmp_path / "proxmox.json").read_text())["max_age_hours"] == px.FRESHNESS_HOURS

    config, profiles, _vault, _identity, ominull = ids
    _covered(monkeypatch, {**{k: v for k, v in fresh.items() if k != profiles}, config: _job(40), ominull: _job(200)},
             {ominull: {"status": "offline", "offline_since": (NOW - timedelta(hours=199)).isoformat()}})
    receipt = px.freshness_receipt(NOW)
    assert receipt["ok"] is False
    assert [item["status"] for item in receipt["targets"]] == ["stale", "never-verified", "fresh", "fresh", "offline-unchanged"]


def test_neri_guest_disk_is_not_a_required_target():
    assert not any("/qemu/120" in matcher or "neri" in label for label, matcher in px.REQUIRED_TARGETS.items())


def test_the_receipt_time_is_when_the_drive_job_saved_the_copy(monkeypatch):
    ids = _covered(monkeypatch, {})
    _covered(monkeypatch, {source_id: _job(5) for source_id in ids})
    first = px.freshness_receipt(NOW)["targets"][0]
    assert first["verified_at"] == first["captured_at"] == (NOW - timedelta(hours=5)).isoformat() and first["age_hours"] == 5.0


def test_a_guest_off_since_its_last_copy_stays_current_however_long(monkeypatch, tmp_path):
    monkeypatch.setattr(px, "FRESHNESS_RECEIPT", tmp_path / "proxmox.json")
    ids = _covered(monkeypatch, {})
    guest = ids[1]
    rows = {source_id: _job(2) for source_id in ids}
    since = (NOW - timedelta(days=59)).isoformat()
    _covered(monkeypatch, {**rows, guest: _job(60 * 24)}, {guest: {"status": "offline", "offline_since": since}})
    target = px.freshness_receipt(NOW)["targets"][1]
    assert target["status"] == "offline-unchanged" and target["fresh"] is True and target["offline_since"] == since
    # Off, but it may have run since its last copy without being copied: not known to be current.
    _covered(monkeypatch, {**rows, guest: _job(40)}, {guest: {"status": "offline", "offline_since": None}})
    receipt = px.freshness_receipt(NOW)
    target = receipt["targets"][1]
    assert receipt["ok"] is False and target["status"] == "stale" and target["fresh"] is False
    assert "may have run since its last copy" in target["reason"]
    assert "may have run since its last copy" in alerts._proxmox_conditions(NOW)["proxmox-freshness"]["message"]


def test_missing_coverage_raises_a_proxmox_alert(monkeypatch, tmp_path):
    monkeypatch.setattr(px, "FRESHNESS_RECEIPT", tmp_path / "proxmox.json")
    monkeypatch.setattr(px.backup_store, "list_sources", lambda: [])
    monkeypatch.setattr(backup_offsite, "read_state", lambda: {})
    conditions = alerts._proxmox_conditions(NOW)
    assert list(conditions) == ["proxmox-freshness"] and "proxmox-gem/config (missing)" in conditions["proxmox-freshness"]["message"]


def test_restore_of_a_guest_is_the_host_side_command():
    backup = {"verification_json": {"snapshot_id": "d" * 64, "payload_path": "/vzdump-qemu-120.vma", "capture": {"kind": "proxmox-qemu", "host": "proxmox-gem"}}}
    assert "| ssh proxmox-gem qmrestore - <new-vmid>" in px.restore_instructions(backup)


def test_receipt_path_is_stable():
    expected = Path.home() / ".local/state/summitflow/backup-freshness/proxmox.json"
    assert expected == px.FRESHNESS_RECEIPT


def test_coverage_matches_whole_path_segments_only():
    sources = [{"id": "vm1200", "path": "proxmox://proxmox-gem/qemu/1200", "enabled": True}]
    assert px._covering_source("proxmox://proxmox-gem/qemu/120", sources) is None
    sources.append({"id": "vm120", "path": "proxmox://proxmox-gem/qemu/120", "enabled": True})
    assert (px._covering_source("proxmox://proxmox-gem/qemu/120", sources) or {}).get("id") == "vm120"
    files = [{"id": "f", "path": "proxmox://proxmox-gem/host/files?path=/x", "enabled": True}]
    assert (px._covering_source("proxmox://proxmox-gem/host/files", files) or {}).get("id") == "f"
