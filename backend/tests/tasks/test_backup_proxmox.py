"""Proxmox guests stream into the repository without staging, never stop a guest, and report freshness."""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import pytest

from app.tasks import backup_alerts as alerts
from app.tasks import backup_proxmox as px

if TYPE_CHECKING:
    from app.tasks.backup_restic import ResticConfig

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


def test_streamed_admission_reserves_no_scratch_staging(tmp_path, monkeypatch):
    from app.tasks import backup_repository_runtime as runtime

    monkeypatch.setenv("SF_HOST_RETENTION_PRESSURE_MIN_FREE_GB", "0")
    config = cast("ResticConfig", type("Config", (), {"local_repository": tmp_path})())
    state = {"sources": {"big": {"result": {"logical_bytes": 10**15, "stored_bytes": 1}}}}
    staged = runtime._capacity_admission(config, state, "big", staging_directory=tmp_path)
    streamed = runtime._capacity_admission(config, state, "big", staging_directory=tmp_path, payload_bytes=1, streamed=True)
    assert staged["admitted"] is False and streamed["admitted"] is True and streamed["staging_peak_bytes"] == 0


def test_admission_leaves_out_the_staging_filesystem_when_nothing_more_stages(tmp_path, monkeypatch):
    """Regression: a full scratch filesystem blocked streamed captures that stage zero bytes."""
    from app.tasks import backup_repository_runtime as runtime

    monkeypatch.setenv("SF_HOST_RETENTION_PRESSURE_MIN_FREE_GB", "0")
    config = cast("ResticConfig", type("Config", (), {"local_repository": tmp_path})())
    fresh: dict = {"sources": {}}
    def paths(**kwargs):
        return [path for item in runtime._capacity_admission(config, fresh, "s", staging_directory=tmp_path, **kwargs)["filesystems"] for path in item["paths"]]
    assert paths(streamed=True, payload_bytes=1) == ["repository"]
    assert paths(staged_bytes=10, payload_bytes=10) == ["repository"]
    # Before staging, an unmeasured capture still needs the staging reserve.
    assert paths() == ["staging", "repository"]


def test_save_stream_backs_up_command_stdout_without_a_path(monkeypatch):
    from app.tasks import backup_restic

    calls: list[list[str]] = []
    summary = {"message_type": "summary", "snapshot_id": "a" * 64, "total_bytes_processed": 1000, "data_added": 400, "data_added_packed": 300}

    class Result:
        stdout = json.dumps(summary)

    adapter = backup_restic.ResticAdapter.__new__(backup_restic.ResticAdapter)
    adapter.config = type("Config", (), {"validate": lambda self, **_: None, "hostname": "h"})()
    monkeypatch.setattr(backup_restic, "repository_lock", lambda config: __import__("contextlib").nullcontext())
    monkeypatch.setattr(adapter, "_repository", lambda: {"id": "b" * 64}, raising=False)
    monkeypatch.setattr(adapter, "_command", lambda *args, **_: list(args), raising=False)
    monkeypatch.setattr(adapter, "_run", lambda command, **_: calls.append(command) or Result(), raising=False)
    result = adapter.save_stream("pve-vm-120", ["ssh", "h", "vzdump"], "vzdump-qemu-120.vma", capture={"kind": "proxmox-qemu"}, defer_check=True)
    assert calls[0][calls[0].index("--stdin-from-command"):calls[0].index("--")] == ["--stdin-from-command", "--stdin-filename", "vzdump-qemu-120.vma"]
    assert calls[0][calls[0].index("--") + 1:] == ["ssh", "h", "vzdump"]
    assert result["payload_path"] == "/vzdump-qemu-120.vma" and result["stored_bytes"] == 300
    assert result["verification"]["capture"] == {"kind": "proxmox-qemu", "stream_bytes": 1000}
    with pytest.raises(backup_restic.ResticError):
        adapter.save_stream("x", ["true"], "../escape", capture={})


