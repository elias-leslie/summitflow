"""Best-effort publication of existing default-branch commits before backups.

The scheduler opts in through backup_publish_before_backup. Every result permits
backup capture to continue; failed/pending publication stays retryable through
the existing completed-backup verification record. This helper creates no commit
and never modifies the worktree, index, branch or upstream configuration.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from ..services.git.utils import network_repository_identity
from ..utils import safe_subprocess


class _InspectionFailed(RuntimeError):
    """Local inspection failed; no raw Git diagnostic escapes to records."""


class _TransportUnavailable(_InspectionFailed):
    """Remote transport cannot establish evidence; not a source repair finding."""


class _OutgoingFailed(RuntimeError):
    """Publication security evidence was unavailable or rejected."""


def publication_window_open(now: datetime | None = None) -> bool:
    """Scheduled publication is limited to 02:00-06:00 New York, including DST."""
    local = (now or datetime.now(UTC)).astimezone(ZoneInfo("America/New_York"))
    return 2 <= local.hour < 6


def _git(project: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    environment.update(GIT_OPTIONAL_LOCKS="0", GIT_NO_LAZY_FETCH="1", GIT_TERMINAL_PROMPT="0", GIT_NO_REPLACE_OBJECTS="1")
    command = ["git", "-C", str(project), *arguments]
    network = arguments[0] in {"push", "fetch", "ls-remote"}
    if network:
        watchdog = shutil.which("timeout")
        if watchdog is None:
            raise _TransportUnavailable
        ssh = _git(project, "config", "--get", "core.sshCommand")
        if ssh.returncode not in {0, 1}:
            raise _InspectionFailed
        ssh_command = os.environ.get("GIT_SSH_COMMAND") or (ssh.stdout.strip() if ssh.returncode == 0 else "ssh")
        environment.update(GCM_INTERACTIVE="Never", GIT_SSH_COMMAND=ssh_command + " -o BatchMode=yes -o ConnectTimeout=15")
        command = [watchdog, "--signal=TERM", "--kill-after=5s", "300s", *command]
    try:
        return safe_subprocess.run(
            command, capture_output=True,
            text=True, stdin=subprocess.DEVNULL, env=environment,
            timeout=310 if network else 30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        if network:
            raise _TransportUnavailable from exc
        raise _InspectionFailed from exc


def _value(project: Path, *arguments: str) -> str:
    result = _git(project, *arguments)
    if result.returncode != 0:
        raise _InspectionFailed
    return result.stdout.strip()


def _acceptance_for_head(project: Path, head: str) -> dict[str, Any]:
    """Reuse the canonical exact-source validator; never run a daily gate."""
    try:
        # The canonical validator reads Git blobs. In a partial clone that can
        # lazily fetch, so omit optional receipt reuse rather than let an offline
        # validation wait outside the bounded publication transport.
        partial = _git(project, "config", "--get-regexp", r"^(extensions\.partialclone|remote\..*\.promisor)$")
        if partial.returncode == 0:
            return {"state": "unavailable", "reason": "partial_clone"}
        common = Path(_value(project, "rev-parse", "--path-format=absolute", "--git-common-dir"))
        candidates = sorted((common / "st" / "acceptance").glob("*.json"), key=lambda path: path.stat().st_mtime_ns, reverse=True)[:64]
        matched = False
        for artifact in candidates:
            if artifact.is_symlink() or not artifact.is_file() or artifact.stat().st_size > 4 * 1024 * 1024:
                continue
            try:
                receipt = json.loads(artifact.read_text())
                if not isinstance(receipt, dict) or not isinstance(receipt.get("source"), dict) or receipt["source"].get("commit") != head:
                    continue
                matched = True
                from cli.lib.acceptance import validate_acceptance_receipt

                validated = validate_acceptance_receipt(project, artifact, sha=head)
                return {"state": "reused", "acceptance_id": validated["acceptance_id"], "source_commit": head}
            except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
                continue
        return {"state": "invalid" if matched else "missing"}
    except (ImportError, OSError, RuntimeError):
        return {"state": "unavailable"}


def _public_evidence(value: Any) -> Any:
    """Exclude raw command/API diagnostics from durable backup evidence."""
    if isinstance(value, dict):
        return {key: _public_evidence(item) for key, item in value.items()
                if key not in {"detail", "stdout", "stderr", "error"}}
    if isinstance(value, list):
        return [_public_evidence(item) for item in value]
    return value


def _reviewed_jj_source(project: Path, default_head: str) -> str:
    """Resolve reviewed immutable JJ work without snapshotting its mutable @."""
    try:
        common = Path(_value(project, "rev-parse", "--path-format=absolute", "--git-common-dir"))
        artifacts = sorted((common / "st" / "acceptance").glob("*.json"), key=lambda path: path.stat().st_mtime_ns, reverse=True)[:64]
        for artifact in artifacts:
            if artifact.is_symlink() or not artifact.is_file() or artifact.stat().st_size > 4 * 1024 * 1024:
                continue
            try:
                receipt = json.loads(artifact.read_text())
                receipt_source = receipt.get("source") if isinstance(receipt, dict) else None
                candidate = receipt_source.get("commit") if isinstance(receipt_source, dict) else None
                if not isinstance(candidate, str) or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", candidate):
                    continue
                if _git(project, "merge-base", "--is-ancestor", default_head, candidate).returncode != 0:
                    continue
                if _acceptance_for_head(project, candidate).get("state") == "reused":
                    return candidate
            except (OSError, ValueError, TypeError, RuntimeError):
                continue
    except (OSError, RuntimeError):
        pass
    return default_head


def _publish_isolated(project: Path, head: str, branch: str, remote: str,
                      remote_url: str, source_id: str, *, resume: bool) -> dict[str, Any]:
    """Use canonical rules/PR/CI machinery without touching the active checkout."""
    from cli.lib.publish_workflow import PublishError, publish_git

    from ..services.git.outgoing import OutgoingVerificationError, PushUpdate, verify_outgoing

    with tempfile.TemporaryDirectory(prefix="st-nightly-publish-") as directory:
        isolated = Path(directory) / "source"
        cloned = _git(project, "clone", "--shared", "--no-checkout", "--no-hardlinks", str(project), str(isolated))
        if cloned.returncode:
            raise _InspectionFailed
        if _git(isolated, "checkout", "--detach", head).returncode:
            raise _InspectionFailed
        if _git(isolated, "remote", "remove", "origin").returncode or _git(isolated, "remote", "add", remote, remote_url).returncode:
            raise _InspectionFailed
        ssh = _git(project, "config", "--get", "core.sshCommand")
        if ssh.returncode == 0 and _git(isolated, "config", "core.sshCommand", ssh.stdout.strip()).returncode:
            raise _InspectionFailed
        security: dict[str, Any] = {"state": "not_run", "sha": head}
        published_bases: tuple[str, ...] = ()

        def run_git(repo: Path, arguments: list[str]) -> subprocess.CompletedProcess[str]:
            if arguments[0] in {"push", "fetch", "ls-remote"} and not publication_window_open():
                raise _InspectionFailed
            if arguments[0] == "push":
                destination_ref = arguments[-1].split(":", 1)[1]
                observed = run_git(isolated, ["ls-remote", "--refs", remote, destination_ref])
                if observed.returncode:
                    raise _InspectionFailed
                rows = observed.stdout.splitlines()
                if len(rows) > 1:
                    raise _InspectionFailed
                old = rows[0].split()[0] if rows else "0" * len(head)
                if rows and run_git(isolated, ["fetch", "--no-tags", remote, destination_ref]).returncode:
                    raise _InspectionFailed
                try:
                    verified = verify_outgoing(isolated, remote_url,
                        [PushUpdate(f"refs/heads/{branch}", head, destination_ref, old)], published_bases=published_bases)
                except OutgoingVerificationError as exc:
                    raise _OutgoingFailed from exc
                security.update(state="success", commits_scanned=verified.commits_scanned,
                                refs_checked=verified.refs_checked, base_sha=old, destination_ref=destination_ref)
                if not publication_window_open():
                    raise _InspectionFailed
                arguments = ["push", "--porcelain", "--no-follow-tags", "--recurse-submodules=no", *arguments[1:]]
            response = _git(repo, *arguments)
            if arguments[0] in {"push", "fetch", "ls-remote"} and response.returncode:
                # Only porcelain's explicit per-ref rejection proves a project
                # update was refused. Raw transport diagnostics prove no defect.
                rejected = arguments[0] == "push" and any(
                    line.startswith("!\t") and len(line.split("\t")) == 3
                    for line in response.stdout.splitlines())
                if not rejected:
                    raise _TransportUnavailable
            return response

        # Existing PRs and already delivered revisions can be observed/merged
        # without a push. Verify their exact source at this boundary as well.
        base_ref = f"refs/heads/{branch}"
        observed = run_git(isolated, ["ls-remote", "--refs", remote, base_ref])
        if observed.returncode or len(observed.stdout.splitlines()) > 1:
            raise _InspectionFailed
        rows = observed.stdout.splitlines()
        old = rows[0].split()[0] if rows else "0" * len(head)
        if rows:
            fetched = run_git(isolated, ["fetch", "--no-tags", remote, base_ref])
            if fetched.returncode:
                raise _InspectionFailed
            published_bases = (old,)
            if _git(isolated, "merge-base", "--is-ancestor", old, head).returncode != 0:
                # Squash/rebase publication can diverge. No unverified remote
                # reachability exclusion may silently omit local ancestors.
                old = "0" * len(head)
        try:
            verified = verify_outgoing(isolated, remote_url, [PushUpdate(base_ref, head, base_ref, old)], published_bases=published_bases)
        except OutgoingVerificationError as exc:
            raise _OutgoingFailed from exc
        security.update(state="success", commits_scanned=verified.commits_scanned,
                        refs_checked=verified.refs_checked, scope="outgoing_history", base_sha=old,
                        destination_ref=base_ref, published_bases=list(published_bases))
        try:
            delivery = publish_git(isolated, sha=head, task_id=f"nightly-{source_id}-{head[:16]}",
                message=f"Publish reviewed local source {head[:12]}", run_git=run_git,
                remote_name=remote, destination=branch, resume=resume,
                reconcile_checkout=False, activity_allowed=publication_window_open)
        except PublishError as exc:
            window_open = publication_window_open()
            delivery = {"status": "BLOCKED" if window_open and not exc.unavailable else "PENDING", "pushed": False,
                        "publication_complete": False, "ci": {"state": "unavailable", "sha": head},
                        "reason": exc.reason if window_open else "outside_publication_window"}
        return {**_public_evidence(delivery), "security": security}


def publish_source_before_backup(source: dict[str, Any], *, retained: dict[str, Any] | None = None) -> dict[str, Any]:
    """Publish accepted committed source; every outcome allows independent backup."""
    result: dict[str, Any] = {
        "source_id": source.get("id"), "status": "skipped", "attempted": False,
        "backup_can_continue": True,
        "publication_complete": False, "observed_at": datetime.now(UTC).isoformat(),
        "source_status": "unknown", "remote_status": "unobserved",
        "ci": {"state": "unobserved"}, "security": {"state": "not_run"},
    }

    def outcome(status: str, reason: str) -> dict[str, Any]:
        return {**result, "status": status, "reason": reason, "observed_at": datetime.now(UTC).isoformat()}

    if not publication_window_open():
        return outcome("pending", "outside_publication_window")
    if source.get("source_type") != "project":
        return outcome("skipped", "non_project_source")
    if not source.get("id") or not source.get("path"):
        return outcome("skipped", "unregistered_source")
    if source.get("enabled") is not True:
        return outcome("skipped", "disabled_source")
    try:
        project = Path(source["path"]).expanduser().resolve(strict=True)
        if not project.is_dir():
            return outcome("skipped", "not_project_directory")
        colocated = (project / ".jj").is_dir()
        top = _git(project, "rev-parse", "--show-toplevel")
        if top.returncode != 0:
            return outcome("skipped", "not_git_repository")
        if Path(top.stdout.strip()).resolve() != project:
            return outcome("skipped", "repository_root_mismatch")
        symbolic = _git(project, "symbolic-ref", "--quiet", "--short", "HEAD")
        branch = symbolic.stdout.strip()
        if retained and retained.get("branch") in {"main", "master"}:
            branch = retained["branch"]
        if colocated:
            # JJ's @/Git HEAD can contain unfinished work. Use a named default
            # bookmark as the boundary for receipt-selected immutable source.
            branches = [name for name in ("main", "master") if _git(project, "show-ref", "--verify", "--quiet", f"refs/heads/{name}").returncode == 0]
            if len(branches) != 1:
                return outcome("pending", "jj_default_bookmark_required")
            branch = branches[0]
        elif symbolic.returncode != 0 and not (retained and retained.get("branch") in {"main", "master"}):
            return outcome("skipped", "detached_head")
        if branch not in {"main", "master"}:
            return outcome("skipped", "non_default_branch")
        revision = str(retained.get("head")) if retained and retained.get("head") else f"refs/heads/{branch}"
        if retained and retained.get("head") and not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", revision):
            return outcome("failed", "invalid_retained_source")
        head_result = _git(project, "rev-parse", "--verify", f"{revision}^{{commit}}")
        if head_result.returncode != 0:
            return outcome("skipped", "unborn_head")
        head = head_result.stdout.strip()
        if colocated and not (retained and retained.get("head")):
            head = _reviewed_jj_source(project, head)
        result.update(head=head, branch=branch, source_status="captured", vcs="jj" if colocated else "git",
                      source_tree=_value(project, "rev-parse", f"{head}^{{tree}}"))
        route = _value(project, "for-each-ref", "--format=%(upstream)%00%(upstream:remotename)%00%(upstream:remoteref)", f"refs/heads/{branch}").split("\0")
        if colocated and (len(route) != 3 or not all(route)):
            remotes = _value(project, "remote").splitlines()
            if remotes != ["origin"]:
                return outcome("pending", "jj_explicit_remote_required")
            route = [f"refs/remotes/origin/{branch}", "origin", f"refs/heads/{branch}"]
        if len(route) != 3 or not all(route):
            return outcome("skipped", "no_existing_upstream")
        tracking_ref, remote, upstream_ref = route
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", remote) or upstream_ref != f"refs/heads/{branch}" or tracking_ref != f"refs/remotes/{remote}/{branch}":
            return outcome("skipped", "incorrect_upstream_route")
        if not colocated and (_value(project, "config", "--get-all", f"branch.{branch}.remote").splitlines() != [remote] or _value(project, "config", "--get-all", f"branch.{branch}.merge").splitlines() != [upstream_ref]):
            return outcome("skipped", "ambiguous_upstream_route")
        fetch_urls = _value(project, "remote", "get-url", "--all", remote).splitlines()
        push_urls = _value(project, "remote", "get-url", "--push", "--all", remote).splitlines()
        if len(fetch_urls) != 1 or len(push_urls) != 1:
            return outcome("skipped", "ambiguous_remote_route")
        identity = network_repository_identity(fetch_urls[0])
        if identity is None or network_repository_identity(push_urls[0]) != identity:
            return outcome("skipped", "unsafe_remote_route")
        if retained and retained.get("repository") and list(identity) != retained["repository"]:
            return outcome("pending", "repository_changed")
        result["repository"] = list(identity)
        mirror = _git(project, "config", "--bool", "--get", f"remote.{remote}.mirror")
        if mirror.returncode not in {0, 1}:
            return outcome("skipped", "uncertain_mirror_configuration")
        if mirror.returncode == 0 and mirror.stdout.strip() == "true":
            return outcome("skipped", "mirror_remote")
        upstream = _git(project, "rev-parse", "--verify", f"{tracking_ref}^{{commit}}")
        ahead: int | None = None
        behind: int | None = None
        if upstream.returncode == 0:
            upstream_head = upstream.stdout.strip()
            counts = _value(project, "rev-list", "--left-right", "--count", f"{upstream_head}...{head}").split()
            behind, ahead = map(int, counts)
        # A newly provisioned private repository has no tracking commit yet.
        # Exact acceptance still gates publication, and the canonical GitHub
        # adapter establishes its real default/empty state before any push.
        result["upstream_status"] = "observed_locally" if upstream.returncode == 0 else "unobserved_locally"
        result.update(head=head, branch=branch, remote=remote, upstream_ref=upstream_ref, ahead=ahead,
                      behind=behind, source_status="captured", vcs="jj" if colocated else "git")
        result["acceptance"] = _acceptance_for_head(project, head)
        if result["acceptance"].get("state") != "reused":
            result["source_status"] = "acceptance_required"
            result["action"] = "Run st check --acceptance for the exact committed source, then retry nightly publication"
            return outcome("pending", "source_acceptance_required")
        if _value(project, "remote", "get-url", "--push", "--all", remote).splitlines() != push_urls:
            return outcome("pending", "repository_changed")
        result["source_status"] = "accepted"
        result["attempted"] = True
        delivered = _publish_isolated(project, head, branch, remote, push_urls[0], str(source["id"]),
                                      resume=bool(retained and retained.get("pushed")))
        result.update(delivered)
        if delivered.get("publication_complete"):
            try:
                result["codeql"] = _codeql_after_publication(project, source, identity, delivered, head)
            except Exception:
                # Security ingestion may fail independently; retain truthful
                # coverage without discarding completed transport or backups.
                result["codeql"] = {"state": "pending", "reason": "codeql_ingestion_unavailable"}
        result["pushed"] = bool(delivered.get("pushed") or (retained and retained.get("pushed")))
        unavailable = delivered.get("reason") in {
            "remote_transport_unavailable", "remote_authentication_unavailable",
            "remote_rate_limited", "remote_api_unavailable",
        }
        no_ci = isinstance(delivered.get("ci"), dict) and delivered["ci"].get("state") == "not_applicable"
        result["remote_status"] = ("uploaded" if no_ci else "verified") if delivered.get("publication_complete") else "unknown" if unavailable else "pending" if delivered.get("status") == "PENDING" else "blocked"
        status = "published" if delivered.get("publication_complete") else "pending" if delivered.get("status") == "PENDING" else "failed"
        reason = ("uploaded_without_ci" if no_ci else "source_publication_verified") if delivered.get("publication_complete") else str(delivered.get("reason") or "remote_publication_unverified")
        return outcome(status, reason)
    except _OutgoingFailed:
        result["security"] = {"state": "blocked", "sha": result.get("head")}
        result["action"] = "Inspect st vcs doctor and repair outgoing scanner, policy, history or secret findings before retry"
        return outcome("failed", "outgoing_verification_failed")
    except _TransportUnavailable:
        result["remote_status"] = "unknown"
        result["ci"] = {"state": "unavailable", "sha": result.get("head")}
        return outcome("pending", "remote_transport_unavailable" if publication_window_open() else "outside_publication_window")
    except (ImportError, OSError, ValueError, TypeError, RuntimeError, subprocess.SubprocessError):
        if not publication_window_open():
            return outcome("pending", "outside_publication_window")
        return outcome("failed", "publication_inspection_unavailable")


def _codeql_after_publication(project: Path, source: dict[str, Any], identity: tuple[str, int | None, str],
                             delivered: dict[str, Any], head: str) -> dict[str, Any]:
    from cli.details import write_details

    from ..services.publication_security import (
        codeql_metadata,
        observe_codeql,
        record_codeql_observation,
    )

    if identity[0] != "github.com" or identity[1] is not None:
        return {"state": "unavailable", "reason": "codeql_provider_unavailable"}
    expected = delivered.get("merge_sha") or head
    evidence = observe_codeql(project, identity[2], expected_sha=expected)
    ci = delivered.get("ci") or {}
    relation_verified = expected == head or (ci.get("pr_checks") or {}).get("sha") == head
    if (delivered.get("publication_complete") and delivered.get("sha") == head and
            ci.get("state") == "success" and ci.get("sha") == expected and
            evidence.get("source_commit") == expected and evidence.get("source_bound") is True and relation_verified):
        evidence["accepted_source_commit"] = head
    write_details(project, "codeql", json.dumps(evidence, indent=2))
    record_codeql_observation(project, evidence, project_id=source.get("project_id"))
    return codeql_metadata(evidence)
