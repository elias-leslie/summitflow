from __future__ import annotations

import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

import typer

from app.services.task_closeout import completion_evidence
from app.storage.projects import get_project_root_path
from app.tasks.autonomous.exec_modules.diff_gate import DiffGateResult, check_diff_gate
from app.utils.git_base import normalize_base_branch

from .._client_base import APIError
from ..client import STClient
from ..lib.autosnapshot import capture_lifecycle_baseline
from ..lib.checkpoint import get_snapshot_info, remove_snapshot
from ..lib.checkpoint_branches import resolve_task_branch
from ..lib.commit_workflow import CommitError, _normalize_paths, commit_repo
from ..output import output_error, output_success
from .done_git import is_working_tree_clean
from .done_lifecycle import _reconstruct_snapshot_info
from .done_subtask import auto_close_subtasks
from .done_task_residue import finalize_missing_snapshot_residue
from .done_task_scope import closeout_paths
from .done_task_scope import git_dirty_paths as _git_dirty_paths
from .done_task_scope import task_scope_paths as _task_scope_paths
from .done_task_scope import task_with_export_context as _task_with_export_context
from .tasks_progress import sync_completed_subtasks


def _refuse_failed_task(task_id: str, status: object) -> None:
    if status == "failed":
        output_error(f"Task {task_id} is failed; completion was not recorded.\n"
                     f"  Next action: st reopen {task_id}, then st claim {task_id} before completing work.")
        raise typer.Exit(1)


def _done_result(
    task_id: str,
    merged: bool = False,
    snapshot_removed: bool = False,
    base_branch: str = "main",
    project_id: str | None = None,
    published: bool = False,
) -> dict[str, str | bool]:
    return {
        "task_id": task_id,
        "action": "completed",
        "merged": merged,
        "published": published,
        "snapshot_removed": snapshot_removed,
        "base_branch": base_branch,
        "project_id": project_id or "",
    }


def _checkpoint_repo_root(project_id: str | None) -> str | None:
    return get_project_root_path(project_id) if project_id else None


def _task_project_id(task: dict[str, Any]) -> str | None:
    raw = task.get("project_id")
    return str(raw) if isinstance(raw, str) and raw else None


def _task_base_branch(task: dict[str, Any]) -> str:
    raw = task.get("base_branch")
    branch = str(raw) if isinstance(raw, str) and raw else "main"
    return normalize_base_branch(branch, _checkpoint_repo_root(_task_project_id(task)))


def _selected_work_is_clean(repo_root: str, paths: tuple[str, ...]) -> bool:
    if not paths:
        return is_working_tree_clean(repo_root)
    repo = Path(repo_root)
    return not _git_dirty_paths(repo_root, paths=tuple(_normalize_paths(repo, paths)))


def ensure_checkpoint_clean(snapshot_info: dict[str, str | int | None], *, task_id: str | None = None, message: str | None = None, strict: bool = True, paths: tuple[str, ...] = ()) -> None:
    raw_pid = snapshot_info.get("project_id")
    project_id = str(raw_pid) if isinstance(raw_pid, str) and raw_pid else None
    repo_root = _checkpoint_repo_root(project_id)
    if not repo_root or _selected_work_is_clean(repo_root, paths):
        return
    if not strict and task_id and paths:
        _commit_active_task_work(repo_root, task_id, message, **({"paths": paths} if paths else {}))
        if _selected_work_is_clean(repo_root, paths):
            return
    output_error(f"Claimed checkpoint has uncommitted changes.\n  Path: {repo_root}\n  Smart mode could not create a clean checkpoint. Fix the reported closeout blocker, then rerun st done.")
    raise typer.Exit(1)


def _auto_verify_readiness(client: STClient, task_id: str) -> None:
    readiness = client.get_task_completion_readiness(task_id)
    if readiness.get("ready"):
        return
    gates = readiness.get("gates", [])
    gate_details = ", ".join(str(gate.get("gate") or gate.get("code") or "unknown") for gate in gates)
    output_error(f"Task not ready to complete: {gate_details}")
    raise typer.Exit(1)


