"""Tasks storage - Column definitions and constants.

This module defines the column lists used in task queries.
"""

# Column list for all task SELECT/RETURNING queries (39 columns)
# Order must match _row_to_dict index mapping
# Note: Migration 072 dropped: plan_content, objective, spirit_anti,
#       decisions, constraints, done_when (moved to task_spirit)
# Note: Migration 099 dropped: progress_log (moved to events table)
# Note: Migration 101 added: agent_override
# Note: Migration 028147425749 added: agent_hub_session_ids
# Note: Migration 105 added: ai_review
# Note: Migration a3b7c1d2e4f5 dropped: pull_request_url
# Note: Migration 52bde0e4709d added: conflict_info, merge_sha
# Note: Migration a9c4e1b7d2e8 dropped: autonomous (derived from execution_mode)
# Note: updated_at surfaced for frontend sorting
TASK_COLUMNS = """id, project_id, capability_id, title, description, status,
    error_message, branch_name, commits,
    total_sessions, total_tokens_used, created_at, started_at, completed_at,
    priority, task_type, parent_task_id, feature_id,
    claimed_by, claimed_at, lock_expires_at, tier, pre_merge_sha, review_result,
    current_phase, verification_result,
    raw_request, enrichment_status, enriched_by, enriched_at,
    complexity, execution_mode,
    agent_override, agent_hub_session_ids,
    labels, ai_review, conflict_info, merge_sha, updated_at"""

# Aliased version for JOINs (prefixed with t.)
TASK_COLUMNS_ALIASED = """t.id, t.project_id, t.capability_id, t.title, t.description, t.status,
    t.error_message, t.branch_name, t.commits,
    t.total_sessions, t.total_tokens_used, t.created_at, t.started_at, t.completed_at,
    t.priority, t.task_type, t.parent_task_id, t.feature_id,
    t.claimed_by, t.claimed_at, t.lock_expires_at, t.tier, t.pre_merge_sha, t.review_result,
    t.current_phase, t.verification_result,
    t.raw_request, t.enrichment_status, t.enriched_by, t.enriched_at,
    t.complexity, t.execution_mode,
    t.agent_override, t.agent_hub_session_ids,
    t.labels, t.ai_review, t.conflict_info, t.merge_sha, t.updated_at"""

EXPECTED_TASK_COLUMNS = 39

# Columns for queries that JOIN with task_spirit (41 columns total)
# Adds 2 spirit fields: done_when, plan_status
# Dropped: objective, spirit_anti, decisions, constraints (migration 52f2ce12774b)
# Dropped: autonomous (migration a9c4e1b7d2e8)
TASK_COLUMNS_WITH_SPIRIT = """t.id, t.project_id, t.capability_id, t.title, t.description, t.status,
    t.error_message, t.branch_name, t.commits,
    t.total_sessions, t.total_tokens_used, t.created_at, t.started_at, t.completed_at,
    t.priority, t.task_type, t.parent_task_id, t.feature_id,
    t.claimed_by, t.claimed_at, t.lock_expires_at, t.tier, t.pre_merge_sha, t.review_result,
    t.current_phase, t.verification_result,
    t.raw_request, t.enrichment_status, t.enriched_by, t.enriched_at,
    t.complexity, t.execution_mode,
    t.agent_override, t.agent_hub_session_ids,
    t.labels, t.ai_review, t.conflict_info, t.merge_sha, t.updated_at,
    ts.done_when, ts.plan_status"""

EXPECTED_TASK_COLUMNS_WITH_SPIRIT = 41
