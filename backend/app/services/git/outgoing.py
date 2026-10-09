"""Fail-closed, transport-independent checks for complete outgoing Git history.

No source marker grants permission. Callers supply the actual destination and
pre-push object/ref tuples; this module performs only local inspection.
"""

from __future__ import annotations

import argparse
import fnmatch
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from app.utils import safe_subprocess
from app.utils.heavy_work import HeavyWork, HeavyWorkError, heavy_work
from app.utils.transient_scratch import current_scratch, scratch_subprocess_env


class OutgoingVerificationError(RuntimeError):
    """Outgoing objects cannot be certified safe; messages never include content."""


class OutgoingAdmissionUnavailable(OutgoingVerificationError):
    """Shared admission infrastructure is unavailable, not a source finding."""


@dataclass(frozen=True)
class PushUpdate:
    local_ref: str
    local_oid: str
    remote_ref: str
    remote_oid: str


@dataclass(frozen=True)
class OutgoingVerification:
    commits_scanned: int
    refs_checked: int


_OID = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
_BEGIN = rb"-----" + rb"BEGIN "
_CONTENT = re.compile(
    _BEGIN + rb"[A-Z ]*PRIVATE KEY-----|" + _BEGIN + rb"PGP PRIVATE KEY BLOCK-----"
    rb"|\bAKIA[0-9A-Z]{16}\b|aws_secret_access_key\s*=\s*[A-Za-z0-9/+=]{40}"
    rb"|gh[pousr]_[A-Za-z0-9]{36}|glpat-[A-Za-z0-9_-]{20}"
    rb"|xox[baprs]-[A-Za-z0-9-]{10,}|AIza[0-9A-Za-z_-]{35}"
    rb"|sk-ant-[A-Za-z0-9_-]{24,}|sk-(?:proj-)?[A-Za-z0-9]{32,}"
    rb"|[rs]k_live_[A-Za-z0-9]{16,}|\bSK[0-9a-fA-F]{32}\b"
    rb"|SG\.[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,}|npm_[A-Za-z0-9]{36}"
    rb"|pypi-AgEIcHlwaS5vcmc[A-Za-z0-9_-]{50,}"
    rb'|"private_key"\s*:\s*"-----BEGIN'
    rb"|CF-Access-Client-Secret\s*[:=]\s*[A-Za-z0-9]{32,}"
    rb"|eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"
)