def _sources_and_rows(monkeypatch, rows_by_source: dict[str, list[dict[str, Any]]], offline: frozenset[str] = frozenset()):
    sources = []
    for index, matcher in enumerate(px.REQUIRED_TARGETS.values()):
        if matcher.startswith("source:"):
            sources.append({"id": matcher.removeprefix("source:"), "path": "/media/x", "enabled": True})
        else:
            sources.append({"id": f"s{index}", "path": matcher + "?via=agent&path=/x" if matcher.endswith("/files") else matcher, "enabled": True})
    monkeypatch.setattr(px.backup_store, "list_sources", lambda: sources)
    monkeypatch.setattr(px.backup_store, "list_backups", lambda source_id, limit: (rows_by_source.get(source_id, []), 0))
    monkeypatch.setattr(alerts, "source_offline_since", lambda source_id: NOW.isoformat() if source_id in offline else None)
    return [source["id"] for source in sources]


def _verified(hours: float, offsite_hours: float | None = None) -> dict[str, Any]:
    offsite: dict[str, Any] = {"status": "verified"}
    if offsite_hours is not None:
        offsite["verified_at"] = (NOW - timedelta(hours=offsite_hours)).isoformat()
    return {"id": "bkp", "status": "completed", "completed_at": NOW - timedelta(hours=hours), "verification_json": {"snapshot_id": "c" * 64, "offsite": offsite}}


def test_freshness_receipt_requires_every_target_offsite_verified_and_recent(monkeypatch, tmp_path):
    monkeypatch.setattr(px, "FRESHNESS_RECEIPT", tmp_path / "proxmox.json")
    ids = _sources_and_rows(monkeypatch, {})
    fresh = {source_id: [_verified(2)] for source_id in ids}
    _sources_and_rows(monkeypatch, fresh)
    assert px.write_freshness_receipt(NOW)["ok"] is True
    assert json.loads((tmp_path / "proxmox.json").read_text())["max_age_hours"] == px.FRESHNESS_HOURS

    config, profiles, _vault, _identity, ominull = ids
    pending = [{"id": "p", "status": "completed_pending_upload", "completed_at": NOW, "verification_json": {"offsite": {"status": "pending"}}}]
    _sources_and_rows(monkeypatch, {**fresh, config: [_verified(40)], profiles: pending, ominull: [_verified(200)]}, offline=frozenset({ominull}))
    receipt = px.freshness_receipt(NOW)
    statuses = [item["status"] for item in receipt["targets"]]
    assert receipt["ok"] is False
    assert statuses == ["stale", "never-verified", "fresh", "fresh", "offline-unchanged"]


def test_neri_guest_disk_is_not_a_required_target():
    assert not any("/qemu/120" in matcher or "neri" in label for label, matcher in px.REQUIRED_TARGETS.items())


def test_receipt_verified_at_is_the_offsite_verification_time(monkeypatch):
    ids = _sources_and_rows(monkeypatch, {})
    rows = {source_id: [_verified(5, offsite_hours=1)] for source_id in ids}
    rows[ids[0]] = [_verified(5)]  # Older rows without an offsite time fall back to the capture time.
    _sources_and_rows(monkeypatch, rows)
    first, second = px.freshness_receipt(NOW)["targets"][:2]
    assert second["verified_at"] == (NOW - timedelta(hours=1)).isoformat() and second["captured_at"] == (NOW - timedelta(hours=5)).isoformat()
    assert first["verified_at"] == first["captured_at"] == (NOW - timedelta(hours=5)).isoformat()
    assert second["age_hours"] == 5.0


def test_offline_guest_stays_fresh_only_up_to_the_cap(monkeypatch, tmp_path):
    monkeypatch.setattr(px, "FRESHNESS_RECEIPT", tmp_path / "proxmox.json")
    ids = _sources_and_rows(monkeypatch, {})
    guest = ids[1]
    limit = px.OFFLINE_FRESHNESS_DAYS * 24
    rows = {source_id: [_verified(2)] for source_id in ids}
    _sources_and_rows(monkeypatch, {**rows, guest: [_verified(limit - 1)]}, offline=frozenset({guest}))
    assert px.freshness_receipt(NOW)["targets"][1]["status"] == "offline-unchanged"
    _sources_and_rows(monkeypatch, {**rows, guest: [_verified(limit + 1)]}, offline=frozenset({guest}))
    receipt = px.freshness_receipt(NOW)
    target = receipt["targets"][1]
    assert receipt["ok"] is False and target["status"] == "stale" and target["fresh"] is False
    assert "offline cap" in target["reason"]
    assert "offline cap" in alerts._proxmox_conditions(NOW)["proxmox-freshness"]["message"]


