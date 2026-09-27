from __future__ import annotations

import json
import os
import socket
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from monitor_observe import ObserveQueryError, logs, query_log_services, query_logs


def test_user_service_discovery_pins_owner_bus_in_non_login_shell(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = tmp_path / str(os.getuid())
    runtime.mkdir()
    with socket.socket(socket.AF_UNIX) as bus:
        bus.bind(str(runtime / "bus"))
        monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
        monkeypatch.delenv("DBUS_SESSION_BUS_ADDRESS", raising=False)
        environment = logs._command_env(["systemctl", "--user", "list-units"], runtime_root=tmp_path)
        assert environment is not None
        assert environment["XDG_RUNTIME_DIR"] == str(runtime)
        assert environment["DBUS_SESSION_BUS_ADDRESS"] == f"unix:path={runtime / 'bus'}"
        assert logs._command_env(["docker", "ps"], runtime_root=tmp_path) is None


def _journal_row(*, unit: str, scope: str, message: str = "ready", cursor: str = "s=1") -> bytes:
    key = "_SYSTEMD_USER_UNIT" if scope == "user" else "_SYSTEMD_UNIT"
    return json.dumps({"__REALTIME_TIMESTAMP": str(int(datetime.now(UTC).timestamp() * 1_000_000) - 1_000_000),
                       "__CURSOR": cursor, key: unit, "PRIORITY": "4", "MESSAGE": message}).encode() + b"\n"


def test_system_unit_discovery_and_query(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[list[str]] = []

    def run(argv: list[str]):
        seen.append(argv)
        if argv[0] == "systemctl":
            if "list-units" in argv:
                return "● ssh.service loaded failed failed SSH\n".encode(), b"", 0, False
            return b"cron.service enabled enabled\nssh.service enabled enabled\n", b"", 0, False
        return _journal_row(unit="ssh.service", scope="system"), b"", 0, False

    monkeypatch.setattr(logs, "_run", run)
    services = query_log_services(scope="system", limit=10)
    assert services["coverage"] == {"availability": "ok", "source": "systemctl",
                                    "scope": "system", "units_seen": 2}
    assert [row["value"]["service"] for row in services["items"]] == ["cron.service", "ssh.service"]
    result = query_logs("ssh.service", scope="system")
    assert result["coverage"]["unit"] == "ssh.service"
    assert result["items"][0]["value"]["unit"] == "ssh.service"
    assert result["items"][0]["value"]["scope"] == "system"
    assert "--system" in seen[-1] and "--unit=ssh.service" in seen[-1]
    with pytest.raises(ObserveQueryError, match="available unit"):
        query_logs("unknown.service", scope="system")
    assert all("--unit=unknown.service" not in argv for argv in seen)


def test_whole_journal_search_is_bounded_and_masks_private_key(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[list[str]] = []

    def run(argv: list[str]):
        seen.append(argv)
        key_label = "PRIVATE" + " KEY"
        message = (f"trace at module.py:42\n-----BEGIN {key_label}-----\nabc\n"
                   f"-----END {key_label}-----\ntoken='secret with spaces'")
        return _journal_row(unit="cron.service", scope="system", message=message), b"", 0, False

    monkeypatch.setattr(logs, "_run", run)
    result = query_logs(scope="system", priority=4, limit=1)
    assert "--system" in seen[0]
    assert not any(arg.startswith("--unit=") for arg in seen[0])
    assert "--priority=4" in seen[0]
    assert "--lines=2" in seen[0]
    assert result["requested"]["unit"] is None
    value = result["items"][0]["value"]
    assert value["unit"] == "cron.service" and value["service"] is None
    assert "module.py:42" in value["message"]
    assert "abc" not in value["message"] and "secret with spaces" not in value["message"]
    assert "[REDACTED PRIVATE KEY]" in value["message"]
    assert len(json.dumps(result).encode()) <= 4096


def test_discovery_failures_and_capture_cap_are_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(logs, "_run", lambda _argv: (b"", b"permission denied", 1, False))
    denied = query_log_services(scope="system")
    assert denied["coverage"]["availability"] == "permission_denied"
    unavailable = query_logs("ssh.service", scope="system")
    assert unavailable["coverage"]["availability"] == "permission_denied"
    monkeypatch.setattr(logs, "_run", lambda _argv: (b"ssh.service enabled enabled\n", b"", -9, True))
    clipped = query_log_services(scope="system")
    assert clipped["truncated"]
    assert any(row["code"] == "source_truncated" for row in clipped["errors"])
    with pytest.raises(ObserveQueryError, match="scope"):
        query_logs(scope="host")


def test_alias_uses_explicit_identity_when_packaged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    identity = tmp_path / "project.identity.json"
    identity.write_text(json.dumps({"services": {"backend": "summitflow-backend.service",
                                                "frontend": "summitflow-frontend.service",
                                                "default_workers": [], "optional_workers": []}}))
    monkeypatch.setattr(logs, "IDENTITY_PATH", tmp_path / "zipapp" / "project.identity.json")
    seen: list[list[str]] = []

    def run(argv: list[str]):
        seen.append(argv)
        return _journal_row(unit="summitflow-backend.service", scope="user"), b"", 0, False

    monkeypatch.setattr(logs, "_run", run)
    result = query_logs("backend", identity_path=identity)
    assert result["coverage"]["availability"] == "ok"
    assert "--unit=summitflow-backend.service" in seen[0]
    assert all(argv[0] != "systemctl" for argv in seen)


def test_root_helper_targets_owner_user_journal(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SUMMITFLOW_MONITOR_OWNER_UID", "1000")
    monkeypatch.setattr(logs.pwd, "getpwuid", lambda uid: SimpleNamespace(pw_name="owner") if uid == 1000 else None)
    identity = tmp_path / "project.identity.json"
    identity.write_text(json.dumps({"services": {"backend": "summitflow-backend.service",
                                                "frontend": "summitflow-frontend.service",
                                                "default_workers": [], "optional_workers": []}}))
    seen: list[list[str]] = []

    def run(argv: list[str]):
        seen.append(argv)
        if argv[0] == "runuser":
            return b"other.service loaded active running\n", b"", 0, False
        return _journal_row(unit="other.service", scope="user"), b"", 0, False

    monkeypatch.setattr(logs, "_run", run)
    broad = query_logs(scope="user")
    assert broad["items"][0]["value"]["unit"] == "other.service"
    assert "_UID=1000" in seen[0] and "--user" not in seen[0]
    assert not any(arg.startswith("_SYSTEMD_USER_UNIT=") for arg in seen[0])
    selected = query_logs("backend", scope="user", identity_path=identity)
    assert selected["coverage"]["unit"] == "summitflow-backend.service"
    assert "_UID=1000" in seen[-1]
    assert "_SYSTEMD_USER_UNIT=summitflow-backend.service" in seen[-1]
    assert not any(arg.startswith("--unit=") for arg in seen[-1])
    services = query_log_services(scope="user")
    assert services["items"][0]["value"]["service"] == "other.service"
    runuser = seen[-1]
    assert runuser[:5] == ["runuser", "-u", "owner", "--", "env"]
    assert "XDG_RUNTIME_DIR=/run/user/1000" in runuser
    assert "DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus" in runuser
    assert "--user" in runuser
    query_logs("other.service", scope="user")
    assert "_SYSTEMD_USER_UNIT=other.service" in seen[-1]
    system = query_logs(scope="system")
    assert system["coverage"]["scope"] == "system"
    assert "--system" in seen[-1] and "_UID=1000" not in seen[-1]


def test_invalid_owner_uid_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUMMITFLOW_MONITOR_OWNER_UID", "0")
    with pytest.raises(ObserveQueryError, match="owner UID"):
        query_logs(scope="user")
    monkeypatch.setenv("SUMMITFLOW_MONITOR_OWNER_UID", "1000;rm")
    with pytest.raises(ObserveQueryError, match="owner UID"):
        query_log_services(scope="user")


def test_service_catalog_paginates_beyond_one_hundred_units(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = "".join(f"unit-{number:03}.service enabled enabled\n" for number in range(125)).encode()

    def run(argv: list[str]):
        if "list-unit-files" in argv:
            return rows, b"", 0, False
        return b"", b"", 0, False

    monkeypatch.setattr(logs, "_run", run)
    first = query_log_services(scope="system", limit=100, max_bytes=65536)
    assert len(first["items"]) == 100
    assert first["items"][0]["value"]["service"] == "unit-000.service"
    assert first["next_cursor"] and first["truncated"]
    second = query_log_services(scope="system", cursor=first["next_cursor"],
                                limit=100, max_bytes=65536)
    assert len(second["items"]) == 25
    assert second["items"][0]["value"]["service"] == "unit-100.service"
    assert second["items"][-1]["value"]["service"] == "unit-124.service"
    assert second["next_cursor"] is None and not second["truncated"]
    with pytest.raises(ObserveQueryError, match="cursor"):
        query_log_services(scope="user", cursor=first["next_cursor"])
    with pytest.raises(ObserveQueryError, match="cursor"):
        query_log_services(scope="system", cursor="ls1.bad.100")


def test_service_catalog_byte_budget_cursor_advances(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = "".join(f"unit-{number:03}.service enabled enabled\n" for number in range(30)).encode()
    monkeypatch.setattr(logs, "_run", lambda _argv: (rows, b"", 0, False))
    seen: list[str] = []
    cursor = None
    for _ in range(30):
        page = query_log_services(scope="system", cursor=cursor, limit=30, max_bytes=700)
        assert len(json.dumps(page, separators=(",", ":")).encode()) <= 700
        seen.extend(row["value"]["service"] for row in page["items"])
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert seen == [f"unit-{number:03}.service" for number in range(30)]


def test_container_catalog_and_bounded_redacted_logs(monkeypatch: pytest.MonkeyPatch) -> None:
    identifier = "a" * 64
    seen: list[list[str]] = []
    stamp = datetime.fromtimestamp(datetime.now(UTC).timestamp() - 1, UTC).isoformat()

    def run(argv: list[str]):
        seen.append(argv)
        if argv[:3] == ["docker", "ps", "-a"]:
            return f"{identifier}\tpostgres\n".encode(), b"", 0, False
        key_label = "PRIVATE" + " KEY"
        stdout = (f"{stamp} connection ready\n"
                  f"{stamp} token='secret with spaces'\n"
                  f"{stamp} -----BEGIN {key_label}-----\n"
                  f"{stamp} private material\n"
                  f"{stamp} -----END {key_label}-----\n").encode()
        stderr = f"{stamp} password=hidden\n".encode()
        return stdout, stderr, 0, False

    monkeypatch.setattr(logs, "_run", run)
    catalog = query_log_services(scope="container")
    assert catalog["coverage"]["source"] == "docker"
    assert catalog["items"][0]["value"] == {"service": "postgres", "scope": "container",
                                           "container_id": identifier}
    result = query_logs("postgres", scope="container", limit=2)
    assert seen[-1][0:3] == ["docker", "logs", "--timestamps"]
    assert seen[-1][-1] == identifier and "--tail=3" in seen[-1]
    assert result["truncated"] and result["next_cursor"] is None
    assert result["coverage"]["priority_filter"] == "unsupported"
    assert result["coverage"]["pagination"] == "unsupported"
    messages = " ".join(row["value"]["message"] for row in result["items"])
    assert "secret with spaces" not in messages and "hidden" not in messages
    assert all(row["value"]["container_id"] == identifier for row in result["items"])
    assert len(json.dumps(result, separators=(",", ":")).encode()) <= 4096
    full = query_logs("postgres", scope="container", limit=10)
    full_messages = " ".join(row["value"]["message"] for row in full["items"])
    assert "private material" not in full_messages and "[REDACTED PRIVATE KEY]" in full_messages
    assert "hidden" not in full_messages
    by_id = query_logs(identifier, scope="container")
    assert by_id["requested"]["unit"] == "postgres"
    with pytest.raises(ObserveQueryError, match="available"):
        query_logs("redis", scope="container")
    assert all(not (argv[:2] == ["docker", "logs"] and argv[-1] == "redis") for argv in seen)


def test_container_source_errors_and_unsupported_filters(monkeypatch: pytest.MonkeyPatch) -> None:
    identifier = "b" * 64
    monkeypatch.setattr(logs, "_run", lambda argv: (
        (f"{identifier}\tredis\n".encode(), b"", 0, False)
        if argv[:2] == ["docker", "ps"] else (b"", b"permission denied", 1, False)))
    denied = query_logs("redis", scope="container")
    assert denied["coverage"]["availability"] == "permission_denied"
    with pytest.raises(ObserveQueryError, match="cursor or priority"):
        query_logs("redis", scope="container", priority=3)
    with pytest.raises(ObserveQueryError, match="cursor or priority"):
        query_logs("redis", scope="container", cursor="s=1")
    with pytest.raises(ObserveQueryError, match="discovered"):
        query_logs(scope="container")
    monkeypatch.setattr(logs, "_run", lambda _argv: (b"", b"permission denied", 1, False))
    unavailable = query_log_services(scope="container")
    assert unavailable["coverage"]["availability"] == "permission_denied"
    unknown = query_logs("redis", scope="container")
    assert unknown["coverage"]["availability"] == "permission_denied"


def test_package_catalog_and_timestamped_sources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    local_stamp = (datetime.now().astimezone() - timedelta(minutes=2))
    apt_stamp = local_stamp.strftime("%Y-%m-%d  %H:%M:%S")
    dpkg_stamp = local_stamp.strftime("%Y-%m-%d %H:%M:%S")
    history = tmp_path / "history.log"
    history.write_text(f"Start-Date:  {apt_stamp}\nCommandline: apt install app\n"
                       "Install: app:amd64 (1.0)\n"
                       f"End-Date:  {apt_stamp}\n")
    term = tmp_path / "term.log"
    key_label = "PRIVATE" + " KEY"
    term.write_text(f"Log started: {apt_stamp}\n"
                    "password='secret with spaces'\n"
                    f"-----BEGIN {key_label}-----\nprivate material\n-----END {key_label}-----\n"
                    f"Log ended: {apt_stamp}\n")
    dpkg = tmp_path / "dpkg.log"
    dpkg.write_text(f"{dpkg_stamp} install app:amd64 <none> 1.0\n"
                    "2020-01-01 00:00:00 old action\n")
    monkeypatch.setattr(logs, "_PACKAGE_LOGS", {"apt-history": history, "apt-term": term, "dpkg": dpkg})
    catalog = query_log_services(scope="package")
    assert catalog["coverage"]["sources"] == {"apt-history": "ok", "apt-term": "ok", "dpkg": "ok"}
    assert [row["value"]["service"] for row in catalog["items"]] == ["apt-history", "apt-term", "dpkg"]
    since = datetime.now(UTC) - timedelta(minutes=10)
    until = datetime.now(UTC) + timedelta(minutes=1)
    history_result = query_logs("apt-history", scope="package", since=since, until=until)
    assert any("Install: app" in row["value"]["message"] for row in history_result["items"])
    term_result = query_logs("apt-term", scope="package", since=since, until=until)
    term_messages = " ".join(row["value"]["message"] for row in term_result["items"])
    assert "secret with spaces" not in term_messages and "private material" not in term_messages
    assert "[REDACTED PRIVATE KEY]" in term_messages
    dpkg_result = query_logs("dpkg", scope="package", since=since, until=until)
    assert len(dpkg_result["items"]) == 1
    assert dpkg_result["items"][0]["value"]["message"] == "install app:amd64 <none> 1.0"
    assert dpkg_result["coverage"]["pagination"] == "unsupported"
    assert len(json.dumps(dpkg_result, separators=(",", ":")).encode()) <= 4096
    with pytest.raises(ObserveQueryError, match="package service"):
        query_logs("/var/log/dpkg.log", scope="package")
    with pytest.raises(ObserveQueryError, match="cursor or priority"):
        query_logs("dpkg", scope="package", cursor="x")
    with pytest.raises(ObserveQueryError, match="cursor or priority"):
        query_logs("dpkg", scope="package", priority=3)


def test_package_tail_cap_and_symlink_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stamp = (datetime.now().astimezone() - timedelta(minutes=2)).strftime("%Y-%m-%d %H:%M:%S")
    dpkg = tmp_path / "dpkg.log"
    dpkg.write_text("".join(f"{stamp} install app-{number}:amd64 <none> 1.0\n" for number in range(20)))
    link = tmp_path / "term.log"
    link.symlink_to(dpkg)
    monkeypatch.setattr(logs, "_PACKAGE_LOGS", {"apt-history": tmp_path / "missing",
                                              "apt-term": link, "dpkg": dpkg})
    monkeypatch.setattr(logs, "MAX_CAPTURE_BYTES", 150)
    catalog = query_log_services(scope="package")
    assert catalog["coverage"]["availability"] == "partial"
    assert catalog["coverage"]["sources"] == {"apt-history": "unsupported",
                                              "apt-term": "unsupported", "dpkg": "ok"}
    since = datetime.now(UTC) - timedelta(minutes=10)
    until = datetime.now(UTC) + timedelta(minutes=1)
    clipped = query_logs("dpkg", scope="package", since=since, until=until)
    assert clipped["coverage"]["availability"] == "partial"
    assert clipped["truncated"]
    assert any(row["code"] == "source_truncated" for row in clipped["errors"])
    assert all("app-0:" not in row["value"]["message"] for row in clipped["items"])
    denied = query_logs("apt-term", scope="package", since=since, until=until)
    assert denied["coverage"]["availability"] == "unsupported"
    assert denied["items"] == []


def test_package_permission_denial_is_explicit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "term.log"
    path.write_text("not read")
    monkeypatch.setattr(logs, "_PACKAGE_LOGS", {"apt-term": path})
    monkeypatch.setattr(logs, "_open_package_log", lambda _path: (_ for _ in ()).throw(PermissionError()))
    catalog = query_log_services(scope="package")
    assert catalog["coverage"]["sources"] == {"apt-term": "permission_denied"}
    result = query_logs("apt-term", scope="package")
    assert result["coverage"]["availability"] == "permission_denied"
    assert result["items"] == []
