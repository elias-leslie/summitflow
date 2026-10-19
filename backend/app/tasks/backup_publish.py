"""Guarded publication of one exact committed source by a plain fast-forward push.

Private repositories publish any committed source; public ones (and any
non-GitHub remote) publish only a source with a valid full acceptance receipt.
The outgoing history/secret verifier and the workflow-effects authority gate
run before every push. This helper creates no commit and never modifies the
worktree, index, branch or upstream configuration; the push itself records the
published commit in the checkout's remote-tracking ref.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from contextlib import ExitStack
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..services.git.utils import network_repository_identity
from ..utils import safe_subprocess
from ..utils.agent_execution import run_source_git, source_requires_agent
from ..utils.transient_scratch import scratch_subprocess_env

_OID = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")


class _InspectionFailed(RuntimeError):
    """Local inspection failed; no raw Git diagnostic escapes to records."""


class _TransportUnavailable(_InspectionFailed):
    """Remote transport cannot establish evidence; not a source repair finding."""


class _OutgoingFailed(RuntimeError):
    """Publication security evidence was unavailable or rejected."""


class _AdmissionUnavailable(RuntimeError):
    """Shared validation admission is unavailable, not a source finding."""


def _git(project: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    environment = {key: value for key, value in scratch_subprocess_env().items() if not key.startswith("GIT_")}
    environment.update(GIT_OPTIONAL_LOCKS="0", GIT_NO_LAZY_FETCH="1", GIT_TERMINAL_PROMPT="0", GIT_NO_REPLACE_OBJECTS="1")
    command = ["git", "--no-replace-objects", "-C", str(project), *arguments]
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
        runner = safe_subprocess.run if network else run_source_git
        return runner(
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


def _requires_independent_repository(project: Path) -> bool:
    from ..services import tether

    return source_requires_agent(project) and os.getuid() != tether._agent_uid()


def _acceptance_for_head(project: Path, head: str) -> dict[str, Any]:
    """The canonical full-coverage receipt lookup for one exact commit."""
    try:
        # Receipt validation reads Git blobs. In a partial clone that can
        # lazily fetch outside the bounded publication transport.
        partial = _git(project, "config", "--get-regexp", r"^(extensions\.partialclone|remote\..*\.promisor)$")
        if partial.returncode == 0:
            return {"state": "unavailable", "reason": "partial_clone"}
        from cli.lib.acceptance import receipt_for_commit

        receipt = receipt_for_commit(project, head)
    except (ImportError, OSError, ValueError, RuntimeError, subprocess.SubprocessError):
        return {"state": "unavailable"}
    if receipt is None:
        return {"state": "missing"}
    return {"state": "reused", "acceptance_id": receipt["acceptance_id"], "source_commit": head}


def remote_repository(project: Path, identity: tuple[str, int | None, str]) -> dict[str, Any] | None:
    """GitHub metadata (visibility, default branch); None for any other host."""
    if identity[0] != "github.com" or identity[1] is not None:
        return None
    from cli.lib.github_publish import GitHub

    return GitHub(project, identity[2]).api("")


def is_public(repository: dict[str, Any] | None) -> bool:
    """Only a GitHub repository that says it is private may skip acceptance."""
    return repository is None or repository.get("private") is not True


def _public_evidence(value: Any) -> Any:
    """Exclude raw command/API diagnostics from durable evidence."""
    if isinstance(value, dict):
        return {key: _public_evidence(item) for key, item in value.items()
                if key not in {"detail", "stdout", "stderr", "error"}}
    if isinstance(value, list):
        return [_public_evidence(item) for item in value]
    return value


def _push(project: Path, head: str, branch: str, remote: str, remote_url: str,
          authorized_workflows: tuple[str, ...], *, source_project: Path | None = None) -> dict[str, Any]:
    """Verify and fast-forward the remote branch to ``head``; never force."""
    from cli.lib.publication_effects import delivery_workflow_authority

    from ..services.git.outgoing import (
        OutgoingAdmissionUnavailable,
        OutgoingVerificationError,
        PushUpdate,
        verify_outgoing,
    )

    def network(*arguments: str) -> subprocess.CompletedProcess[str]:
        response = _git(project, *arguments)
        # A refused push exits 1: porcelain lists the remote's per-ref
        # rejection, or a pre-push hook refused it before any ref was sent.
        # Transport failures exit 128 (or the watchdog's code) and prove no
        # project defect.
        if response.returncode and not (arguments[0] == "push" and response.returncode == 1):
            raise _TransportUnavailable
        return response

    destination = f"refs/heads/{branch}"
    transport = remote_url if source_project is not None else remote
    rows = network("ls-remote", "--refs", transport, destination).stdout.splitlines()
    if len(rows) > 1:
        raise _InspectionFailed
    fields = rows[0].split() if rows else []
    if rows and (len(fields) != 2 or not _OID.fullmatch(fields[0]) or len(fields[0]) != len(head) or fields[1] != destination):
        raise _InspectionFailed
    old = fields[0] if fields else None
    if old and _git(project, "cat-file", "-e", f"{old}^{{commit}}").returncode:
        network("fetch", "--no-tags", "--recurse-submodules=no", transport, destination)
    if old == head or (old and _git(project, "merge-base", "--is-ancestor", head, old).returncode == 0):
        return {"status": "SUCCESS", "reason": "already_on_remote", "pushed": False, "sha": head,
                "publication_complete": True, "security": {"state": "not_run", "sha": head},
                "delivery": {"uploaded_source": head}}
    if old and _git(project, "merge-base", "--is-ancestor", old, head).returncode != 0:
        # Remote work this checkout lacks needs a person; never publish around it.
        return {"status": "BLOCKED", "reason": "remote_base_diverged", "pushed": False, "sha": head,
                "publication_complete": False, "security": {"state": "not_run", "sha": head}}
    try:
        verified = verify_outgoing(project, remote_url, [PushUpdate(destination, head, destination, old or "0" * len(head))],
                                   published_bases=(old,) if old else ())
    except OutgoingAdmissionUnavailable as exc:
        raise _AdmissionUnavailable from exc
    except OutgoingVerificationError as exc:
        raise _OutgoingFailed from exc
    security = {"state": "success", "sha": head, "commits_scanned": verified.commits_scanned,
                "refs_checked": verified.refs_checked, "scope": "outgoing_history", "base_sha": old,
                "destination_ref": destination}
    try:
        authority = delivery_workflow_authority(project, head, old, branch, None, git=_git,
                                                authorized=authorized_workflows)
    except ValueError:
        return {"status": "PENDING", "reason": "workflow_effects_unknown", "pushed": False, "sha": head,
                "publication_complete": False, "security": security}
    if authority["unauthorized_workflows"]:
        return {"status": "PENDING", "reason": "workflow_effects_authorization_required", "pushed": False,
                "sha": head, "publication_complete": False, "security": security, "workflow_authority": authority,
                "unauthorized_workflows": authority["unauthorized_workflows"],
                "action": "Authorize the listed workflow effects explicitly for this source before publication"}
    if source_project is not None:
        from .publication_agent import source_job

        hook = source_job(source_project, "hook", remote=remote, remote_url=remote_url,
                          head=head, destination=destination, old=old or "0" * len(head))
        if hook != {"returncode": 0}:
            return {"status": "BLOCKED", "reason": "pre_push_hook_rejected", "pushed": False,
                    "sha": head, "publication_complete": False, "security": security,
                    "workflow_authority": authority}
    pushed = network("push", "--porcelain", "--no-follow-tags", "--recurse-submodules=no", transport, f"{head}:{destination}")
    if pushed.returncode:
        rejected = any(line.startswith("!\t") and len(line.split("\t")) == 3 for line in pushed.stdout.splitlines())
        return {"status": "BLOCKED", "reason": "remote_push_rejected" if rejected else "pre_push_hook_rejected",
                "pushed": False, "sha": head, "publication_complete": False, "security": security,
                "workflow_authority": authority}
    return {"status": "SUCCESS", "reason": "source_published", "pushed": True, "sha": head,
            "publication_complete": True, "security": security, "workflow_authority": authority,
            "delivery": {"uploaded_source": head}}


def publish_source(source: dict[str, Any], source_commit: str, *,
                   authorized_workflows: tuple[str, ...] = ()) -> dict[str, Any]:
    """Publish one exact committed source of a registered project.

    The owning CLI/API authorizes the call; route, acceptance (public
    repositories), outgoing and workflow-effects checks still apply.
    """
    result: dict[str, Any] = {
        "source_id": source.get("id"), "status": "skipped", "attempted": False,
        "publication_complete": False, "observed_at": datetime.now(UTC).isoformat(),
        "source_status": "unknown", "remote_status": "unobserved", "security": {"state": "not_run"},
        "requested_source_commit": None, "captured_source_commit": None,
    }

    def outcome(status: str, reason: str) -> dict[str, Any]:
        return {**result, "status": status, "reason": reason, "observed_at": datetime.now(UTC).isoformat()}

    if not isinstance(source_commit, str) or not _OID.fullmatch(source_commit):
        return outcome("failed", "invalid_manual_source")
    result["requested_source_commit"] = source_commit
    if source.get("source_type") != "project":
        return outcome("skipped", "non_project_source")
    if not source.get("id") or not source.get("path"):
        return outcome("skipped", "unregistered_source")
    if source.get("enabled") is not True:
        return outcome("skipped", "disabled_source")
    resources = ExitStack()
    try:
        project = Path(source["path"]).expanduser().resolve(strict=True)
        if not project.is_dir():
            return outcome("skipped", "not_project_directory")
        top = _git(project, "rev-parse", "--show-toplevel")
        if top.returncode != 0:
            return outcome("skipped", "not_git_repository")
        if Path(top.stdout.strip()).resolve() != project:
            return outcome("skipped", "repository_root_mismatch")
        # The selected source is independent of the mutable branch or HEAD.
        branches = [name for name in ("main", "master") if _git(project, "show-ref", "--verify", "--quiet", f"refs/heads/{name}").returncode == 0]
        if len(branches) != 1:
            return outcome("pending", "manual_default_branch_required")
        branch = branches[0]
        head_result = _git(project, "rev-parse", "--verify", f"{source_commit}^{{commit}}")
        if head_result.returncode != 0 or head_result.stdout.strip() != source_commit:
            return outcome("failed", "manual_source_unavailable")
        head = source_commit
        result.update(head=head, branch=branch, source_status="captured", vcs="git", captured_source_commit=head,
                      source_tree=_value(project, "rev-parse", f"{head}^{{tree}}"))
        route = _value(project, "for-each-ref", "--format=%(upstream)%00%(upstream:remotename)%00%(upstream:remoteref)", f"refs/heads/{branch}").split("\0")
        if len(route) != 3 or not all(route):
            return outcome("skipped", "no_existing_upstream")
        tracking_ref, remote, upstream_ref = route
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", remote) or upstream_ref != f"refs/heads/{branch}" or tracking_ref != f"refs/remotes/{remote}/{branch}":
            return outcome("skipped", "incorrect_upstream_route")
        if (_value(project, "config", "--get-all", f"branch.{branch}.remote").splitlines() != [remote] or _value(project, "config", "--get-all", f"branch.{branch}.merge").splitlines() != [upstream_ref]):
            return outcome("skipped", "ambiguous_upstream_route")
        fetch_urls = _value(project, "remote", "get-url", "--all", remote).splitlines()
        push_urls = _value(project, "remote", "get-url", "--push", "--all", remote).splitlines()
        if len(fetch_urls) != 1 or len(push_urls) != 1:
            return outcome("skipped", "ambiguous_remote_route")
        identity = network_repository_identity(fetch_urls[0])
        if identity is None or network_repository_identity(push_urls[0]) != identity:
            return outcome("skipped", "unsafe_remote_route")
        result["repository"] = list(identity)
        mirror = _git(project, "config", "--bool", "--get", f"remote.{remote}.mirror")
        if mirror.returncode not in {0, 1}:
            return outcome("skipped", "uncertain_mirror_configuration")
        if mirror.returncode == 0 and mirror.stdout.strip() == "true":
            return outcome("skipped", "mirror_remote")
        result.update(remote=remote, upstream_ref=upstream_ref)
        publication_project = project
        independent = _requires_independent_repository(project)
        if independent:
            from .publication_agent import independent_repository

            publication_project = resources.enter_context(independent_repository(project, head))
        try:
            repository = remote_repository(publication_project, identity)
        except Exception as exc:
            from cli.lib.github_publish import GitHubError

            if not isinstance(exc, GitHubError):
                raise
            result["remote_status"] = "unknown"
            return outcome("pending" if exc.unavailable else "failed", exc.reason)
        if repository is not None:
            if repository.get("archived") is True:
                return outcome("skipped", "remote_repository_archived")
            if repository.get("default_branch") not in {None, branch}:
                return outcome("skipped", "remote_default_branch_mismatch")
        public = is_public(repository)
        result["visibility"] = "public" if public else "private"
        result["acceptance"] = _acceptance_for_head(project, head)
        if result["acceptance"].get("state") != "reused":
            if public:
                result["source_status"] = "acceptance_required"
                result["action"] = "Public repositories publish only accepted commits: run st check --acceptance for this commit"
                return outcome("pending", "source_acceptance_required")
            result["acceptance"] = {"state": "not_required", "reason": "private_repository", "source_commit": head}
        result["source_status"] = "accepted" if result["acceptance"]["state"] == "reused" else "committed"
        result["attempted"] = True
        if independent:
            delivered = _push(publication_project, head, branch, remote, push_urls[0], authorized_workflows,
                              source_project=project)
            if delivered["publication_complete"]:
                from .publication_agent import source_job

                source_job(project, "update_tracking", head=head, tracking_ref=tracking_ref)
        else:
            delivered = _push(project, head, branch, remote, push_urls[0], authorized_workflows)
        result.update(delivered)
        result["remote_status"] = ("uploaded" if delivered["publication_complete"] else
                                   "pending" if delivered["status"] == "PENDING" else "blocked")
        status = ("published" if delivered["publication_complete"] else
                  "pending" if delivered["status"] == "PENDING" else "failed")
        return outcome(status, delivered["reason"])
    except _AdmissionUnavailable:
        result["security"] = {"state": "unavailable", "sha": result.get("head")}
        result["remote_status"] = "unknown"
        result["action"] = "Restore shared heavy-work admission before retrying required outgoing verification"
        return outcome("pending", "heavy_work_admission_unavailable")
    except _OutgoingFailed as exc:
        from ..services.git.outgoing import OutgoingVerificationError

        result["security"] = {"state": "blocked", "sha": result.get("head")}
        if isinstance(exc.__cause__, OutgoingVerificationError):
            # Verifier messages are fixed, already-redacted reasons.
            result["security"]["reason"] = str(exc.__cause__)
        result["action"] = "Inspect st vcs doctor and repair outgoing scanner, policy, history or secret findings before retry"
        return outcome("failed", "outgoing_verification_failed")
    except _TransportUnavailable:
        result["remote_status"] = "unknown"
        return outcome("pending", "remote_transport_unavailable")
    except (ImportError, OSError, ValueError, TypeError, KeyError, RuntimeError, subprocess.SubprocessError):
        return outcome("failed", "publication_inspection_unavailable")
    finally:
        resources.close()