def test_missing_coverage_raises_a_proxmox_alert(monkeypatch, tmp_path):
    monkeypatch.setattr(px, "FRESHNESS_RECEIPT", tmp_path / "proxmox.json")
    monkeypatch.setattr(px.backup_store, "list_sources", lambda: [])
    conditions = alerts._proxmox_conditions(NOW)
    assert list(conditions) == ["proxmox-freshness"] and "proxmox-gem/config (missing)" in conditions["proxmox-freshness"]["message"]


def test_restore_of_a_guest_returns_the_host_side_command(monkeypatch):
    from app.tasks import backup_restore

    monkeypatch.setattr(px.backup_store, "get_source", lambda source_id: {"path": "proxmox://proxmox-gem/qemu/120"})
    backup = {"verification_json": {"snapshot_id": "d" * 64, "payload_path": "/vzdump-qemu-120.vma", "capture": {"kind": "proxmox-qemu", "host": "proxmox-gem"}}}
    monkeypatch.setattr(backup_restore.backup_store, "get_backup", lambda backup_id: backup)
    result = backup_restore.restore_backup(project_id="x", backup_id="bkp", source_id="pve-vm-120")
    assert result["status"] == "failed" and "| ssh proxmox-gem qmrestore - <new-vmid>" in result["error"]


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


class _StreamAdapter:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.calls: list[tuple[str, bool]] = []

    def restore(self, snapshot: str, destination: Path, *, remote: bool = False) -> dict[str, Any]:
        self.calls.append((snapshot, remote))
        target = destination / "pve-cluster-config.sql"
        target.write_bytes(self.payload)
        return {"status": "completed", "payload_file": str(target)}


@pytest.mark.parametrize(("payload", "error"), [(b"PRAGMA foreign_keys=OFF\n", None), (b"garbage!!!!!!!!!!!!!!!!!", "format header"), (b"PRAGMA", "bytes")])
def test_stream_restore_returns_the_dump_file_and_proves_size_and_format(monkeypatch, tmp_path, payload, error):
    from app.tasks import backup_repository_runtime as runtime
    from app.tasks import backup_restic

    adapter = _StreamAdapter(payload)
    monkeypatch.setattr(runtime, "_backup_environment", lambda _backup: {})
    monkeypatch.setattr(backup_restic.ResticConfig, "from_env", staticmethod(lambda _env: None))
    monkeypatch.setattr(backup_restic, "ResticAdapter", lambda _config: adapter)
    backup = {"verification_json": {"snapshot_id": "a" * 64, "remote_snapshot_id": "b" * 64, "payload_path": "/pve-cluster-config.sql",
                                    "capture": {"kind": "proxmox-config", "host": "proxmox-gem", "stream_bytes": 24}}}
    if error:
        with pytest.raises(RuntimeError, match=error):
            px.restore_stream_isolated(backup, tmp_path, remote=True)
        return
    result = px.restore_stream_isolated(backup, tmp_path, remote=True)
    assert adapter.calls == [("b" * 64, True)]
    assert Path(result["payload_file"]).read_bytes() == payload
    assert result["size_bytes"] == 24 and "sqlite3" in result["next_step"]


def test_receipt_carries_the_monthly_restore_drill(monkeypatch):
    ids = _sources_and_rows(monkeypatch, {})
    _sources_and_rows(monkeypatch, {source_id: [_verified(2)] for source_id in ids})
    sources = px.backup_store.list_sources()
    sources[-1].update(last_drill_ok=True, last_drill_at=NOW - timedelta(days=2))
    targets = px.freshness_receipt(NOW)["targets"]
    assert targets[-1]["restore_drill_ok"] is True and targets[-1]["restore_drill_at"] == (NOW - timedelta(days=2)).isoformat()
    assert targets[0]["restore_drill_ok"] is None and targets[0]["restore_drill_at"] is None
