"""Fixed stdlib-only Neri deployment program sent through the guest agent.

This is operator code, never code or commands supplied by project identity.
Only fixed source/fixture files, their hashes, and an attempt UUID are input data.
"""

from __future__ import annotations

import base64
import fcntl
import grp
import hashlib
import json
import os
import pwd
import re
import stat
import subprocess
import sys
import time
import urllib.request
import zlib
from pathlib import Path
from typing import Any

ADAPTER = "neri-runner-v1"
ROOT = Path("/opt/neri-runner")
PROFILES = (
    ("juice-shop-local-v1", Path("/etc/neri-runner/config.json"), 8517),
    ("wordpress-simple-page-ordering-local-v1", Path("/etc/neri-runner/wordpress-config.json"), 8518),
)
SERVICES = ("neri-proxy.service", "neri-wordpress-proxy.service")
FILES = ("proxy_runner.py", "proxy_core.py")
FIXTURE_CONTROLS = (
    "fixture.lock.json", ".wp-env.json", "package.json", "package-lock.json", "patch-wp-env.cjs", "setup.sh", "seed.sh",
)
FIXTURE_FILES = ("reset-profiles.json", "target_reset.py", *("fixture/" + name for name in FIXTURE_CONTROLS))
FIXTURE_ROOT = Path("/opt/neri-wordpress-fixture")
RESET_CONFIG = Path("/etc/neri-runner/reset-profiles.json")
RESET_HELPER = Path("/usr/local/lib/neri/target_reset.py")
WORDPRESS_CONFIG = Path("/etc/neri-runner/wordpress-config.json")
RUNNER_CONFIG = Path("/etc/neri-runner/config.json")
PRIVILEGED_UID = 0
MAX_TRANSFER_PAYLOAD_BYTES = 4 * 1024 * 1024


class DeploymentError(RuntimeError):
    """A deployment stopped at a recorded phase."""