def _run_smart_prereqs(client: STClient, task_id: str, project_id: str | None, *,
                       owned_claim: dict[str, Any] | None = None) -> None:
    subtasks_resp = client.get_subtasks(task_id)
    sync_analysis = sync_completed_subtasks(client, task_id, subtasks_resp.get("subtasks", []), acknowledge_none=False,
        **({"owned_claim": owned_claim} if owned_claim is not None else {}))
    if sync_analysis.synced:
        output_success(f"Pre-synced subtasks before completion: {', '.join(sync_analysis.synced)}")
    auto_close_subtasks(client, task_id, project_id, **({"owned_claim": owned_claim} if owned_claim is not None else {}))
    _auto_verify_readiness(client, task_id)


def _is_rolling_repair(task: dict[str, Any]) -> bool:
    if "publication-repair" not in (task.get("labels") or []) or not task.get("project_id"):
        return False
    from app.storage.tasks.publication_repair import get_repair_task
    repair = get_repair_task(str(task["project_id"]))
    return bool(repair and repair["id"] == task["id"])


def _task_has_published_commit_event(task_id: str) -> bool:
    import re
    try:
        from app.storage.events import get_events_by_trace
    except Exception:
        return False
    commit_event_re = re.compile(r"\bst commit\b.*\bcommit=[0-9a-f]+\b")
    try:
        events = get_events_by_trace(task_id, limit=50)
    except Exception:
        return False
    return any(message and commit_event_re.search(message) for event in reversed(events) if (message := event.get("message")))


def _commit_active_task_work(repo_root: str, task_id: str, message: str | None, *, paths: tuple[str, ...] = ()) -> None:
    if not paths:
        output_error(f"Task scope is ambiguous. Rerun st done {task_id} --paths <owned-path> (repeat for each task path)")
        raise typer.Exit(1)
    commit_message = (message or f"complete {task_id}").strip()
    try:
        result = commit_repo(Path(repo_root), message=commit_message, task_id=task_id, push=False, paths=paths)
    except CommitError as exc:
        output_error(f"Task closeout blocked: st commit failed: {exc}")
        raise typer.Exit(1) from None
    if result.get("status") == "BLOCKED":
        detail = str(result.get("detail") or result.get("reason") or "quality gates failed")
        output_error(f"Task closeout blocked: {detail}")
        raise typer.Exit(2)
    if result.get("status") == "SUCCESS":
        try:
            from app.storage.events import log_task_event
            detail_parts = [f"commit={result.get('sha') or ''}", f"pushed={str(result.get('pushed', False)).lower()}", f"publication_complete={str(result.get('publication_complete', False)).lower()}"]
            log_task_event(task_id, "st commit " + " ".join(part for part in detail_parts if not part.endswith("=")))
        except Exception:
            pass
    output_success(f"Committed task work before completion: {result.get('sha')}")


def _finish_local_completion(task_id: str, project_id: str | None, *, message: str | None,
                             paths: tuple[str, ...], receipt: dict[str, Any]) -> dict[str, Any]:
    from app.services.task_closeout import request_closeout, resume_closeout

    if not project_id:
        raise ValueError("Local completion requires a registered project")
    claim = getattr(receipt, "completion_claim", {})
    intent = request_closeout(task_id, project_id, source_sha=receipt["source_commit"], message=message, paths=paths,
        expected_worker=claim.get("claimed_by"), expected_claimed_at=claim.get("claimed_at"),
        expected_acceptance=dict(receipt),
        expected_verification={key: (claim.get("verification_result") or {}).get(key) or {}
                               for key in ("acceptance", "deployment", "live_validation")})
    if not intent.get("request_id"):
        return intent
    return resume_closeout(task_id, explicit=True)