def _git(repo: Path, *args: str, timeout: int = 120) -> bytes:
    try:
        result = safe_subprocess.run(
            ["git", "--no-replace-objects", "-C", str(repo), *args],
            capture_output=True, check=False, timeout=timeout,
            env={key: value for key, value in os.environ.items() if not key.startswith("GIT_")},
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise OutgoingVerificationError("Outgoing Git inspection failed.") from exc
    if result.returncode:
        raise OutgoingVerificationError("Outgoing history or objects are unavailable.")
    return result.stdout


def _destination(value: str) -> None:
    if not value or value.startswith("-") or any(ord(c) < 33 for c in value):
        raise OutgoingVerificationError("Invalid publication destination.")
    if "://" in value:
        parsed = urlsplit(value)
        if parsed.scheme not in {"https", "ssh", "git", "file"} or parsed.password or parsed.query or parsed.fragment:
            raise OutgoingVerificationError("Invalid publication destination.")
        if parsed.scheme != "file" and (not parsed.hostname or not parsed.path):
            raise OutgoingVerificationError("Invalid publication destination.")
        if parsed.scheme == "https" and parsed.username:
            raise OutgoingVerificationError("Credentials must not be embedded in publication destination.")
    elif not (value.startswith("/") or re.fullmatch(r"(?:[\w.-]+@)?[\w.-]+:[\w./~-]+", value)):
        raise OutgoingVerificationError("Unsupported publication destination.")


def _patterns(policy: Path, filename: str) -> list[str]:
    try:
        lines = (policy / filename).read_text().splitlines()
    except OSError as exc:
        raise OutgoingVerificationError("Secret path policy is unavailable.") from exc
    return [line.strip().lower() for line in lines if line.strip() and not line.lstrip().startswith("#")]


def _matches(path: str, patterns: Sequence[str]) -> bool:
    lowered = path.lower()
    return any(
        fnmatch.fnmatchcase(candidate, pattern)
        for pattern in patterns
        for candidate in (lowered, lowered.rsplit("/", 1)[-1], *lowered.split("/", 1)[1:])
    ) or any(fnmatch.fnmatchcase(lowered, "*/" + pattern) for pattern in patterns)


def _lone_token(path: str, body: bytes) -> bool:
    if any(_matches(path, [pattern]) for pattern in (
        "*/testdata/*", "testdata/*", "*/fixtures/*", "fixtures/*", "*/testvectors/*",
        "*vector*", "*golden*", "*expected*", "*.lock", "*lock.json",
    )):
        return False
    lines = [line for line in body.splitlines() if line.strip()]
    token = re.sub(rb"\s", b"", body)
    return (
        len(lines) <= 1 and 16 <= len(token) <= 512
        and re.fullmatch(rb"[A-Za-z0-9+/=_.-]+", token) is not None
        and all(re.search(pattern, token) for pattern in (rb"[a-z]", rb"[A-Z]", rb"[0-9]"))
    )


def _reviewed_npmrc(path: str, mode: bytes, body: bytes, denied: Sequence[str]) -> bool:
    """Only the reviewed root build-safety grammar can bypass its filename deny.

    This never exempts content or scanner checks, nor additional owner deny rules.
    Unknown package-manager settings require review rather than a broad allowlist.
    """
    if path != ".npmrc" or mode != b"100644" or not body.isascii():
        return False
    if any(pattern != ".npmrc" for pattern in denied if _matches(path, [pattern])):
        return False
    values = {
        b"minimum-release-age": b"1440",
        b"block-exotic-subdeps": b"true",
        b"strict-dep-builds": b"true",
        b"dangerously-allow-all-builds": b"false",
        b"verify-store-integrity": b"true",
    }
    if any(char < 32 and char != 10 for char in body):
        return False
    seen: set[bytes] = set()
    for line in body.split(b"\n"):
        if not line:
            continue
        key, separator, value = line.partition(b"=")
        if not separator or key in seen or key not in values or value != values[key]:
            return False
        seen.add(key)
    return bool(seen)


def verify_outgoing(
    repo: str | Path, remote_url: str, updates: Sequence[PushUpdate], *,
    scanner: str | None = None, policy_dir: str | Path | None = None,
    published_bases: Sequence[str] = (),
) -> OutgoingVerification:
    """Admit complete outgoing verification before history/tree materialization."""
    try:
        with heavy_work("outgoing verification") as work:
            return _verify_outgoing(repo, remote_url, updates, scanner=scanner,
                                    policy_dir=policy_dir, published_bases=published_bases, work=work)
    except HeavyWorkError as exc:
        raise OutgoingAdmissionUnavailable("Outgoing verification admission is unavailable.") from exc


def _verify_outgoing(
    repo: str | Path, remote_url: str, updates: Sequence[PushUpdate], *,
    scanner: str | None, policy_dir: str | Path | None,
    published_bases: Sequence[str], work: HeavyWork,
) -> OutgoingVerification:
    """Verify exact update tuples and all outgoing trees, with no history cap.

    Missing old objects, shallow/grafted history, scanner/policy failures, and
    any finding fail closed. New refs scan every ancestor. Ref deletions carry
    no content but still require a valid destination and update tuple.
    """
    root = Path(repo).resolve()
    _destination(remote_url)
    if not updates:
        raise OutgoingVerificationError("No publication updates supplied.")
    if _git(root, "rev-parse", "--is-shallow-repository").strip() != b"false":
        raise OutgoingVerificationError("Complete outgoing history is required; shallow repository refused.")
    grafts = Path(os.fsdecode(_git(root, "rev-parse", "--git-path", "info/grafts").strip()))
    if not grafts.is_absolute():
        grafts = root / grafts
    if grafts.exists() and grafts.stat().st_size:
        raise OutgoingVerificationError("Grafted history cannot certify outgoing objects.")
    policy = Path(policy_dir) if policy_dir is not None else Path.home() / ".config/git/secretguard"
    denied, allowed = _patterns(policy, "denylist.txt"), _patterns(policy, "allowlist.txt")
    if not denied:
        raise OutgoingVerificationError("Empty secret path policy refused.")
    scanner_bin = shutil.which(scanner or "gitleaks")
    if scanner_bin is None:
        raise OutgoingVerificationError("Required outgoing secret scanner is unavailable.")
    revisions: list[str] = []
    commits: set[str] = set()
    refs: set[str] = set()
    for base in published_bases:
        if not _OID.fullmatch(base):
            raise OutgoingVerificationError("Invalid live destination base object.")
        _git(root, "cat-file", "-e", base + "^{commit}")
    for update in updates:
        if not _OID.fullmatch(update.local_oid) or not _OID.fullmatch(update.remote_oid):
            raise OutgoingVerificationError("Invalid outgoing object identifier.")
        # Git allows HEAD/revision/raw-OID sources (ST publishes captured OIDs).
        # The source label is never used for object resolution or subprocess args.
        if not update.local_ref or any(ord(c) < 33 for c in update.local_ref):
            raise OutgoingVerificationError("Invalid outgoing source label.")
        if not update.remote_ref.startswith("refs/") or any(ord(c) < 33 for c in update.remote_ref):
            raise OutgoingVerificationError("Invalid outgoing destination ref.")
        _git(root, "check-ref-format", update.remote_ref)
        if update.remote_ref == "(delete)" or update.remote_ref in refs:
            raise OutgoingVerificationError("Invalid or duplicate destination ref.")
        refs.add(update.remote_ref)
        if set(update.local_oid) == {"0"}:
            continue
        _git(root, "cat-file", "-e", update.local_oid + "^{commit}")
        # Annotated tag bodies are transported too, not just their commit trees.
        object_kind = _git(root, "cat-file", "-t", update.local_oid).strip()
        if object_kind == b"tag" and _CONTENT.search(_git(root, "cat-file", "tag", update.local_oid)):
            raise OutgoingVerificationError("Outgoing tag contains sensitive content (redacted).")
        revision = update.local_oid
        if set(update.remote_oid) != {"0"}:
            _git(root, "cat-file", "-e", update.remote_oid + "^{commit}")
            if update.remote_ref.startswith("refs/heads/"):
                _git(root, "merge-base", "--is-ancestor", update.remote_oid, update.local_oid)
            elif update.remote_oid != update.local_oid:
                raise OutgoingVerificationError("Replacing existing publication tags is refused.")
            revision = update.remote_oid + ".." + update.local_oid
        elif published_bases:
            applicable = [base for base in published_bases if _is_ancestor(root, base, update.local_oid)]
            revision = " ".join([update.local_oid, *("^" + base for base in applicable)])
        revisions.append(revision)
        commits.update(_git(root, "rev-list", *revision.split()).decode("ascii").splitlines())
    seen: set[tuple[bytes, bytes, bytes]] = set()
    for commit in sorted(commits):
        if _CONTENT.search(_git(root, "cat-file", "commit", commit)):
            raise OutgoingVerificationError("Outgoing commit metadata contains sensitive content (redacted).")
        for entry in _git(root, "ls-tree", "-rz", "--full-tree", commit).split(b"\0"):
            if not entry:
                continue
            metadata, path_bytes = entry.split(b"\t", 1)
            mode, kind, oid = metadata.split()
            if kind != b"blob" or (path_bytes, mode, oid) in seen:
                continue
            seen.add((path_bytes, mode, oid))
            path = os.fsdecode(path_bytes)
            body = _git(root, "cat-file", "blob", oid.decode("ascii"))
            if (not _matches(path, allowed) and _matches(path, denied)
                    and not _reviewed_npmrc(path, mode, body, denied)):
                raise OutgoingVerificationError("Outgoing history contains a secret-sensitive path (content redacted).")
            if _CONTENT.search(body) or _lone_token(path, body):
                raise OutgoingVerificationError("Outgoing history contains sensitive content (redacted).")
    if revisions:
        # Pin built-in rules and neutralize repo/environment exclusions. Findings
        # and scanner errors are intentionally not echoed, even with --redact.
        process_env = scratch_subprocess_env()
        temporary_parent = process_env.get("TMPDIR") if current_scratch() is not None else None
        with tempfile.TemporaryDirectory(prefix="st-outgoing-", dir=temporary_parent) as directory:
            config = Path(directory) / "gitleaks.toml"
            config.write_text("[extend]\nuseDefault = true\n")
            env = {key: value for key, value in process_env.items() if not key.startswith(("GITLEAKS_", "GIT_"))}
            env["GIT_NO_REPLACE_OBJECTS"] = "1"
            for revision in revisions:
                try:
                    result = safe_subprocess.run_inherited(
                        work.command([scanner_bin, "git", "--no-banner", "--redact=100", "--log-level", "error",
                         "--ignore-gitleaks-allow", "--config", str(config),
                         "--gitleaks-ignore-path", directory, "--log-opts=" + revision, str(root)]),
                        inherit_fds=work.pass_fds, env=work.environment(env), timeout=300,
                    )
                except (OSError, subprocess.TimeoutExpired) as exc:
                    raise OutgoingVerificationError("Outgoing secret scan failed or timed out.") from exc
                if result.returncode:
                    raise OutgoingVerificationError("Outgoing secret scan refused history or failed (details redacted).")
    return OutgoingVerification(len(commits), len(updates))


def _is_ancestor(root: Path, base: str, oid: str) -> bool:
    try:
        result = safe_subprocess.run(["git", "--no-replace-objects", "-C", str(root), "merge-base", "--is-ancestor", base, oid],
                                capture_output=True, timeout=120,
                                env={key: value for key, value in os.environ.items() if not key.startswith("GIT_")})
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise OutgoingVerificationError("Live destination ancestry inspection failed.") from exc
    if result.returncode not in {0, 1}:
        raise OutgoingVerificationError("Live destination ancestry is incomplete.")
    return result.returncode == 0


def live_destination_bases(repo: str | Path, remote_url: str) -> tuple[str, ...]:
    """Read the live destination default HEAD, never cached tracking refs.

    Only new refs need this bounded read. Empty destinations have no exclusions;
    unreadable requested destinations or missing advertised objects fail closed.
    """
    root = Path(repo).resolve()
    _destination(remote_url)
    output = _git(root, "ls-remote", "--symref", remote_url, "HEAD", timeout=30).decode("ascii")
    bases = [line.split()[0] for line in output.splitlines() if not line.startswith("ref:")]
    if len(bases) > 1 or any(not _OID.fullmatch(base) for base in bases):
        raise OutgoingVerificationError("Ambiguous live destination default ref.")
    for base in bases:
        try:
            _git(root, "cat-file", "-e", base + "^{commit}")
        except OutgoingVerificationError:
            _git(root, "fetch", "--no-tags", remote_url, base, timeout=30)
            _git(root, "cat-file", "-e", base + "^{commit}")
    return tuple(bases)


def parse_updates(data: str) -> tuple[PushUpdate, ...]:
    try:
        return tuple(PushUpdate(*line.split()) for line in data.splitlines() if line.strip())
    except TypeError as exc:
        raise OutgoingVerificationError("Malformed pre-push input.") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("remote_name")
    parser.add_argument("remote_url")
    parser.add_argument("--repo", default=".")
    args = parser.parse_args()
    try:
        updates = parse_updates(sys.stdin.read())
        bases = live_destination_bases(args.repo, args.remote_url) if any(set(update.remote_oid) == {"0"} and set(update.local_oid) != {"0"} for update in updates) else ()
        verify_outgoing(args.repo, args.remote_url, updates, published_bases=bases)
    except (OutgoingVerificationError, ValueError, OSError) as exc:
        print(f"Publication refused: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
