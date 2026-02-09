"""Subtask execution with self-healing retry loop."""

from __future__ import annotations

import time
import traceback
import uuid
from typing import Any

from ....constants import (
    CONTEXT_FRESHNESS_THRESHOLD,
    SELF_HEAL_MAX_ATTEMPTS,
    SUPERVISOR_GUIDED_MAX_ATTEMPTS,
)
from ....core.debug import debug, debug_error, debug_section, debug_success
from ....logging_config import get_logger
from ....services.agent_hub_client import get_sync_client
from ....storage.steps import get_steps_for_subtask
from ....storage.subtasks import update_subtask_passes
from ..escalation import get_supervisor_guidance_sync
from .agent_routing import (
    EXTENSION_ATTEMPTS,
    detect_progress,
    get_agent_for_task,
    request_extension,
)
from .events import emit_error, emit_log, emit_progress, emit_progress_log
from .git_ops import auto_commit, has_uncommitted_changes
from .prompts import build_fix_prompt, build_subtask_prompt
from .session import extract_handoff_summary
from .steps import (
    auto_defect_step,
    compute_issue_id,
    is_infrastructure_failure,
    verify_steps_with_smoke_tests,
)
from .worktree import check_worktree_health, get_project_path

logger = get_logger(__name__)

AUTOCODE_ROLES = ["system", "autocode"]
MAX_ITERATIONS = 50