def identity(contents: dict[str, bytes]) -> dict[str, Any]:
    hashes = {name: hashlib.sha256(value).hexdigest() for name, value in contents.items()}
    digest = hashlib.sha256(json.dumps(hashes, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {"release_id": "sha256:" + digest, "files": hashes}


def encode_payload(payload: dict[str, Any]) -> str:
    """Compress the fixed source bundle before passing it through guest argv."""
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    if len(raw) > MAX_TRANSFER_PAYLOAD_BYTES:
        raise DeploymentError("Runner bundle exceeds the fixed transfer limit")
    return base64.b64encode(zlib.compress(raw, level=9)).decode("ascii")


def decode_payload(encoded: str) -> dict[str, Any]:
    """Decode one bounded compressed bundle; source hashes still verify its contents."""
    if not isinstance(encoded, str) or len(encoded) > MAX_TRANSFER_PAYLOAD_BYTES * 2:
        raise DeploymentError("Runner bundle transport is invalid")
    try:
        compressed = base64.b64decode(encoded, validate=True)
        decoder = zlib.decompressobj()
        raw = decoder.decompress(compressed, MAX_TRANSFER_PAYLOAD_BYTES + 1)
        if decoder.unconsumed_tail or not decoder.eof or decoder.unused_data:
            raise DeploymentError("Runner bundle transport is incomplete")
        value = json.loads(raw)
    except (ValueError, TypeError, zlib.error) as exc:
        raise DeploymentError("Runner bundle transport is invalid") from exc
    if len(raw) > MAX_TRANSFER_PAYLOAD_BYTES or not isinstance(value, dict):
        raise DeploymentError("Runner bundle transport is invalid")
    return value


def read_identity(directory: Path) -> dict[str, Any]:
    return identity({name: (directory / name).read_bytes() for name in FILES})


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_suffix(".tmp")
    with temporary.open("w") as stream:
        json.dump(value, stream)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    sync_directory(path.parent)


def sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise DeploymentError("Runner health redirected")


def profile_health(config: Path, port: int) -> dict[str, Any]:
    # The key never leaves its existing guest configuration or enters argv/logs.
    key = json.loads(config.read_text())["api_key"]
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/health", headers={"Authorization": "Bearer " + key},
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    with opener.open(request, timeout=3) as response:
        value = json.load(response)
    # Omit target/capture/session content from deployment evidence.
    health = {name: value.get(name) for name in (
        "status", "stopped", "busy", "failure", "release", "deployment_protocol", "deployment_blocked",
    )}
    if health["failure"] is not None:
        health["failure"] = "Runner reported a failure"
    return health


def staged_fixture_receipt(contents: bytes) -> dict[str, Any] | None:
    """Recognize only this fixed recovery's sealed marker/completion envelope."""
    try:
        value = json.loads(contents)
        if (not isinstance(value, dict) or set(value) != {
                "adapter", "operation", "original_attempt", "recovery_attempt", "state", "receipt_sha256", "final_receipt"}
                or value["adapter"] != ADAPTER or value["operation"] != "recover-fixture"
                or value["state"] != "verified"
                or not re.fullmatch(r"[0-9a-f]{32}", value["original_attempt"])
                or not re.fullmatch(r"[0-9a-f]{32}", value["recovery_attempt"])
                or value["original_attempt"] == value["recovery_attempt"]):
            return None
        final = value["final_receipt"]
        if (not isinstance(final, dict) or set(final) != {
                "adapter", "operation", "original_attempt", "attempt", "state", "events", "phase",
                "original_receipt", "original_backup", "expected", "artifact_identity", "fixture_digest",
                "before", "after", "verified", "runner_after", "interlock_retained"}
                or final["adapter"] != ADAPTER or final["operation"] != "recover-fixture"
                or final["original_attempt"] != value["original_attempt"] or final["attempt"] != value["recovery_attempt"]
                or final["state"] != "succeeded" or final["phase"] != "verified"
                or final["verified"] is not True or final["interlock_retained"] is not False
                or set(final["original_receipt"]) != {"path", "sha256"}
                or final["original_receipt"]["path"] != str(ROOT / "deployments" / (value["original_attempt"] + "-fixture.json"))
                or not re.fullmatch(r"[0-9a-f]{64}", final["original_receipt"]["sha256"])
                or final["original_backup"] != str(ROOT / "deployments" / (value["original_attempt"] + "-fixture-backup"))
                or final["after"]["installed"] != final["expected"]
                or final["after"]["artifact_identity"] != final["artifact_identity"]
                or set(final["after"]) != {"installed", "artifact_identity", "fixture_digest"}
                or final["after"]["fixture_digest"] != final["fixture_digest"]
                or not re.fullmatch(r"[0-9a-f]{64}", final["fixture_digest"])
                or final["artifact_identity"] != "wordpress-fixture:sha256:" + final["fixture_digest"]
                or set(final["expected"]) != {"release_id", "files"}
                or not re.fullmatch(r"sha256:[0-9a-f]{64}", final["expected"]["release_id"])
                or set(final["expected"]["files"]) != set(FIXTURE_FILES)
                or any(not re.fullmatch(r"[0-9a-f]{64}", digest) for digest in final["expected"]["files"].values())
                or set(final["before"]) - {"installed", "artifact_identity", "fixture_digest", "error"}
                or set(final["runner_after"]) != {"profiles", "installed", "marker"}
                or final["runner_after"]["marker"] != value["original_attempt"]):
            return None
        encoded = json.dumps(final, sort_keys=True, separators=(",", ":")).encode()
        if hashlib.sha256(encoded).hexdigest() != value["receipt_sha256"]:
            return None
        require_release(final["runner_after"], final["runner_after"]["installed"], blocked=True)
        return final
    except (ValueError, TypeError, KeyError, AttributeError, DeploymentError):
        return None


def deployment_marker_owner(contents: bytes) -> str:
    owner = contents.decode().strip()
    if re.fullmatch(r"[0-9a-f]{32}", owner):
        return owner
    staged = staged_fixture_receipt(contents)
    return staged["original_attempt"] if staged is not None else "unrecognized"


def inspect() -> dict[str, Any]:
    result: dict[str, Any] = {"profiles": {}, "installed": None, "marker": None}
    try:
        result["installed"] = read_identity(ROOT)
    except (OSError, ValueError):
        result["installed_error"] = "Installed bundle unreadable"
    marker = ROOT / ".deploying"
    if marker.exists() or marker.is_symlink():
        try:
            result["marker"] = "unrecognized" if marker.is_symlink() else deployment_marker_owner(marker.read_bytes())
        except (OSError, UnicodeError):
            result["marker"] = "unreadable"
    for name, config, port in PROFILES:
        try:
            result["profiles"][name] = profile_health(config, port)
        except Exception:
            result["profiles"][name] = {"error": "Runner health unavailable"}
    return result


def require_idle(observation: dict[str, Any], *, blocked: bool) -> None:
    if set(observation["profiles"]) != {profile[0] for profile in PROFILES}:
        raise DeploymentError("Both fixed runner profiles must report health")
    for value in observation["profiles"].values():
        if (value.get("status") != "ok" or value.get("failure") is not None
                or value.get("deployment_protocol") != ADAPTER
                or value.get("deployment_blocked") is not blocked):
            raise DeploymentError("Runner health or deployment interlock unavailable; controlled bootstrap/recovery required")
        if value.get("stopped") is not True or value.get("busy") is not False:
            raise DeploymentError("Runner profile is busy; deployment refused")


def require_release(observation: dict[str, Any], expected: dict[str, Any], *, blocked: bool) -> None:
    require_idle(observation, blocked=blocked)
    if observation["installed"] != expected:
        raise DeploymentError("Installed bundle hash mismatch")
    if any(value.get("release") != expected for value in observation["profiles"].values()):
        raise DeploymentError("Running release identity mismatch")


def save_bundle(contents: dict[str, bytes], expected: dict[str, Any]) -> Path:
    releases = ROOT / "releases"
    releases.mkdir(exist_ok=True)
    releases.chmod(0o755)
    directory = releases / expected["release_id"].removeprefix("sha256:")
    if not directory.exists():
        directory.mkdir()
        directory.chmod(0o755)
        for name, value in contents.items():
            path = directory / name
            with path.open("xb") as stream:
                stream.write(value)
                stream.flush()
                os.fsync(stream.fileno())
            path.chmod(0o644)
        sync_directory(directory)
        sync_directory(directory.parent)
    if read_identity(directory) != expected:
        raise DeploymentError("Staged bundle hash mismatch; preserve and inspect the release directory")
    return directory


def replace_link(path: Path, target: str) -> None:
    temporary = path.with_name(path.name + ".next")
    if temporary.exists() or temporary.is_symlink():
        raise DeploymentError("Unsettled activation link exists; inspect deployment state")
    temporary.symlink_to(target)
    os.replace(temporary, path)
    sync_directory(path.parent)


def systemctl(action: str) -> None:
    result = subprocess.run(
        ["/usr/bin/systemctl", action, *SERVICES], capture_output=True, timeout=90, check=False,
    )
    if result.returncode != 0:
        raise DeploymentError(f"Runner service {action} failed")


def activate(directory: Path, previous: Path, *, services_stopped: bool = False) -> None:
    current = ROOT / "current"
    if not current.exists() and not current.is_symlink():
        # One-time conversion of guarded legacy runners. Both are stopped while
        # the flat entry points become stable links; source activation itself is
        # still one atomic current-link replacement.
        if not services_stopped:
            systemctl("stop")
        replace_link(current, str(previous.relative_to(ROOT)))
        for name in FILES:
            replace_link(ROOT / name, "current/" + name)
    if (not current.is_symlink()
            or any(not (ROOT / name).is_symlink() or os.readlink(ROOT / name) != "current/" + name for name in FILES)
            or current.resolve() != previous):
        raise DeploymentError("Installed layout changed; inspect before recovery")
    replace_link(ROOT / "previous", str(previous.relative_to(ROOT)))
    replace_link(current, str(directory.relative_to(ROOT)))


def require_legacy_layout() -> None:
    """Accept only the original two-file installation for one-time adoption."""
    if (ROOT / "current").exists() or (ROOT / "current").is_symlink():
        raise DeploymentError("Guarded runner layout already exists; use normal deployment or recovery")
    if (ROOT / "previous").exists() or (ROOT / "previous").is_symlink():
        raise DeploymentError("Unexpected legacy previous link; inspect before recovery")
    if any(not (ROOT / name).is_file() or (ROOT / name).is_symlink() for name in FILES):
        raise DeploymentError("Legacy runner source layout is not the expected fixed-file installation")


def fixture_paths() -> dict[str, Path]:
    return {"reset-profiles.json": RESET_CONFIG, "target_reset.py": RESET_HELPER,
            **{"fixture/" + name: FIXTURE_ROOT / name for name in FIXTURE_CONTROLS}}


def fixture_contents(payload: dict[str, Any]) -> tuple[dict[str, bytes], str, str]:
    """Validate public pins before any guest mutation, including at host freeze."""
    try:
        if (set(payload) != {"files", "identity"} or not isinstance(payload["files"], dict)
                or set(payload["files"]) != set(FIXTURE_FILES)):
            raise DeploymentError("Fixture bundle must contain exactly the fixed public files")
        contents = {name: base64.b64decode(payload["files"][name], validate=True) for name in FIXTURE_FILES}
        if identity(contents) != payload["identity"]:
            raise DeploymentError("Transferred fixture bundle hash mismatch")
        config = json.loads(contents["reset-profiles.json"])
        if (config["schema_version"] != "neri.reset-profiles.v1"
                or set(config["profiles"]) != {profile[0] for profile in PROFILES}):
            raise DeploymentError("Fixture reset profiles differ from the fixed runner profiles")
        profile = config["profiles"]["wordpress-simple-page-ordering-local-v1"]
        fixed = {
            "kind": "wordpress", "root": "/var/lib/neri-wordpress-runner",
            "receipts": "/var/lib/neri-wordpress-reset-receipts",
            "fixture_root": "/opt/neri-wordpress-fixture",
            "env_home": "/var/lib/neri-wordpress/wp-env", "runtime_user": "neri-wordpress",
        }
        if any(profile.get(key) != value for key, value in fixed.items()):
            raise DeploymentError("WordPress fixture locations and runtime identity are fixed")
        lock_bytes = contents["fixture/fixture.lock.json"]
        digest = hashlib.sha256(lock_bytes).hexdigest()
        artifact = "wordpress-fixture:sha256:" + digest
        lock = json.loads(lock_bytes)
        if (profile["fixture_digest"] != digest or profile["artifact_identity"] != artifact
                or lock["schema_version"] != "neri.wordpress-fixture.v1"
                or lock["reset_version"] != profile["reset_version"]):
            raise DeploymentError("Fixture lock and reset artifact identity differ")
        if set(lock["fixture_files"]) != set(FIXTURE_CONTROLS) - {"fixture.lock.json"}:
            raise DeploymentError("Fixture control hash allowlist differs")
        for name, expected in lock["fixture_files"].items():
            if hashlib.sha256(contents["fixture/" + name]).hexdigest() != expected:
                raise DeploymentError("Fixture control hash differs from its lock")
        return contents, digest, artifact
    except DeploymentError:
        raise
    except (KeyError, ValueError, TypeError, AttributeError) as exc:
        raise DeploymentError("Fixture bundle contract is invalid") from exc


def protected_file(path: Path) -> os.stat_result:
    details = path.lstat()
    if (not stat.S_ISREG(details.st_mode) or details.st_uid != PRIVILEGED_UID
            or details.st_nlink != 1 or details.st_mode & 0o022):
        raise DeploymentError("Fixture/configuration file is not protected and root-owned")
    return details


def protected_directory(path: Path) -> None:
    details = path.lstat()
    if (not stat.S_ISDIR(details.st_mode) or details.st_uid != PRIVILEGED_UID
            or details.st_mode & 0o022):
        raise DeploymentError("Fixture/configuration directory is not protected and root-owned")


PIN_ATTRIBUTES = ("st_dev", "st_ino", "st_mode", "st_uid", "st_gid", "st_nlink",
                  "st_size", "st_mtime_ns", "st_ctime_ns")


def pinned_path(path: Path, *, directory: bool = False) -> tuple[os.stat_result, bytes]:
    """Read without following links, and reject replacement during the read."""
    details = path.lstat()
    expected_type = stat.S_ISDIR if directory else stat.S_ISREG
    if not expected_type(details.st_mode) or (not directory and details.st_nlink != 1):
        raise DeploymentError("Runner configuration path is not a fixed directory or private file")
    flags = os.O_RDONLY | os.O_NOFOLLOW | (os.O_DIRECTORY if directory else os.O_NONBLOCK)
    descriptor = os.open(path, flags)
    try:
        contents = b""
        if not directory:
            with os.fdopen(descriptor, "rb", closefd=False) as stream:
                contents = stream.read()
        opened = os.fstat(descriptor)
        current = path.lstat()
        if any(getattr(details, name) != getattr(value, name)
               for value in (opened, current) for name in PIN_ATTRIBUTES):
            raise DeploymentError("Runner configuration changed during inspection")
        return details, contents
    finally:
        os.close(descriptor)


def revalidate_pins(pins: dict[Path, tuple[os.stat_result, bytes]]) -> None:
    for path, (details, contents) in pins.items():
        current, current_bytes = pinned_path(path, directory=stat.S_ISDIR(details.st_mode))
        if (current_bytes != contents or any(getattr(details, name) != getattr(current, name)
                                            for name in PIN_ATTRIBUTES)):
            raise DeploymentError("Runner configuration changed since inspection")


def configuration_layout() -> tuple[bool, int, dict[Path, tuple[os.stat_result, bytes]]]:
    """Allow only the named runner's original layout or its exact root-owned replacement."""
    try:
        runner = pwd.getpwnam("neri-runner")
        group = grp.getgrnam("neri-runner")
    except KeyError as exc:
        raise DeploymentError("Named runner account/group is unavailable") from exc
    if runner.pw_uid == 0 or group.gr_gid == 0 or runner.pw_gid != group.gr_gid:
        raise DeploymentError("Named runner account/group is invalid")
    directory = WORDPRESS_CONFIG.parent
    if RUNNER_CONFIG.parent != directory or RESET_CONFIG.parent != directory:
        raise DeploymentError("Runner configuration paths differ from the fixed layout")
    pins = {directory: pinned_path(directory, directory=True),
            RUNNER_CONFIG: pinned_path(RUNNER_CONFIG), WORDPRESS_CONFIG: pinned_path(WORDPRESS_CONFIG)}

    def metadata(path: Path) -> tuple[int, int, int]:
        details = pins[path][0]
        return details.st_uid, details.st_gid, stat.S_IMODE(details.st_mode)

    canonical_private = (PRIVILEGED_UID, group.gr_gid, 0o640)
    canonical = (metadata(directory) == (PRIVILEGED_UID, group.gr_gid, 0o750)
                 and metadata(RUNNER_CONFIG) == canonical_private)
    legacy = (metadata(directory) == (runner.pw_uid, group.gr_gid, 0o700)
              and metadata(RUNNER_CONFIG) == (runner.pw_uid, group.gr_gid, 0o600))
    if not (canonical or legacy) or metadata(WORDPRESS_CONFIG) != canonical_private:
        raise DeploymentError("Runner configuration ownership/modes differ from the supported layouts")
    for path in (RUNNER_CONFIG, WORDPRESS_CONFIG):
        if not isinstance(json.loads(pins[path][1]), dict):
            raise DeploymentError("Private runner configuration is invalid")
    return legacy, group.gr_gid, pins


def adopt_configuration(gid: int, pins: dict[Path, tuple[os.stat_result, bytes]]) -> None:
    """Freeze the legacy directory, then atomically preserve the exact private bytes."""
    revalidate_pins(pins)
    directory = WORDPRESS_CONFIG.parent
    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        opened = os.fstat(descriptor)
        if any(getattr(opened, name) != getattr(pins[directory][0], name) for name in PIN_ATTRIBUTES):
            raise DeploymentError("Runner configuration directory changed since inspection")
        os.fchown(descriptor, PRIVILEGED_UID, gid)
        os.fchmod(descriptor, 0o750)
        os.fsync(descriptor)
        current = directory.lstat()
        if (current.st_dev, current.st_ino) != (opened.st_dev, opened.st_ino):
            raise DeploymentError("Runner configuration directory was replaced during adoption")
        revalidate_pins({path: value for path, value in pins.items() if path != directory})
        replace_file(RUNNER_CONFIG, pins[RUNNER_CONFIG][1], 0o640, PRIVILEGED_UID, gid)
    finally:
        os.close(descriptor)


def fixture_observation() -> dict[str, Any]:
    """Public byte identity and one public scalar; never return private config."""
    result: dict[str, Any] = {"installed": None, "artifact_identity": None, "fixture_digest": None}
    try:
        for directory in {FIXTURE_ROOT, RESET_CONFIG.parent, RESET_HELPER.parent, WORDPRESS_CONFIG.parent}:
            protected_directory(directory)
        protected_file(FIXTURE_ROOT / "fixture.lock.json")
        result["fixture_digest"] = hashlib.sha256((FIXTURE_ROOT / "fixture.lock.json").read_bytes()).hexdigest()
        contents = {}
        for name, path in fixture_paths().items():
            details = protected_file(path)
            expected_mode = 0o755 if name in {"fixture/setup.sh", "fixture/seed.sh"} else 0o644
            if stat.S_IMODE(details.st_mode) != expected_mode:
                raise DeploymentError("Installed fixture public-file mode differs")
            contents[name] = path.read_bytes()
        result["installed"] = identity(contents)
        protected_file(WORDPRESS_CONFIG)
        artifact = json.loads(WORDPRESS_CONFIG.read_bytes()).get("target_artifact_identity")
        if not isinstance(artifact, str) or not re.fullmatch(r"wordpress-fixture:sha256:[a-f0-9]{64}", artifact):
            raise DeploymentError("Private runner artifact identity is invalid")
        result["artifact_identity"] = artifact
    except (OSError, ValueError, TypeError, AttributeError, DeploymentError):
        result["error"] = "Installed fixture/configuration unreadable or unprotected"
    return result


def replace_file(path: Path, contents: bytes, mode: int, uid: int, gid: int) -> None:
    temporary = path.with_name(path.name + ".next")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
    with os.fdopen(descriptor, "wb") as stream:
        os.fchown(stream.fileno(), uid, gid)
        os.fchmod(stream.fileno(), mode)
        stream.write(contents)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    sync_directory(path.parent)


def provision_fixture() -> None:
    result = subprocess.run(
        ["/usr/bin/bash", str(FIXTURE_ROOT / "setup.sh")],
        cwd=FIXTURE_ROOT, env={
            "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            "HOME": "/root", "NERI_RESET_CONFIG": str(RESET_CONFIG),
        }, capture_output=True, timeout=900, check=False,
    )
    if result.returncode != 0:
        raise DeploymentError("Fixed WordPress fixture provisioning failed")


def restore_fixture_dependencies() -> None:
    """Rebuild the locked fixture dependencies from the existing root cache only."""
    result = subprocess.run(
        ["/usr/bin/npm", "ci", "--offline", "--ignore-scripts"],
        cwd=FIXTURE_ROOT, env={
            "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            "HOME": "/root",
        }, capture_output=True, timeout=900, check=False,
    )
    if result.returncode != 0:
        raise DeploymentError("Fixed WordPress fixture dependency restoration failed")


def verify_fixture() -> None:
    # Reuse Neri's complete archive/tree/image/config and live baseline checks.
    # The fixed import program receives no target commands or private config.
    program = (
        "import importlib.util; "
        "spec=importlib.util.spec_from_file_location('neri_target_reset', '/usr/local/lib/neri/target_reset.py'); "
        "helper=importlib.util.module_from_spec(spec); spec.loader.exec_module(helper); "
        "helper.wordpress_state(helper.wordpress_lock())"
    )
    result = subprocess.run(
        ["/usr/bin/python3", "-B", "-c", program],
        env={"PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
             "NERI_RESET_KIND": "wordpress", "NERI_RESET_CONFIG": str(RESET_CONFIG)},
        capture_output=True, timeout=900, check=False,
    )
    if result.returncode != 0:
        raise DeploymentError("WordPress fixture verification failed")


def sync_fixture(attempt: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Synchronize fixed public pins; provision only a changed fixture digest."""
    if not re.fullmatch(r"[0-9a-f]{32}", attempt):
        raise DeploymentError("Invalid deployment attempt")
    protected_directory(ROOT)
    if os.geteuid() != PRIVILEGED_UID:
        raise DeploymentError("Fixture deployment requires root")
    receipts = ROOT / "deployments"
    path = receipts / (attempt + "-fixture.json")
    record: dict[str, Any] = {
        "adapter": ADAPTER, "operation": "sync-fixture", "attempt": attempt,
        "state": "running", "events": [],
    }
    marker_owned = False
    uncertain = False

    def phase(name: str, **values: Any) -> None:
        record.update(phase=name, **values)
        record["events"].append({"phase": name, "at": time.time()})
        atomic_json(path, record)

    with (ROOT / ".deployment-lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        receipts.mkdir(mode=0o755, exist_ok=True)
        protected_directory(receipts)
        if path.exists() or path.is_symlink():
            raise DeploymentError("Fixture attempt already exists; inspect its receipt instead of retrying")
        try:
            phase("inspect")
            runner_before = inspect()
            if runner_before["marker"] is not None:
                raise DeploymentError("Existing deployment interlock retained; inspect and recover its owner")
            require_release(runner_before, runner_before["installed"], blocked=False)
            contents, digest, artifact = fixture_contents(payload)
            phase("validated", expected=payload["identity"], artifact_identity=artifact, fixture_digest=digest)
            legacy, runner_gid, config_pins = configuration_layout()
            before = fixture_observation()
            record["before"] = before
            if (not legacy and before["installed"] == payload["identity"] and before["artifact_identity"] == artifact
                    and "error" not in before):
                verify_fixture()
                revalidate_pins(config_pins)
                phase("verified", state="noop", after=before, verified=True)
                return record

            # Existing private config must be present and protected; no secrets
            # are supplied by the host or synthesized from public fixture data.
            for directory in {FIXTURE_ROOT, RESET_HELPER.parent}:
                protected_directory(directory)
            public_pins = {}
            for destination in fixture_paths().values():
                if destination.exists() or destination.is_symlink():
                    protected_file(destination)
                    public_pins[destination] = pinned_path(destination)
            private_details, private_bytes = config_pins[WORDPRESS_CONFIG]
            private = json.loads(private_bytes)
            private["target_artifact_identity"] = artifact
            phase("interlock")
            marker = ROOT / ".deploying"
            with marker.open("x") as stream:
                stream.write(attempt)
                stream.flush()
                os.fsync(stream.fileno())
            marker.chmod(0o644)
            marker_owned = True
            sync_directory(ROOT)
            require_idle(inspect(), blocked=True)

            phase("backup")
            revalidate_pins({**config_pins, **public_pins})
            backup = receipts / (attempt + "-fixture-backup")
            backup.mkdir(mode=0o700)
            backup.chmod(0o700)
            for name, destination in fixture_paths().items():
                if destination in public_pins:
                    details, old_bytes = public_pins[destination]
                    replace_file(backup / name.replace("/", "_"), old_bytes,
                                 stat.S_IMODE(details.st_mode), details.st_uid, details.st_gid)
            for destination in (RUNNER_CONFIG, WORDPRESS_CONFIG):
                replace_file(backup / ("private-" + destination.name), config_pins[destination][1],
                             0o600, PRIVILEGED_UID, PRIVILEGED_UID)
            sync_directory(receipts)
            record["backup"] = str(backup)
            record["private_config_metadata"] = {
                "mode": stat.S_IMODE(private_details.st_mode),
                "uid": private_details.st_uid, "gid": private_details.st_gid,
            }

            # Stop both runners before installing configuration they load once.
            # Every interruption from this point requires receipt reconciliation.
            phase("stop")
            uncertain = True
            systemctl("stop")
            revalidate_pins({**config_pins, **public_pins})
            if legacy:
                phase("adopt-configuration")
                adopt_configuration(runner_gid, config_pins)
                record["configuration_adopted"] = True
                _legacy, _gid, config_pins = configuration_layout()
            # Legacy protection may have hidden an already-identical fixture.
            # Reobserve strictly after adoption before choosing any provisioning.
            current_fixture = fixture_observation()
            if (current_fixture["installed"] != payload["identity"]
                    or current_fixture["artifact_identity"] != artifact or "error" in current_fixture):
                phase("install")
                revalidate_pins({**config_pins, **public_pins})
                for name, destination in fixture_paths().items():
                    mode = 0o755 if name in {"fixture/setup.sh", "fixture/seed.sh"} else 0o644
                    replace_file(destination, contents[name], mode, PRIVILEGED_UID, PRIVILEGED_UID)
                revalidate_pins({WORDPRESS_CONFIG: config_pins[WORDPRESS_CONFIG],
                                 RUNNER_CONFIG: config_pins[RUNNER_CONFIG]})
                replace_file(WORDPRESS_CONFIG, json.dumps(private).encode(),
                             0o640, PRIVILEGED_UID, runner_gid)
            if current_fixture["fixture_digest"] != digest:
                phase("provision", provision_started=True)
                provision_fixture()
            phase("verify-fixture")
            verify_fixture()
            after = fixture_observation()
            if (after["installed"] != payload["identity"] or after["artifact_identity"] != artifact
                    or "error" in after):
                raise DeploymentError("Installed fixture/configuration identity mismatch")
            phase("restart", after=after)
            systemctl("restart")
            deadline = time.monotonic() + 30
            while True:
                try:
                    require_release(inspect(), runner_before["installed"], blocked=True)
                    break
                except DeploymentError:
                    if time.monotonic() >= deadline:
                        raise
                    time.sleep(1)
            phase("verified", state="succeeded", after=after, verified=True)
            uncertain = False
        except Exception as exc:
            reason = str(exc) if isinstance(exc, DeploymentError) else type(exc).__name__
            phase("failed", failed_phase=record.get("phase"),
                  state="uncertain" if uncertain else "failed", error=reason, after=fixture_observation())
        finally:
            if marker_owned and not uncertain:
                marker = ROOT / ".deploying"
                if marker.read_text().strip() == attempt:
                    marker.unlink()
                    sync_directory(ROOT)
            record["interlock_retained"] = (ROOT / ".deploying").exists()
            atomic_json(path, record)
    return record


def require_recovery_stopped(observation: dict[str, Any]) -> None:
    """Accept blocked idle health or both services explicitly inactive after sync."""
    if set(observation["profiles"]) != {profile[0] for profile in PROFILES}:
        raise DeploymentError("Both fixed runner profiles must report recovery state")
    if all("error" not in value for value in observation["profiles"].values()):
        require_release(observation, observation["installed"], blocked=True)
        return
    if any("error" not in value for value in observation["profiles"].values()):
        raise DeploymentError("Partial runner health is unavailable for fixture recovery")
    result = subprocess.run(
        ["/usr/bin/systemctl", "show", "--property=ActiveState", "--value", *SERVICES],
        capture_output=True, timeout=30, check=False,
    )
    if (result.returncode != 0 or result.stdout.decode().split() != ["inactive", "inactive"]
            or observation["installed"] is None):
        raise DeploymentError("Fixture recovery requires both runners stopped or blocked and idle")


def recover_fixture(original_attempt: str, attempt: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Repair public inputs after a retained post-install failure; never provision or reseed."""
    if (not re.fullmatch(r"[0-9a-f]{32}", original_attempt)
            or not re.fullmatch(r"[0-9a-f]{32}", attempt) or attempt == original_attempt):
        raise DeploymentError("Invalid fixture recovery attempt")
    protected_directory(ROOT)
    if os.geteuid() != PRIVILEGED_UID:
        raise DeploymentError("Fixture recovery requires root")
    receipts = ROOT / "deployments"
    path = receipts / (attempt + "-fixture-recovery.json")
    original_path = receipts / (original_attempt + "-fixture.json")
    marker = ROOT / ".deploying"
    record: dict[str, Any] = {
        "adapter": ADAPTER, "operation": "recover-fixture", "attempt": attempt,
        "original_attempt": original_attempt, "state": "running", "events": [],
    }
    marker_owned = False

    def phase(name: str, **values: Any) -> None:
        record.update(phase=name, **values)
        record["events"].append({"phase": name, "at": time.time()})
        atomic_json(path, record)
        path.chmod(0o644)
        with path.open("rb") as stream:
            os.fsync(stream.fileno())

    with (ROOT / ".deployment-lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        protected_directory(receipts)
        if path.exists() or path.is_symlink():
            raise DeploymentError("Recovery attempt already exists; inspect its receipt instead of retrying")
        try:
            phase("inspect")
            protected_file(marker)
            protected_file(original_path)
            original_pins = {marker: pinned_path(marker), original_path: pinned_path(original_path)}
            original = json.loads(original_pins[original_path][1])
            events = [event.get("phase") for event in original.get("events", [])]
            verification_failure = (
                original.get("failed_phase") == "verify-fixture"
                and "provision" in events
                and "verify-fixture" in events
                and events.index("provision") < events.index("verify-fixture")
            )
            provisioning_failure = (
                original.get("failed_phase") == "provision"
                and "provision" in events
                and "verify-fixture" not in events
            )
            if (deployment_marker_owner(original_pins[marker][1]) != original_attempt
                    or original.get("adapter") != ADAPTER or original.get("operation") != "sync-fixture"
                    or original.get("attempt") != original_attempt or original.get("state") != "uncertain"
                    or not (verification_failure or provisioning_failure)):
                raise DeploymentError("Recovery requires the matching post-install fixture failure")
            backup = receipts / (original_attempt + "-fixture-backup")
            if original.get("backup") != str(backup):
                raise DeploymentError("Original fixture backup identity mismatch")
            protected_directory(backup)
            marker_owned = True
            record.update(original_receipt={"path": str(original_path),
                          "sha256": hashlib.sha256(original_pins[original_path][1]).hexdigest()},
                          original_backup=str(backup))
            runner_before = inspect()
            if runner_before["marker"] != original_attempt:
                raise DeploymentError("Fixture recovery marker owner differs")
            require_recovery_stopped(runner_before)
            contents, digest, artifact = fixture_contents(payload)
            legacy, runner_gid, config_pins = configuration_layout()
            if legacy:
                raise DeploymentError("Fixture recovery requires the protected configuration layout")
            for directory in {FIXTURE_ROOT, RESET_HELPER.parent}:
                protected_directory(directory)
            public_pins = {}
            for destination in fixture_paths().values():
                protected_file(destination)
                public_pins[destination] = pinned_path(destination)
            private = json.loads(config_pins[WORDPRESS_CONFIG][1])
            private["target_artifact_identity"] = artifact
            phase("validated", expected=payload["identity"], artifact_identity=artifact, fixture_digest=digest,
                  before=fixture_observation())
            revalidate_pins({**original_pins, **config_pins, **public_pins})
            require_recovery_stopped(inspect())
            phase("install")
            for name, destination in fixture_paths().items():
                mode = 0o755 if name in {"fixture/setup.sh", "fixture/seed.sh"} else 0o644
                replace_file(destination, contents[name], mode, PRIVILEGED_UID, PRIVILEGED_UID)
            revalidate_pins({**original_pins, WORDPRESS_CONFIG: config_pins[WORDPRESS_CONFIG],
                             RUNNER_CONFIG: config_pins[RUNNER_CONFIG]})
            replace_file(WORDPRESS_CONFIG, json.dumps(private).encode(), 0o640, PRIVILEGED_UID, runner_gid)
            if provisioning_failure:
                phase("restore-dependencies")
                restore_fixture_dependencies()
            phase("verify-fixture")
            verify_fixture()
            revalidate_pins(original_pins)
            after = fixture_observation()
            if (after["installed"] != payload["identity"] or after["artifact_identity"] != artifact
                    or "error" in after):
                raise DeploymentError("Recovered fixture/configuration identity mismatch")
            phase("restart", after=after)
            systemctl("restart")
            revalidate_pins(original_pins)
            phase("verify-runners")
            deadline = time.monotonic() + 30
            while True:
                runner_after = inspect()
                try:
                    if runner_after["marker"] != original_attempt:
                        raise DeploymentError("Fixture recovery marker owner differs")
                    require_release(runner_after, runner_before["installed"], blocked=True)
                    break
                except DeploymentError:
                    if time.monotonic() >= deadline:
                        raise
                    time.sleep(1)
            revalidate_pins(original_pins)
            phase("verified-blocked", verified=True, after=after,
                  runner_after=runner_after, interlock_retained=True)
            completed = {**record, "phase": "verified", "state": "succeeded", "interlock_retained": False,
                         "events": [*record["events"], {"phase": "verified", "at": time.time()}]}
            encoded = json.dumps(completed, sort_keys=True, separators=(",", ":")).encode()
            envelope = {"adapter": ADAPTER, "operation": "recover-fixture", "original_attempt": original_attempt,
                        "recovery_attempt": attempt, "state": "verified", "receipt_sha256": hashlib.sha256(encoded).hexdigest(),
                        "final_receipt": completed}
            staged_bytes = json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode()
            if staged_fixture_receipt(staged_bytes) != completed:
                raise DeploymentError("Fixed recovery completion envelope is invalid")
            revalidate_pins(original_pins)
            # The marker remains present until its bytes become the authoritative
            # receipt in one atomic rename. No unlink-before-receipt crash window.
            replace_file(marker, staged_bytes, 0o644, PRIVILEGED_UID, PRIVILEGED_UID)
            staged_pin = pinned_path(marker)
            if staged_pin[1] != staged_bytes:
                raise DeploymentError("Fixture recovery completion marker changed")
            revalidate_pins({original_path: original_pins[original_path], marker: staged_pin})
            os.replace(marker, path)
            sync_directory(ROOT)
            sync_directory(receipts)
            protected_file(path)
            durable = staged_fixture_receipt(path.read_bytes())
            if durable is None or durable != completed:
                raise DeploymentError("Durable fixture recovery completion differs")
            record = durable
        except Exception as exc:
            reason = str(exc) if isinstance(exc, DeploymentError) else type(exc).__name__
            if marker_owned:
                if not marker.exists() and not marker.is_symlink():
                    try:
                        descriptor = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
                    except FileExistsError:
                        pass  # A different owner won the path; never replace it.
                    else:
                        with os.fdopen(descriptor, "wb") as stream:
                            os.fchmod(stream.fileno(), 0o644)
                            stream.write(original_pins[marker][1])
                            stream.flush()
                            os.fsync(stream.fileno())
                        sync_directory(ROOT)
                elif not marker.is_symlink():
                    try:
                        protected_file(marker)
                        marker_pin = pinned_path(marker)
                    except (OSError, DeploymentError):
                        pass  # An unsupported replacement remains a conflict.
                    else:
                        staged = staged_fixture_receipt(marker_pin[1])
                        if staged is not None and staged["original_attempt"] == original_attempt and staged["attempt"] == attempt:
                            revalidate_pins({marker: marker_pin})
                            replace_file(
                                marker, original_pins[marker][1], 0o644,
                                PRIVILEGED_UID, PRIVILEGED_UID,
                            )
            owner = inspect()["marker"]
            phase("failed", failed_phase=record.get("phase"), state="uncertain", error=reason,
                  after=fixture_observation(), interlock_retained=owner == original_attempt,
                  marker_conflict=owner is not None and owner != original_attempt)
    return record


def bootstrap(attempt: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Adopt the fixed legacy layout after explicitly stopping both runners."""
    if not re.fullmatch(r"[0-9a-f]{32}", attempt):
        raise DeploymentError("Invalid deployment attempt")
    if os.geteuid() != PRIVILEGED_UID or ROOT.stat().st_uid != PRIVILEGED_UID:
        raise DeploymentError("Runner deployment requires its root-owned installation directory")
    receipts = ROOT / "deployments"
    path = receipts / (attempt + ".json")
    record: dict[str, Any] = {
        "adapter": ADAPTER, "operation": "bootstrap", "attempt": attempt,
        "state": "running", "events": [],
    }
    marker_owned = False
    uncertain = False

    def phase(name: str, **values: Any) -> None:
        record.update(phase=name, **values)
        record["events"].append({"phase": name, "at": time.time()})
        atomic_json(path, record)

    with (ROOT / ".deployment-lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        receipts.mkdir(exist_ok=True)
        if path.exists() or path.is_symlink():
            raise DeploymentError("Attempt already exists; inspect its receipt instead of retrying")
        try:
            phase("inspect")
            before = inspect()
            record["before"] = before
            if before["marker"] is not None:
                raise DeploymentError("Existing deployment interlock retained; inspect and recover its owner")
            require_legacy_layout()
            if set(payload) != {"files", "identity"} or set(payload["files"]) != set(FILES):
                raise DeploymentError("Bundle must contain exactly the two fixed source files")
            contents = {name: base64.b64decode(payload["files"][name], validate=True) for name in FILES}
            expected = identity(contents)
            record["expected"] = expected
            if expected != payload["identity"]:
                raise DeploymentError("Transferred bundle hash mismatch")
            previous_contents = {name: (ROOT / name).read_bytes() for name in FILES}
            if identity(previous_contents) != before["installed"]:
                raise DeploymentError("Installed source changed since inspection")

            phase("interlock")
            marker = ROOT / ".deploying"
            with marker.open("x") as stream:
                stream.write(attempt)
                stream.flush()
                os.fsync(stream.fileno())
            marker.chmod(0o644)
            marker_owned = True
            uncertain = True
            sync_directory(ROOT)
            phase("stop")
            systemctl("stop")
            phase("stage")
            directory = save_bundle(contents, expected)
            previous = save_bundle(previous_contents, before["installed"])
            phase("activate", previous=before["installed"])
            activate(directory, previous, services_stopped=True)
            phase("restart")
            systemctl("restart")
            phase("verify")
            deadline = time.monotonic() + 30
            while True:
                after = inspect()
                try:
                    require_release(after, expected, blocked=True)
                    break
                except DeploymentError:
                    if time.monotonic() >= deadline:
                        record["after"] = after
                        raise
                    time.sleep(1)
            phase("verified", state="succeeded", after=after)
            uncertain = False
        except Exception as exc:
            reason = str(exc) if isinstance(exc, DeploymentError) else type(exc).__name__
            phase(
                "failed", failed_phase=record.get("phase"),
                state="uncertain" if uncertain else "failed", error=reason, after=inspect(),
            )
        finally:
            if marker_owned and not uncertain:
                marker = ROOT / ".deploying"
                if marker.read_text().strip() == attempt:
                    marker.unlink()
                    sync_directory(ROOT)
            record["interlock_retained"] = (ROOT / ".deploying").exists()
            atomic_json(path, record)
    return record


def deploy(attempt: str, payload: dict[str, Any]) -> dict[str, Any]:
    if not re.fullmatch(r"[0-9a-f]{32}", attempt):
        raise DeploymentError("Invalid deployment attempt")
    if os.geteuid() != PRIVILEGED_UID or ROOT.stat().st_uid != PRIVILEGED_UID:
        raise DeploymentError("Runner deployment requires its root-owned installation directory")
    receipts = ROOT / "deployments"
    path = receipts / (attempt + ".json")
    record: dict[str, Any] = {"adapter": ADAPTER, "attempt": attempt, "state": "running", "events": []}
    marker_owned = False
    uncertain = False

    def phase(name: str, **values: Any) -> None:
        record.update(phase=name, **values)
        record["events"].append({"phase": name, "at": time.time()})
        atomic_json(path, record)

    # Serialize deployments without truncating a previous attempt's marker.
    with (ROOT / ".deployment-lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        receipts.mkdir(exist_ok=True)
        if path.exists() or path.is_symlink():
            raise DeploymentError("Attempt already exists; inspect its receipt instead of retrying")
        try:
            phase("inspect")
            before = inspect()
            record["before"] = before
            if before["marker"] is not None:
                raise DeploymentError("Existing deployment interlock retained; inspect and recover its owner")
            require_release(before, before["installed"], blocked=False)
            if set(payload) != {"files", "identity"} or set(payload["files"]) != set(FILES):
                raise DeploymentError("Bundle must contain exactly the two fixed source files")
            contents = {name: base64.b64decode(payload["files"][name], validate=True) for name in FILES}
            expected = identity(contents)
            record["expected"] = expected
            if expected != payload["identity"]:
                raise DeploymentError("Transferred bundle hash mismatch")
            if before["installed"] == expected:
                require_release(before, expected, blocked=False)
                phase("verified", state="noop", after=before)
                return record
            phase("interlock")
            marker = ROOT / ".deploying"
            with marker.open("x") as stream:
                stream.write(attempt)
                stream.flush()
                os.fsync(stream.fileno())
            marker.chmod(0o644)
            marker_owned = True
            sync_directory(ROOT)
            # The marker blocks new permits before this second health check.
            require_idle(inspect(), blocked=True)
            phase("stage")
            directory = save_bundle(contents, expected)
            previous_contents = {name: (ROOT / name).read_bytes() for name in FILES}
            if identity(previous_contents) != before["installed"]:
                raise DeploymentError("Installed source changed since inspection")
            previous = save_bundle(previous_contents, before["installed"])
            phase("activate", previous=before["installed"])
            uncertain = True
            activate(directory, previous)
            phase("restart")
            systemctl("restart")
            phase("verify")
            # Service startup is asynchronous; only read-only health is polled.
            deadline = time.monotonic() + 30
            while True:
                after = inspect()
                try:
                    require_release(after, expected, blocked=True)
                    break
                except DeploymentError:
                    if time.monotonic() >= deadline:
                        record["after"] = after
                        raise
                    time.sleep(1)
            phase("verified", state="succeeded", after=after)
            uncertain = False
        except Exception as exc:
            # Never emit raw guest/subprocess/HTTP exceptions containing secrets.
            reason = str(exc) if isinstance(exc, DeploymentError) else type(exc).__name__
            phase("failed", failed_phase=record.get("phase"), state="uncertain" if uncertain else "failed", error=reason, after=inspect())
        finally:
            if marker_owned and not uncertain:
                marker = ROOT / ".deploying"
                if marker.read_text().strip() == attempt:
                    marker.unlink()
                    sync_directory(ROOT)
            record["interlock_retained"] = (ROOT / ".deploying").exists()
            atomic_json(path, record)
    return record


def main() -> int:
    if sys.argv[1:] == ["inspect"]:
        print(json.dumps(inspect()))
        return 0
    if len(sys.argv) == 5 and sys.argv[1] == "recover-fixture":
        result = recover_fixture(sys.argv[2], sys.argv[3], decode_payload(sys.argv[4]))
        print(json.dumps(result))
        return 0 if result["state"] == "succeeded" else 1
    if len(sys.argv) != 4 or sys.argv[1] not in {"bootstrap", "deploy", "sync-fixture"}:
        raise DeploymentError("Unsupported fixed adapter action")
    operation = {"bootstrap": bootstrap, "deploy": deploy, "sync-fixture": sync_fixture}[sys.argv[1]]
    result = operation(sys.argv[2], decode_payload(sys.argv[3]))
    print(json.dumps(result))
    return 0 if result["state"] in {"noop", "succeeded"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
