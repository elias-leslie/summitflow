from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from monitor_observe import (
    ObserveQueryError,
    connections,
    hardware,
    inventory,
    logs,
    query_apps,
    query_connections,
    query_drivers,
    query_logs,
    query_sensors,
    query_startup,
    query_system_info,
    query_users,
)


def _bounded(payload: dict, budget: int = 4096) -> None:
    assert set(payload) == {"schema", "generated_at", "requested", "coverage", "items",
                            "next_cursor", "truncated", "errors"}
    assert payload["schema"] == 1
    assert len(json.dumps(payload, separators=(",", ":")).encode()) <= budget


def test_logs_allowlist_redaction_pagination_and_command(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(logs, "_services", lambda: {"backend": "summitflow-backend.service"})
    seen = []

    def run(argv: list[str]):
        seen.append(argv)
        stamp = str(int(datetime.now(UTC).timestamp() * 1_000_000) - 1_000_000)
        rows = [
            {"__REALTIME_TIMESTAMP": stamp, "__CURSOR": f"s={n}",
             "PRIORITY": "3", "MESSAGE": f"password=secret{n} Authorization: Bearer abc{n} https://me:pwd@host"}
            for n in range(3)
        ]
        return b"\n".join(json.dumps(row).encode() for row in rows) + b"\n", b"", 0, False

    monkeypatch.setattr(logs, "_run", run)
    result = query_logs("backend", limit=2)
    _bounded(result)
    assert result["truncated"] and result["next_cursor"] == "s=1"
    assert all("secret" not in row["value"]["message"] for row in result["items"])
    assert all("abc" not in row["value"]["message"] for row in result["items"])
    assert "--unit=summitflow-backend.service" in seen[0]
    assert "--reverse" in seen[0]
    assert all(part != "--unit=backend" for part in seen[0])
    query_logs("backend", cursor="s=1", limit=2)
    assert "--cursor=s=1" in seen[1]
    assert not any(arg.startswith("--since=") for arg in seen[1])
    with pytest.raises(ObserveQueryError):
        query_logs("ssh.service")
    with pytest.raises(ObserveQueryError):
        query_logs("backend", priority=9)
    with pytest.raises(ObserveQueryError):
        query_logs("backend", cursor="bad\narg")


def test_log_source_errors_are_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(logs, "_services", lambda: {"backend": "summitflow-backend.service"})
    monkeypatch.setattr(logs, "_run", lambda _argv: (b"", b"permission denied", 1, False))
    denied = query_logs("backend")
    assert denied["coverage"]["availability"] == "permission_denied"
    monkeypatch.setattr(logs, "_run", lambda _argv: (_ for _ in ()).throw(TimeoutError()))
    timeout = query_logs("backend")
    assert timeout["errors"][0]["code"] == "timeout"


def test_log_identity_and_capture_failures_are_explicit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(logs, "IDENTITY_PATH", tmp_path / "missing.json")
    missing = query_logs("backend")
    assert missing["coverage"]["availability"] == "unsupported"
    monkeypatch.setattr(logs, "_services", lambda: {"backend": "summitflow-backend.service"})
    monkeypatch.setattr(logs, "_run", lambda _argv: (b"", b"", -9, True))
    clipped = query_logs("backend")
    assert clipped["truncated"]
    assert clipped["errors"][0]["code"] == "source_truncated"


def test_sensors_fixture_and_unsupported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(hardware.shutil, "which", lambda _name: None)
    hw = tmp_path / "hwmon"
    chip = hw / "hwmon0"
    chip.mkdir(parents=True)
    (chip / "name").write_text("coretemp")
    (chip / "temp1_input").write_text("42000")
    freq = tmp_path / "cpufreq"
    policy = freq / "policy0"
    policy.mkdir(parents=True)
    (policy / "scaling_cur_freq").write_text("2400000")
    monkeypatch.setattr(hardware, "HWMON", hw)
    monkeypatch.setattr(hardware, "CPUFREQ", freq)
    monkeypatch.setattr(hardware, "POWER_SUPPLY", tmp_path / "absent")
    result = query_sensors()
    _bounded(result)
    assert any(row["value"].get("reading") == 42 for row in result["items"])
    assert result["coverage"]["providers"]["power_supply"] == "unsupported"


def test_sensor_scan_caps_are_reported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(hardware.shutil, "which", lambda _name: None)
    hw = tmp_path / "hwmon"
    for number in range(3):
        chip = hw / f"hwmon{number}"
        chip.mkdir(parents=True)
        (chip / "temp1_input").write_text("1000")
    monkeypatch.setattr(hardware, "HWMON", hw)
    monkeypatch.setattr(hardware, "CPUFREQ", tmp_path / "absent1")
    monkeypatch.setattr(hardware, "POWER_SUPPLY", tmp_path / "absent2")
    monkeypatch.setattr(hardware, "MAX_DEVICES", 2)
    result = query_sensors()
    assert result["truncated"]
    assert result["coverage"]["scan"]["hwmon"] == {"devices_seen": 3, "devices_scanned": 2,
                                                  "files_seen": 2, "files_scanned": 2}
    assert any(row["code"] == "source_truncated" for row in result["errors"])


def test_gpu_sensor_provider_uses_fixed_query_and_no_serial(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(hardware.shutil, "which", lambda _name: "/usr/bin/nvidia-smi")
    captured = []

    def run(argv: list[str]):
        captured.append(argv)
        return b"0, Test GPU, 40, 25, 100, 200, N/A\n", b"", 0, False

    monkeypatch.setattr(hardware, "_run", run)
    monkeypatch.setattr(hardware, "HWMON", tmp_path / "absent1")
    monkeypatch.setattr(hardware, "CPUFREQ", tmp_path / "absent2")
    monkeypatch.setattr(hardware, "POWER_SUPPLY", tmp_path / "absent3")
    result = query_sensors()
    assert result["coverage"]["providers"]["nvidia_gpu"] == "ok"
    assert len(result["items"]) == 5
    assert result["items"][0]["value"] == {"gpu_index": "0", "metric": "temperature.gpu", "reading": 40.0}
    assert result["items"][-1]["availability"] == "unsupported"
    assert "uuid" not in json.dumps(result).lower()
    assert captured[0][0] == "nvidia-smi"
    assert all("--query-gpu=" not in part or "serial" not in part for part in captured[0])


def test_connections_redacted_and_optional_owner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "tcp").write_text(
        "sl local_address rem_address st tx rx tr tm retr uid timeout inode\n"
        "0: 0100007F:1F90 0200007F:1234 01 0 0 0 1000 0 999\n"
    )
    monkeypatch.setattr(connections, "PROC_NET", tmp_path)
    monkeypatch.setattr(connections, "_owner_map", lambda inodes: ({"999": 123}, "ok", {}))
    result = query_connections(include_process=True)
    _bounded(result)
    assert result["items"][0]["value"]["local"] == "[REDACTED]"
    assert result["items"][0]["value"]["pid"] == 123
    assert result["coverage"]["tables"]["tcp6"] == "unsupported"
    raw = query_connections(include_addresses=True)
    assert raw["items"][0]["value"]["local"] == "127.0.0.1:8080"


def test_connection_owner_cap_never_implies_unknown_owner_is_known(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "tcp").write_text(
        "header\n0: 0100007F:1F90 0200007F:1234 01 0 0 0 1000 0 999\n"
    )
    monkeypatch.setattr(connections, "PROC_NET", tmp_path)
    monkeypatch.setattr(connections, "_owner_map", lambda inodes: ({}, "not_collected",
                                                   {"pids_seen": 300, "pids_scanned": 256,
                                                    "fds_scanned": 20, "scan_capped": True}))
    result = query_connections(include_process=True)
    assert result["items"][0]["value"]["process_availability"] == "not_collected"
    assert result["coverage"]["process_scan"]["scan_capped"]
    assert result["truncated"]
    assert any(row["code"] == "source_truncated" for row in result["errors"])


def test_users_active_sessions_are_bounded_and_private(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    passwd = tmp_path / "passwd"
    passwd.write_text("alice:x:1000:1000::/home/alice:/bin/bash\n")
    monkeypatch.setattr(inventory, "PASSWD", passwd)
    seen: list[list[str]] = []

    def run(argv: list[str]):
        seen.append(argv)
        return (b"9 1000 alice seat0 tty2 active yes 10min ago\n"
                b"c2 1001 bob - pts/1 online no -\n", b"", 0, False)

    monkeypatch.setattr(inventory, "_run", run)
    result = query_users(limit=10)
    _bounded(result)
    assert result["coverage"]["accounts"] == "ok"
    assert result["coverage"]["sessions"] == "ok"
    assert result["coverage"]["active_sessions_seen"] == 1
    assert [row["value"]["kind"] for row in result["items"]] == ["active_session", "account"]
    assert result["items"][0]["value"] == {"kind": "active_session", "uid": 1000, "state": "active"}
    serialized = json.dumps(result)
    assert all(secret not in serialized for secret in ("tty2", "pts/1", "seat0", "10min", "c2"))
    assert seen == [["loginctl", "list-sessions", "--no-legend", "--no-pager", "--no-ask-password"]]


def test_users_session_failure_and_cap_are_explicit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    passwd = tmp_path / "passwd"
    passwd.write_text("alice:x:1000:1000::/home/alice:/bin/bash\n")
    monkeypatch.setattr(inventory, "PASSWD", passwd)
    monkeypatch.setattr(inventory, "_run", lambda _argv: (_ for _ in ()).throw(PermissionError()))
    denied = query_users()
    assert denied["coverage"]["availability"] == "partial"
    assert denied["coverage"]["sessions"] == "permission_denied"
    assert denied["items"][0]["value"]["kind"] == "account"
    monkeypatch.setattr(inventory, "MAX_SESSION_ROWS", 1)
    monkeypatch.setattr(inventory, "_run", lambda _argv: (
        b"1 1000 alice seat0 tty2 active no -\n2 1001 bob seat0 tty3 active no -\n", b"", 0, False))
    capped = query_users()
    assert capped["coverage"]["sessions_capped"] is True
    assert capped["coverage"]["sessions"] == "partial"
    assert capped["truncated"]
    assert any(row["code"] == "source_truncated" for row in capped["errors"])


def test_startup_desktop_metadata_only_and_source_coverage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    system_dir = tmp_path / "system"
    user_dir = tmp_path / "user"
    system_dir.mkdir()
    user_dir.mkdir()
    (system_dir / "at-spi.desktop").write_text(
        "[Desktop Entry]\nName=Accessibility Bridge\nHidden=false\nOnlyShowIn=GNOME;\n"
        "Exec=token=secret-value\n"
    )
    (user_dir / "hidden.desktop").write_text("[Desktop Entry]\nName=Hidden App\nHidden=true\n")
    (user_dir / "link.desktop").symlink_to(system_dir / "at-spi.desktop")
    monkeypatch.setattr(inventory, "AUTOSTART_DIRS", (system_dir, user_dir))
    monkeypatch.setattr(inventory, "_run", lambda _argv: (b"worker.service enabled\n", b"", 0, False))
    result = query_startup(limit=10)
    _bounded(result)
    assert result["coverage"]["providers"] == {"systemd_user": "ok", "desktop_autostart": "ok"}
    assert [row["value"]["kind"] for row in result["items"]] == [
        "desktop_autostart", "desktop_autostart", "systemd_user_unit"]
    assert result["items"][0]["value"] == {
        "kind": "desktop_autostart", "name": "Accessibility Bridge", "hidden": False,
        "only_show_in": "GNOME;"}
    assert "secret-value" not in json.dumps(result)
    assert "link.desktop" not in json.dumps(result)


def test_inventory_sources_and_command_failures(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    passwd = tmp_path / "passwd"
    passwd.write_text("alice:x:1000:1000::/home/alice:/bin/bash\n")
    modules = tmp_path / "modules"
    modules.write_text("i915 1234 1 - Live 0x0\n")
    release = tmp_path / "os-release"
    release.write_text('NAME="Test OS"\nVERSION_ID="1"\n')
    monkeypatch.setattr(inventory, "PASSWD", passwd)
    monkeypatch.setattr(inventory, "MODULES", modules)
    monkeypatch.setattr(inventory, "OS_RELEASE", release)
    monkeypatch.setattr(inventory, "_run", lambda _argv: (b"", b"", 0, False))
    assert query_users()["items"][0]["value"]["name"] == "alice"
    assert query_drivers()["items"][0]["value"]["module"] == "i915"
    assert query_system_info()["items"][0]["value"]["os_release"]["name"] == "Test OS"
    monkeypatch.setattr(inventory, "_run", lambda _argv: (b"pkg\t1.0\n", b"", 0, False))
    assert query_apps()["items"][0]["value"] == {"name": "pkg", "version": "1.0"}
    monkeypatch.setattr(inventory, "_run", lambda _argv: (b"", b"failure", 1, False))
    assert query_startup()["coverage"]["providers"]["systemd_user"] == "error"
    passwd.unlink()
    assert query_users()["coverage"]["availability"] == "unsupported"


def test_apps_provider_commands_and_pagination(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[list[str]] = []

    def run(argv: list[str]):
        seen.append(argv)
        if argv[0] == "snap":
            return (b"Name Version Rev Tracking Publisher Notes\nfirefox 1.2 10 stable owner -\n"
                    b"editor 2.3 11 stable owner -\n", b"", 0, False)
        return (b"Application Version\norg.example.Editor 2.3\norg.example.Viewer 1.0\n",
                b"", 0, False)

    monkeypatch.setattr(inventory, "_run", run)
    first = query_apps(provider="snap", limit=1)
    assert first["requested"]["provider"] == "snap"
    assert first["coverage"]["source"] == "snap"
    assert first["coverage"]["entries_seen"] == 2
    assert first["items"][0]["value"] == {"name": "firefox", "version": "1.2"}
    assert first["next_cursor"] == "1"
    second = query_apps(provider="snap", cursor=first["next_cursor"], limit=1)
    assert second["items"][0]["value"]["name"] == "editor"
    assert second["next_cursor"] is None
    flatpak = query_apps(provider="flatpak", limit=5)
    assert [row["value"]["name"] for row in flatpak["items"]] == [
        "org.example.Editor", "org.example.Viewer"]
    assert flatpak["coverage"]["source"] == "flatpak"
    assert seen == [
        ["snap", "list", "--color=never", "--unicode=never"],
        ["snap", "list", "--color=never", "--unicode=never"],
        ["flatpak", "list", "--app", "--columns=application,version"],
    ]


def test_apps_failures_and_capture_limit_are_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(inventory, "_run", lambda _argv: (_ for _ in ()).throw(FileNotFoundError()))
    missing = query_apps(provider="flatpak")
    assert missing["coverage"]["availability"] == "unsupported"
    assert missing["errors"][0]["source"] == "flatpak"
    monkeypatch.setattr(inventory, "_run", lambda _argv: (b"", b"permission denied", 1, False))
    denied = query_apps(provider="snap")
    assert denied["coverage"]["availability"] == "permission_denied"
    monkeypatch.setattr(inventory, "_run", lambda _argv: (b"Name Version\napp 1.0\npartial", b"", -9, True))
    partial = query_apps(provider="snap")
    assert partial["coverage"]["availability"] == "partial"
    assert partial["coverage"]["source_truncated"] is True
    assert partial["items"][0]["value"]["name"] == "app"
    assert partial["errors"][0]["code"] == "source_truncated"


def test_apps_bad_provider_cursor_and_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(inventory, "_run", lambda _argv: (b"Name Version\napp 1.0\nnext 2.0\n", b"", 0, False))
    with pytest.raises(inventory.ObserveQueryError):
        query_apps(provider="other")
    with pytest.raises(inventory.ObserveQueryError):
        query_apps(provider="snap", cursor="-1")
    with pytest.raises(inventory.ObserveQueryError):
        query_apps(provider="snap", cursor="1;bad")
    page = query_apps(provider="snap", limit=1, max_bytes=512)
    assert len(json.dumps(page, separators=(",", ":")).encode()) <= 512