def execute_subtask(
    task_id: str,
    subtask: dict[str, Any],
    project_id: str,
    issue_counts: dict[str, int],
    task_type: str | None = None,
    agent_override: str | None = None,
) -> dict[str, Any]:
    """Execute a single subtask with fresh context and self-healing retry loop."""
    start_time = time.time()
    subtask_id = subtask.get("id", "")
    subtask_short_id = subtask.get("subtask_id", "")
    subtask_desc = subtask.get("description", "")[:60]

    debug_section(f"Subtask {subtask_short_id}", task_id=task_id, project_id=project_id)
    debug(
        "Starting subtask execution",
        task_id=task_id,
        project_id=project_id,
        subtask_id=subtask_short_id,
        description=subtask_desc,
    )
    logger.info("Executing subtask", task_id=task_id, subtask_id=subtask_short_id)
    emit_log(
        task_id,
        "info",
        f"Starting subtask {subtask_short_id}: {subtask_desc}",
        project_id=project_id,
    )
    emit_progress(
        task_id, subtask_id=subtask_short_id, status="in_progress", project_id=project_id
    )

    all_passed = False
    step_results: list[dict[str, Any]] = []

    try:
        # Use task worktree if available for isolated execution
        project_path = get_project_path(project_id, task_id)

        if not check_worktree_health(project_path, task_id, project_id):
            return {
                "subtask_id": subtask_short_id,
                "status": "failed",
                "reason": "worktree_invalid",
            }

        prompt = build_subtask_prompt(task_id, subtask, project_id, project_path)

        # Resolve which agent to use: override > task_type mapping > default
        agent_slug = agent_override or get_agent_for_task(task_type)

        logger.info(
            "Executing in project",
            subtask_id=subtask_short_id,
            project_path=project_path,
            prompt_length=len(prompt),
            agent_slug=agent_slug,
        )
        client = get_sync_client()
        emit_log(
            task_id,
            "info",
            f"Calling agent ({agent_slug}) for subtask {subtask_short_id}...",
            source="orchestrator",
            project_id=project_id,
        )

        # Pre-create session ID so events are queryable during execution
        from ....storage.tasks.core import add_agent_hub_session

        agent_session_id = str(uuid.uuid4())
        add_agent_hub_session(task_id, agent_session_id)

        logger.info(
            "Calling Agent Hub complete (agentic mode)",
            agent_slug=agent_slug,
            max_turns=50,
            session_id=agent_session_id,
        )
        emit_log(
            task_id,
            "info",
            f"Agent session started: {agent_session_id}",
            source="orchestrator",
            project_id=project_id,
        )
        response = client.complete(
            messages=[{"role": "user", "content": prompt}],
            agent_slug=agent_slug,
            working_dir=project_path,
            max_turns=50,
            execute_tools=True,
            project_id=project_id,
            use_memory=True,
            trace_id=task_id,
            include_roles=AUTOCODE_ROLES,
            session_id=agent_session_id,
        )
        # Update session ID if Agent Hub returned a different one
        if response.session_id and response.session_id != agent_session_id:
            add_agent_hub_session(task_id, response.session_id)
            agent_session_id = response.session_id

        # Surface progress_log to execution timeline
        if response.progress_log:
            emit_progress_log(
                task_id, subtask_short_id, response.progress_log, project_id=project_id
            )
        else:
            # Fallback for agents that don't support incremental progress
            response_preview = response.content[:300] if response.content else "(no response)"
            emit_log(
                task_id,
                "info",
                f"Agent completed subtask {subtask_short_id}",
                source="agent",
                project_id=project_id,
            )
            emit_log(
                task_id,
                "debug",
                f"Agent response: {response_preview}",
                source="agent",
                project_id=project_id,
                visibility="internal",
            )

        # Log context window usage after initial execution
        ctx = response.context_usage
        if ctx:
            level = "warn" if ctx.percent_used >= CONTEXT_FRESHNESS_THRESHOLD else "info"
            emit_log(
                task_id,
                level,
                f"Context usage after initial execution: {ctx.percent_used:.0f}% "
                f"({ctx.used_tokens}/{ctx.limit_tokens} tokens)",
                source="orchestrator",
                project_id=project_id,
            )

        # Log memory citations used
        if response.cited_uuids:
            citations_str = ", ".join(response.cited_uuids[:5])
            if len(response.cited_uuids) > 5:
                citations_str += f" (+{len(response.cited_uuids) - 5} more)"
            emit_log(
                task_id,
                "info",
                f"Memory cited: {citations_str}",
                source="memory",
                project_id=project_id,
            )

        # Log citations from Agent Hub response for ACE-aligned feedback
        # Must acknowledge citations (or lack thereof) before subtask can pass
        if response.cited_uuids:
            from ....storage.subtasks import log_citations

            log_citations(task_id, subtask_short_id, response.cited_uuids, client=client)
        else:
            # No citations used - acknowledge this for the citation gate
            from ....storage.subtasks import acknowledge_no_citations

            acknowledge_no_citations(task_id, subtask_short_id)

        # ================================================================
        # Self-Healing Retry Loop
        # ================================================================
        steps = subtask.get("steps_from_table", [])
        if not steps:
            emit_log(
                task_id,
                "error",
                f"Subtask {subtask_short_id} has 0 steps — cannot verify",
                source="orchestrator",
                project_id=project_id,
            )
            return {
                "subtask_id": subtask_short_id,
                "status": "failed",
                "passed": False,
                "reason": "zero_steps",
                "step_results": [],
            }

        supervisor_guidance_text: str | None = None
        self_fix_attempts = 0
        supervisor_guided_attempts = 0
        total_max_attempts = SELF_HEAL_MAX_ATTEMPTS + SUPERVISOR_GUIDED_MAX_ATTEMPTS
        extensions_granted = 0

        heal_attempt = 0
        while heal_attempt <= total_max_attempts:
            if heal_attempt > 0:
                steps = get_steps_for_subtask(subtask_id)

            if not check_worktree_health(project_path, task_id, project_id):
                step_results = [{
                    "step_number": 0,
                    "passed": False,
                    "output": "Worktree destroyed during execution",
                    "reason": "worktree_destroyed",
                    "returncode": -1,
                }]
                all_passed = False
                break

            all_passed, step_results = verify_steps_with_smoke_tests(
                task_id, subtask_id, steps, project_path, project_id
            )

            # Success - break out of retry loop
            if all_passed:
                break

            # Exhausted all retry attempts — check for extension
            if heal_attempt >= total_max_attempts:
                progress = detect_progress(
                    subtask_id, steps, step_results, project_path,
                )
                if not progress:
                    break
                approved, ext_guidance = request_extension(
                    task_id, subtask_short_id, step_results, progress,
                    project_id=project_id,
                    prior_extensions=extensions_granted,
                )
                if not approved:
                    break
                extensions_granted += 1
                total_max_attempts += EXTENSION_ATTEMPTS
                if ext_guidance:
                    supervisor_guidance_text = ext_guidance
                emit_log(
                    task_id,
                    "info",
                    f"Supervisor granted extension #{extensions_granted} "
                    f"({EXTENSION_ATTEMPTS} more attempts)",
                    source="supervisor",
                    project_id=project_id,
                )

            failed_steps = [r for r in step_results if not r["passed"]]
            failed_count = len(failed_steps)

            # Auto-defect infrastructure failures before retry
            infra_failures = [
                f for f in failed_steps
                if is_infrastructure_failure(
                    f.get("output", ""), f.get("reason", ""), f.get("returncode", 1)
                )
            ]
            if infra_failures:
                for f in infra_failures:
                    auto_defect_step(
                        subtask_id, f["step_number"], f.get("output", ""),
                        task_id, project_id,
                    )
                failed_steps = [f for f in failed_steps if f not in infra_failures]
                failed_count = len(failed_steps)
                if not failed_steps:
                    steps = get_steps_for_subtask(subtask_id)
                    heal_attempt += 1
                    continue

            # Determine which phase we're in
            if self_fix_attempts < SELF_HEAL_MAX_ATTEMPTS:
                # Phase 1: Self-fix attempts
                self_fix_attempts += 1
                emit_log(
                    task_id,
                    "warn",
                    f"Verification failed ({failed_count} steps). "
                    f"Self-heal attempt {self_fix_attempts}/{SELF_HEAL_MAX_ATTEMPTS}",
                    source="orchestrator",
                    project_id=project_id,
                )

                fix_prompt = build_fix_prompt(
                    subtask, failed_steps, response.content, supervisor_guidance=None
                )
            else:
                # Phase 2: Supervisor-guided attempts
                if supervisor_guided_attempts == 0:
                    # First supervisor attempt - get guidance
                    emit_log(
                        task_id,
                        "warn",
                        "Self-fix exhausted. Requesting supervisor guidance...",
                        source="orchestrator",
                        project_id=project_id,
                    )

                    # Get supervisor guidance synchronously
                    error_desc = "; ".join(
                        f"Step {f.get('step_number')}: {f.get('reason', 'failed')}"
                        for f in failed_steps
                    )
                    supervisor_guidance_text = get_supervisor_guidance_sync(
                        task_id, subtask_short_id, error_desc, failed_steps,
                        project_id=project_id,
                    )

                    if supervisor_guidance_text:
                        emit_log(
                            task_id,
                            "info",
                            f"Supervisor guidance received ({len(supervisor_guidance_text)} chars)",
                            source="supervisor",
                            project_id=project_id,
                        )
                    else:
                        emit_log(
                            task_id,
                            "warn",
                            "Supervisor guidance unavailable, continuing without",
                            source="orchestrator",
                            project_id=project_id,
                        )

                supervisor_guided_attempts += 1
                emit_log(
                    task_id,
                    "warn",
                    f"Verification failed ({failed_count} steps). "
                    f"Supervisor-guided attempt {supervisor_guided_attempts}/{SUPERVISOR_GUIDED_MAX_ATTEMPTS}",
                    source="orchestrator",
                    project_id=project_id,
                )

                fix_prompt = build_fix_prompt(
                    subtask, failed_steps, response.content, supervisor_guidance_text
                )

            # Call agent with fix prompt, continuing existing session for context
            continuation = agent_session_id is not None
            if not continuation:
                agent_session_id = str(uuid.uuid4())
                from ....storage.tasks.core import add_agent_hub_session

                add_agent_hub_session(task_id, agent_session_id)

            emit_log(
                task_id,
                "info",
                f"Calling agent for fix attempt ({'continuing session' if continuation else 'new session'} {agent_session_id})...",
                source="orchestrator",
                project_id=project_id,
            )

            try:
                fix_kwargs: dict[str, Any] = {
                    "messages": [{"role": "user", "content": fix_prompt}],
                    "agent_slug": agent_slug,
                    "working_dir": project_path,
                    "max_turns": 25,
                    "execute_tools": True,
                    "project_id": project_id,
                    "use_memory": True,
                    "trace_id": task_id,
                    "include_roles": AUTOCODE_ROLES,
                    "session_id": agent_session_id,
                }

                response = client.complete(**fix_kwargs)
                # Update session ID if Agent Hub returned a different one
                if response.session_id and response.session_id != agent_session_id:
                    from ....storage.tasks.core import add_agent_hub_session

                    add_agent_hub_session(task_id, response.session_id)
                agent_session_id = response.session_id or agent_session_id

                # Surface progress_log to execution timeline
                if response.progress_log:
                    emit_progress_log(
                        task_id, subtask_short_id, response.progress_log, project_id=project_id
                    )

                emit_log(
                    task_id,
                    "info",
                    "Agent fix attempt completed",
                    source="agent",
                    project_id=project_id,
                )

                # Check context window usage - start fresh session if approaching limit
                ctx = response.context_usage
                if ctx and ctx.percent_used >= CONTEXT_FRESHNESS_THRESHOLD:
                    emit_log(
                        task_id,
                        "warn",
                        f"Context window at {ctx.percent_used:.0f}% "
                        f"({ctx.used_tokens}/{ctx.limit_tokens} tokens). "
                        "Starting fresh session for next attempt.",
                        source="orchestrator",
                        project_id=project_id,
                    )
                    agent_session_id = str(uuid.uuid4())
                    from ....storage.tasks.core import add_agent_hub_session

                    add_agent_hub_session(task_id, agent_session_id)
                elif ctx:
                    emit_log(
                        task_id,
                        "debug",
                        f"Context usage: {ctx.percent_used:.0f}% "
                        f"({ctx.used_tokens}/{ctx.limit_tokens} tokens)",
                        source="orchestrator",
                        project_id=project_id,
                        visibility="internal",
                    )

                # Auto-commit fix attempt
                if has_uncommitted_changes(project_path):
                    phase = "self-fix" if self_fix_attempts <= SELF_HEAL_MAX_ATTEMPTS else "guided"
                    attempt_num = (
                        self_fix_attempts if phase == "self-fix" else supervisor_guided_attempts
                    )
                    commit_msg = f"[{phase}] {subtask_short_id} attempt {attempt_num}"
                    auto_commit(project_path, commit_msg)

            except Exception as fix_error:
                logger.warning(
                    "Fix attempt failed",
                    subtask_id=subtask_short_id,
                    attempt=heal_attempt + 1,
                    error=str(fix_error),
                )
                emit_log(
                    task_id,
                    "error",
                    f"Fix attempt error: {str(fix_error)[:100]}",
                    source="orchestrator",
                    project_id=project_id,
                )
                # Continue to next attempt or exit loop

            heal_attempt += 1

        # ================================================================
        # End of Self-Healing Loop - Process Final Result
        # ================================================================

        duration = time.time() - start_time
        duration_str = f"{duration:.1f}s"
        total_attempts = 1 + self_fix_attempts + supervisor_guided_attempts

        if all_passed:
            update_subtask_passes(task_id, subtask_short_id, passes=True)
            extract_handoff_summary(subtask_id, response.content)
            attempt_info = f" (after {total_attempts} attempts)" if total_attempts > 1 else ""
            emit_log(
                task_id,
                "info",
                f"Subtask {subtask_short_id} PASSED{attempt_info} ({duration_str})",
                project_id=project_id,
            )
            debug_success(
                f"Subtask {subtask_short_id} verified",
                task_id=task_id,
                project_id=project_id,
                duration_ms=duration * 1000,
                self_fix_attempts=self_fix_attempts,
                supervisor_guided_attempts=supervisor_guided_attempts,
            )
        else:
            failed_steps = [r for r in step_results if not r["passed"]]
            for fail in failed_steps:
                error_msg = fail.get("error") or fail.get("reason") or "verification failed"
                issue_id = compute_issue_id(error_msg)
                issue_counts[issue_id] = issue_counts.get(issue_id, 0) + 1
            emit_log(
                task_id,
                "warn",
                f"Subtask {subtask_short_id} FAILED after {total_attempts} attempts: "
                f"{len(failed_steps)} step(s) ({duration_str})",
                project_id=project_id,
            )
            debug_error(
                f"Subtask {subtask_short_id} verification failed after self-healing",
                task_id=task_id,
                project_id=project_id,
                failed_steps=len(failed_steps),
                duration_ms=duration * 1000,
                self_fix_attempts=self_fix_attempts,
                supervisor_guided_attempts=supervisor_guided_attempts,
            )

        return {
            "subtask_id": subtask_short_id,
            "status": "passed" if all_passed else "failed",
            "step_results": step_results,
            "issue_counts": {k: v for k, v in issue_counts.items() if v >= 2},
            "self_fix_attempts": self_fix_attempts,
            "supervisor_guided_attempts": supervisor_guided_attempts,
            "extensions_granted": extensions_granted,
        }

    except Exception as e:
        logger.warning(
            "Subtask execution failed",
            subtask_id=subtask_short_id,
            error=str(e),
            traceback=traceback.format_exc(),
        )
        error_str = str(e)
        issue_id = compute_issue_id(error_str)
        issue_counts[issue_id] = issue_counts.get(issue_id, 0) + 1
        emit_error(
            task_id, f"Subtask {subtask_short_id} error: {error_str}", project_id=project_id
        )
        debug_error(
            f"Subtask {subtask_short_id} exception",
            task_id=task_id,
            project_id=project_id,
            error=error_str,
            issue_id=issue_id,
        )
        return {
            "subtask_id": subtask_short_id,
            "status": "failed",
            "error": error_str,
            "issue_id": issue_id,
            "issue_count": issue_counts[issue_id],
        }