def _close_missing_checkpoint_active_task(client: STClient, task_id: str, task: dict[str, Any], project_id: str | None, *, base_branch: str, repo_is_clean: bool, paths: tuple[str, ...] = (), acceptance_receipt: dict[str, Any] | None = None) -> dict[str, Any]:
    receipt = _accept_completed_work_or_exit(task_id, project_id, paths=paths, **({"acceptance_receipt": acceptance_receipt} if acceptance_receipt is not None else {}))
    _run_smart_prereqs(client, task_id, project_id, owned_claim=getattr(receipt, "completion_claim", None))
    return _finish_local_completion(task_id, project_id, message=None, paths=paths, receipt=receipt)


_DOC_OR_CONFIG_SUFFIXES = (".md", ".txt", ".rst", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".json")
_DOC_OR_CONFIG_FILENAMES = {"CHANGELOG", "CHANGES", "NOTICE", "AUTHORS", "LICENSE", "README"}


def _is_doc_or_config_path(path: str) -> bool:
    p = path.strip().lower()
    if not p:
        return False
    if "/docs/" in p or p.startswith("docs/"):
        return True
    if any(p.endswith(suffix) for suffix in _DOC_OR_CONFIG_SUFFIXES):
        return True
    basename = p.rsplit("/", 1)[-1].split(".", 1)[0].upper()
    return basename in _DOC_OR_CONFIG_FILENAMES


def _is_diff_docs_or_config_only(
    repo_root: str,
    head_ref: str,
    base_branch: str,
    *,
    base_commit: str | None = None,
) -> bool:
    """Return True if every changed file in the task work diff is docs/config."""
    try:
        diff_ref = f"{base_commit}..{head_ref}" if base_commit else f"{base_branch}...{head_ref}"
        result = subprocess.run(
            ["git", "-C", repo_root, "diff", "--name-only", diff_ref],
            capture_output=True, text=True, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    if result.returncode != 0:
        return False
    paths = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    return bool(paths) and all(_is_doc_or_config_path(p) for p in paths)


def _initial_checkpoint_tree(repo_root: str, claimed_at: str | None) -> str | None:
    """Recover an empty baseline only from a post-claim initial-commit reflog.

    Legacy checkpoints omitted base_commit for unborn repositories. Missing
    history alone is insufficient: the oldest HEAD reflog must record creation
    after this task was claimed. Direct root amendments may replace that root;
    branch switches, resets and other history changes are not proof of origin.
    """
    if not claimed_at:
        return None
    try:
        claimed = datetime.fromisoformat(claimed_at)
        if claimed.tzinfo is None:
            return None
        def git(*args: str) -> subprocess.CompletedProcess[str]:
            return subprocess.run(["git", *args], cwd=repo_root, capture_output=True, text=True, check=False)
        roots = git("rev-list", "--max-parents=0", "--all")
        history = git("reflog", "show", "--date=unix", "--format=%H%x00%gD%x00%gs", "HEAD")
        if roots.returncode or history.returncode or not history.stdout.strip():
            return None
        entries = [line.split("\0", 2) for line in reversed(history.stdout.strip().splitlines())]
        sha, selector, subject = entries[0]
        timestamp = int(selector.rsplit("@{", 1)[1].removesuffix("}"))
        if not subject.startswith("commit (initial):") or timestamp < int(claimed.timestamp()):
            return None
        # Only an uninterrupted sequence of parentless amendments can replace
        # the initial root. Later ordinary commits retain that root as evidence.
        for amended_sha, _, amended_subject in entries[1:]:
            if not amended_subject.startswith("commit (amend):"):
                break
            parents = git("rev-list", "--parents", "-n", "1", amended_sha)
            if parents.returncode or parents.stdout.split() != [amended_sha]:
                break
            sha = amended_sha
        if roots.stdout.splitlines() != [sha]:
            return None
        tree = subprocess.run(["git", "hash-object", "-w", "-t", "tree", "--stdin"], cwd=repo_root,
                              input="", capture_output=True, text=True, check=False)
        return tree.stdout.strip() if tree.returncode == 0 else None
    except (ValueError, IndexError, OSError, subprocess.SubprocessError):
        return None


def _task_commit_diff_ref(repo_root: str, task_id: str, *, exact_commit: str | None = None,
                          project_id: str | None = None) -> tuple[str, str] | None:
    """Recover a direct-main task diff when a broken checkpoint lacks its base."""
    import re

    from app.storage.events import get_events_by_trace

    try:
        events = get_events_by_trace(task_id, limit=1000)
    except Exception:
        return None
    for event in events:
        if exact_commit is not None and (event.get("trace_id") != task_id or event.get("project_id") != project_id):
            continue
        message = event.get("message") or ""
        commit_pattern = r"[0-9a-f]{40}(?:[0-9a-f]{24})?" if exact_commit is not None else r"[0-9a-f]{7,40}"
        match = re.search(r"\bst commit\b.*\bcommit=(" + commit_pattern + r")\b", message)
        if not match:
            continue
        commit = match.group(1)
        if exact_commit is not None and commit != exact_commit:
            continue
        ancestor = subprocess.run(
            ["git", "merge-base", "--is-ancestor", commit, "HEAD"],
            cwd=repo_root, capture_output=True, check=False,
        )
        if ancestor.returncode != 0:
            continue
        parents = subprocess.run(
            ["git", "rev-list", "--parents", "-n", "1", commit],
            cwd=repo_root, capture_output=True, text=True, check=False,
        )
        parts = parents.stdout.strip().split() if parents.returncode == 0 else []
        if len(parts) >= 2 and parts[0].startswith(commit):
            return parts[0], parts[1]
    return None


def _reclaimed_repair_diff(repo_root: str, task_id: str, project_id: str | None, *,
                           base_commit: str, paths: tuple[str, ...],
                           acceptance_receipt: dict[str, Any]) -> DiffGateResult | None:
    """Recheck the original patch for an exact-source, accepted repair refresh."""
    from cli.lib.acceptance import AcceptanceError, repo_lock
    from cli.lib.acceptance_coordinator import validate_source_receipt
    from cli.lib.commit_workflow import run_git

    if not paths or not project_id:
        return None
    repo = Path(repo_root)
    try:
        with repo_lock(repo, purpose="repair refresh diff validation"):
            if not _selected_work_is_clean(repo_root, paths):
                return None
            validated = validate_source_receipt(repo, acceptance_receipt, sha="HEAD").reference.to_dict()
            if validated["source_commit"] != base_commit:
                return None
            task_diff = _task_commit_diff_ref(repo_root, task_id, exact_commit=base_commit, project_id=project_id)
            if task_diff is None:
                return None
            commit, parent = task_diff
            result = check_diff_gate(repo_root, head_ref=commit, base_tree=parent)
            head = run_git(repo, ["rev-parse", "--verify", "HEAD^{commit}"])
            if head.returncode or head.stdout.strip() != commit or not _selected_work_is_clean(repo_root, paths):
                return None
            return result
    except (AcceptanceError, ValueError, OSError, subprocess.SubprocessError):
        return None


def _run_diff_gate(
    repo_root: str,
    task_id: str,
    project_id: str | None,
    base_branch: str,
    *,
    base_commit: str | None = None,
    claimed_at: str | None = None,
    repair_acceptance_receipt: dict[str, Any] | None = None,
    paths: tuple[str, ...] = (),
) -> None:
    # Emergency escape: ST_DIFF_GATE=off disables the gate entirely.
    if (os.environ.get("ST_DIFF_GATE") or "").strip().lower() == "off":
        return
    head_ref = "HEAD" if base_commit else resolve_task_branch(task_id, project_id=project_id)
    # Auto-route: docs/config-only changes skip the code-quality slice.
    if _is_diff_docs_or_config_only(repo_root, head_ref, base_branch, base_commit=base_commit):
        output_success("Diff gate auto-skipped: changes are docs/config only.")
        return
    initial_tree = _initial_checkpoint_tree(repo_root, claimed_at) if not base_commit else None
    diff_result = (check_diff_gate(repo_root, head_ref="HEAD", base_tree=initial_tree) if initial_tree
                   else check_diff_gate(repo_root, head_ref=head_ref, base_ref=base_commit or base_branch))
    if (not diff_result.passed and not base_commit and not initial_tree
            and diff_result.summary == "Could not determine merge-base — completion blocked"
            and (task_diff := _task_commit_diff_ref(repo_root, task_id))):
        commit, parent = task_diff
        diff_result = check_diff_gate(repo_root, head_ref=commit, base_tree=parent)
    if (not diff_result.passed and diff_result.files_changed == 0 and base_commit
            and repair_acceptance_receipt is not None
            and diff_result.summary == "No files changed vs base branch — task has no code changes"):
        recovered = _reclaimed_repair_diff(repo_root, task_id, project_id, base_commit=base_commit,
                                          paths=paths, acceptance_receipt=repair_acceptance_receipt)
        if recovered is not None:
            diff_result = recovered
    if diff_result.passed:
        return
    output_error(
        f"Diff gate blocked completion: {diff_result.summary}\n"
        f"Resolution: address the gate findings, or set ST_DIFF_GATE=off for an emergency override."
    )
    raise typer.Exit(1)


def _close_task_safely(client: STClient, task_id: str, message: str | None, *,
                       owned_claim: dict[str, Any]) -> dict[str, Any]:
    _auto_verify_readiness(client, task_id)
    from app.storage.events import log_task_event
    from app.storage.tasks import update_task_status

    try:
        completed = update_task_status(task_id, "completed", expected_worker=str(owned_claim["claimed_by"]),
            expected_claimed_at=owned_claim["claimed_at"], expected_project_id=str(owned_claim["project_id"]))
        if completed is None:
            raise ValueError("Task no longer exists")
    except ValueError as exc:
        output_error(f"Failed to close task: {exc}")
        raise typer.Exit(1) from None
    if message:
        log_task_event(task_id, f"Closed: {message}")
    return completed


def _capture_and_remove_snapshot(task_id: str, project_id: str | None) -> None:
    repo_root = _checkpoint_repo_root(project_id)
    lifecycle_snapshot = capture_lifecycle_baseline(project_id=project_id, cwd=repo_root)
    if lifecycle_snapshot:
        output_success(f"Protective snapshot captured before cleanup: {lifecycle_snapshot.id}")
    remove_snapshot(task_id, project_id=project_id)


def _owned_completion_claim(root: Path, task_id: str, project_id: str) -> dict[str, Any]:
    from cli.lib.task_claims import current_worker_id, renew_local_owned_claim

    task = renew_local_owned_claim(root, task_id)
    if (task.get("project_id") != project_id or task.get("status") != "running"
            or task.get("claimed_by") != current_worker_id() or not task.get("claimed_at")):
        raise ValueError("Task claim is not actively owned by this worker; run st claim before completion")
    return task


def _accept_completed_work(task_id: str, project_id: str | None, *, paths: tuple[str, ...] = (), acceptance_receipt: dict[str, Any] | None = None) -> dict[str, Any]:
    from cli.lib.task_completion_adapter import accept_owned_task_work

    root = _checkpoint_repo_root(project_id)
    if not root or not project_id:
        raise ValueError("Local acceptance requires a registered project checkout")
    repo = Path(root)
    return accept_owned_task_work(repo, task_id, project_id,
        claim=_owned_completion_claim(repo, task_id, project_id), paths=paths,
        acceptance_receipt=acceptance_receipt)


def _accept_completed_work_or_exit(task_id: str, project_id: str | None, *, paths: tuple[str, ...] = (), acceptance_receipt: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        if acceptance_receipt is not None:
            return _accept_completed_work(task_id, project_id, paths=paths, acceptance_receipt=acceptance_receipt)
        elif paths:
            return _accept_completed_work(task_id, project_id, paths=paths)
        else:
            return _accept_completed_work(task_id, project_id)
    except Exception as exc:
        output_error(f"Task closeout blocked: local acceptance failed: {exc}\n  Checkpoint preserved; rerun st done {task_id} after resolving this blocker.")
        raise typer.Exit(1) from None


def _record_only_work(task: dict[str, Any], task_id: str, snapshot: dict[str, Any] | None, paths: tuple[str, ...]) -> bool:
    """No declared implementation and no changed checkpoint needs a code diff."""
    context = task.get("context") or {}
    requirements = task.get("completion_requirements") or context.get("completion_requirements") or {}
    if (paths or task.get("commits") or _task_scope_paths(task)
            or requirements.get("acceptance") or requirements.get("acceptance_stages")
            or requirements.get("deployment") or requirements.get("live_checks")):
        return False
    root = _checkpoint_repo_root(_task_project_id(task) or str((snapshot or {}).get("project_id") or "") or None)
    if not root:
        return True
    if not is_working_tree_clean(root):
        return context.get("work_kind") in {"admin", "read_only", "research"} or requirements.get("acceptance") is False
    if snapshot and snapshot.get("base_commit"):
        result = subprocess.run(["git", "-C", root, "rev-parse", "HEAD"], capture_output=True, text=True, check=False)
        return result.returncode == 0 and result.stdout.strip() == snapshot["base_commit"]
    return not _task_has_published_commit_event(task_id)


def complete_task(client: STClient, task_id: str, message: str | None = None, strict: bool = False, admin: bool = False, skip_diff_gate: bool = False, *, paths: tuple[str, ...] = (), acceptance_receipt: dict[str, Any] | None = None) -> dict[str, str | bool]:
    """Complete a task with local acceptance and checkpoint cleanup.

    Smart mode (default): checkpoints, accepts locally, closes, and cleans up.
    Strict mode: fails if gates not pre-passed or main dirty.
    """
    from app.services.task_closeout import get_closeout, resume_closeout
    intent = get_closeout(task_id)
    if intent and intent.get("kind") == "local_closeout.v1" and intent.get("state") in {"pending", "blocked"}:
        return resume_closeout(task_id, explicit=True)
    snapshot_info = get_snapshot_info(task_id)
    task = client.get_task(task_id)
    _refuse_failed_task(task_id, task.get("status"))
    task = _task_with_export_context(client, task_id, task)
    if task.get("status") == "completed" and not snapshot_info:
        return {**_done_result(task_id, snapshot_removed=True, project_id=_task_project_id(task)),
                **completion_evidence((task.get("verification_result") or {}).get("acceptance") or {}, retained=True)}
    record_only = acceptance_receipt is None and _record_only_work(task, task_id, snapshot_info, paths)
    if admin and not record_only:
        output_error("Record-only completion cannot close declared implementation work. Use st done without --record-only to validate its owned source and acceptance.")
        raise typer.Exit(2)
    if record_only:
        project_id = _task_project_id(task)
        if task.get("status") == "completed" and snapshot_info:
            return _complete_admin(client, task_id, snapshot_info, message, completed_task=task)
        root = _checkpoint_repo_root(project_id)
        try:
            if not root or not project_id:
                raise ValueError("Record-only completion requires a registered local project and owned task claim")
            if snapshot_info and snapshot_info.get("project_id") != project_id:
                raise ValueError("Checkpoint project differs from task ownership; checkpoint preserved")
            claim = _owned_completion_claim(Path(root), task_id, project_id)
        except (ValueError, RuntimeError) as exc:
            output_error(f"Record-only completion blocked: {exc}")
            raise typer.Exit(1) from None
        _run_smart_prereqs(client, task_id, project_id, owned_claim=claim)
        if snapshot_info:
            return _complete_admin(client, task_id, snapshot_info, message, owned_claim=claim)
        _close_task_safely(client, task_id, message, owned_claim=claim)
        return {**_done_result(task_id, project_id=project_id), **completion_evidence({}, record_only=True)}
    if snapshot_info:
        return _complete_with_snapshot(client, task_id, snapshot_info, message=message, strict=strict, skip_diff_gate=skip_diff_gate, paths=paths, acceptance_receipt=acceptance_receipt)
    snapshot_info = _reconstruct_snapshot_info(client, task_id)
    if snapshot_info:
        return _complete_with_snapshot(client, task_id, snapshot_info, message=message, strict=strict, skip_diff_gate=skip_diff_gate, paths=paths, acceptance_receipt=acceptance_receipt)
    return _complete_without_snapshot(client, task_id, message=message, strict=strict, skip_diff_gate=skip_diff_gate, paths=paths, acceptance_receipt=acceptance_receipt)


def _complete_without_snapshot(client: STClient, task_id: str, *, message: str | None, strict: bool, skip_diff_gate: bool, paths: tuple[str, ...] = (), acceptance_receipt: dict[str, Any] | None = None) -> dict[str, str | bool]:
    task: dict[str, Any] | None = None
    try:
        task = client.get_task(task_id)
    except APIError:
        task = None
    if task is not None:
        root = _checkpoint_repo_root(_task_project_id(task))
        if root and task.get("status") in {"running", "pending"}:
            try:
                paths = closeout_paths(root, task_id, _task_with_export_context(client, task_id, task), project_id=_task_project_id(task), paths=paths)
            except ValueError as exc:
                output_error(str(exc))
                raise typer.Exit(1) from None
        recovered = finalize_missing_snapshot_residue(
            client, task_id, task, message=message, strict=strict, skip_diff_gate=skip_diff_gate,
            deps={
                "checkpoint_repo_root": _checkpoint_repo_root,
                "close_missing_checkpoint_active_task": lambda *args, **kwargs: _close_missing_checkpoint_active_task(*args, **kwargs, **({"paths": paths} if paths else {}), **({"acceptance_receipt": acceptance_receipt} if acceptance_receipt is not None else {})),
                "commit_active_task_work": lambda *args: _commit_active_task_work(*args, **({"paths": paths} if paths else {})),
                "dirty_paths_in_task_scope": lambda repo_root, t: [
                    path for path in _git_dirty_paths(repo_root)
                    if path in (scope := _task_scope_paths(t)) or any(path.startswith(f"{prefix.rstrip('/')}/") for prefix in scope)
                ],
                "done_result": _done_result,
                "is_working_tree_clean": lambda repo_root: _selected_work_is_clean(repo_root, paths),
                "output_error": output_error,
                "output_success": output_success,
                "run_diff_gate": _run_diff_gate,
                "task_base_branch": _task_base_branch,
                "task_has_published_commit_event": _task_has_published_commit_event,
                "task_project_id": _task_project_id,
                "task_with_export_context": _task_with_export_context,
            },
        )
        if recovered is not None:
            return recovered
    output_error(f"No checkpoint found for {task_id}. Was it claimed?")
    raise typer.Exit(1)


def _complete_admin(client: STClient, task_id: str, snapshot_info: dict[str, str | int | None], message: str | None, *,
                    owned_claim: dict[str, Any] | None = None,
                    completed_task: dict[str, Any] | None = None) -> dict[str, str | bool]:
    from app.storage.tasks.closeout import cleanup_completed_checkpoint

    pid = snapshot_info.get("project_id")
    project_id = str(pid) if isinstance(pid, str) and pid else None
    if not project_id or (completed_task or owned_claim or {}).get("project_id") != project_id:
        output_error("Checkpoint project differs from task ownership; checkpoint preserved")
        raise typer.Exit(1)
    already_completed = completed_task is not None
    if completed_task is None:
        if owned_claim is None:
            raise ValueError("Record-only completion requires its exact active claim")
        completed_task = _close_task_safely(client, task_id, message, owned_claim=owned_claim)
    acceptance = (completed_task.get("verification_result") or {}).get("acceptance") or {}
    if not cleanup_completed_checkpoint(task_id, project_id, expected_acceptance=acceptance,
            cleanup=lambda: _capture_and_remove_snapshot(task_id, project_id), require_acceptance=False):
        output_error("Completed task changed before metadata cleanup; checkpoint preserved")
        raise typer.Exit(1)
    return {**_done_result(task_id, snapshot_removed=True, base_branch=str(snapshot_info.get("base_branch", "main")), project_id=project_id),
            **completion_evidence(acceptance, retained=already_completed, record_only=not already_completed)}


def _complete_with_snapshot(client: STClient, task_id: str, snapshot_info: dict[str, str | int | None], *, message: str | None, strict: bool, skip_diff_gate: bool, paths: tuple[str, ...] = (), acceptance_receipt: dict[str, Any] | None = None) -> dict[str, str | bool]:
    try:
        task = client.get_task(task_id)
        already_completed = task.get("status") == "completed"
        if task.get("project_id") and task["project_id"] != snapshot_info.get("project_id"):
            output_error("Checkpoint project differs from task ownership; checkpoint preserved")
            raise typer.Exit(1)
        is_repair = _is_rolling_repair(task)
    except APIError as exc:
        output_error(
            f"Task closeout blocked: current task status is unavailable: {exc.detail}\n"
            f"  Checkpoint preserved; rerun `st done {task_id}` when the API is healthy."
        )
        raise typer.Exit(1) from None
    if not already_completed:
        scoped_task = _task_with_export_context(client, task_id, task)
        root = _checkpoint_repo_root(str(snapshot_info.get("project_id") or "") or None)
        if root:
            try:
                paths = closeout_paths(root, task_id, scoped_task, project_id=str(snapshot_info.get("project_id") or "") or None, paths=paths)
            except ValueError as exc:
                output_error(str(exc))
                raise typer.Exit(1) from None
        ensure_checkpoint_clean(
            snapshot_info,
            task_id=task_id,
            message=message,
            strict=strict or already_completed,
            **({"paths": paths} if paths else {}),
        )
    pid = snapshot_info.get("project_id")
    project_id = str(pid) if isinstance(pid, str) and pid else None
    repo_root = _checkpoint_repo_root(project_id)
    base_branch = normalize_base_branch(str(snapshot_info.get("base_branch", "main")), repo_root)
    snapshot_info["base_branch"] = base_branch
    try:
        base_commit = str(snapshot_info.get("base_commit") or "") or None
        repair_options: dict[str, Any] = {}
        if is_repair and project_id == task.get("project_id") and paths and acceptance_receipt is not None:
            repair_options = {"repair_acceptance_receipt": acceptance_receipt, "paths": paths}
        if not already_completed and repo_root and not skip_diff_gate:
            _run_diff_gate(repo_root, task_id, project_id, base_branch, base_commit=base_commit,
                           claimed_at=str(snapshot_info.get("created_at") or "") or None,
                           **repair_options)
        if not already_completed:
            receipt = _accept_completed_work_or_exit(task_id, project_id, paths=paths, **({"acceptance_receipt": acceptance_receipt} if acceptance_receipt is not None else {}))
            if strict:
                _auto_verify_readiness(client, task_id)
            else:
                _run_smart_prereqs(client, task_id, project_id, owned_claim=getattr(receipt, "completion_claim", None))
        if not already_completed:
            return _finish_local_completion(task_id, project_id, message=message, paths=paths, receipt=receipt)
        acceptance = (task.get("verification_result") or {}).get("acceptance") or {}
        if acceptance.get("state") != "success":
            raise ValueError("Completed implementation has no retained local acceptance; checkpoint preserved")
        from app.storage.tasks.closeout import cleanup_completed_checkpoint
        if not project_id or not cleanup_completed_checkpoint(task_id, project_id,
                expected_acceptance=acceptance,
                cleanup=lambda: _capture_and_remove_snapshot(task_id, project_id)):
            raise ValueError("Completed task changed before metadata cleanup; checkpoint preserved")
        return {**_done_result(task_id, snapshot_removed=True, base_branch=base_branch, project_id=project_id),
                **completion_evidence(acceptance, retained=True)}
    except SystemExit as exc:
        raise typer.Exit(exc.code if isinstance(exc.code, int) else 1) from None
