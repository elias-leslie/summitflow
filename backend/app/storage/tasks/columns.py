"""Tasks storage - Column definitions and constants.

This module defines the column lists used in task queries.
"""

# Column list for all task SELECT/RETURNING queries (40 columns)
# Order must match _row_to_dict index mapping
# Note: Migration 072 dropped: plan_content, objective, spirit_anti,
#       decisions, constraints, done_when (moved to task_spirit)
# Note: Migration 099 dropped: progress_log (moved to events table)
# Note: Migration 101 added: agent_override
# Note: Migration 028147425749 added: agent_hub_session_ids
TASK_COLUMNS = """id, project_id, capability_id, title, description, status,
    error_message, branch_name, commits, pull_request_url,
    total_sessions, total_tokens_used, created_at, started_at, completed_at,
    priority, task_type, parent_task_id, feature_id,
    claimed_by, claimed_at, lock_expires_at, tier, pre_merge_sha, review_result,
    current_phase, verification_result,
    raw_request, enrichment_status, enriched_by, enriched_at,
    complexity, autonomous,
    qa_status, qa_signoff_at, qa_signoff_by, qa_issues, agent_override, agent_hub_session_ids,
    labels"""

# Aliased version for JOINs (prefixed with t.)
TASK_COLUMNS_ALIASED = """t.id, t.project_id, t.capability_id, t.title, t.description, t.status,
    t.error_message, t.branch_name, t.commits, t.pull_request_url,
    t.total_sessions, t.total_tokens_used, t.created_at, t.started_at, t.completed_at,
    t.priority, t.task_type, t.parent_task_id, t.feature_id,
    t.claimed_by, t.claimed_at, t.lock_expires_at, t.tier, t.pre_merge_sha, t.review_result,
    t.current_phase, t.verification_result,
    t.raw_request, t.enrichment_status, t.enriched_by, t.enriched_at,
    t.complexity, t.autonomous,
    t.qa_status, t.qa_signoff_at, t.qa_signoff_by, t.qa_issues, t.agent_override, t.agent_hub_session_ids,
    t.labels"""

EXPECTED_TASK_COLUMNS = 40

# Columns for queries that JOIN with task_spirit (46 columns total)
# Adds 6 spirit fields: objective, spirit_anti, decisions, constraints, done_when, plan_status
TASK_COLUMNS_WITH_SPIRIT = """t.id, t.project_id, t.capability_id, t.title, t.description, t.status,
    t.error_message, t.branch_name, t.commits, t.pull_request_url,
    t.total_sessions, t.total_tokens_used, t.created_at, t.started_at, t.completed_at,
    t.priority, t.task_type, t.parent_task_id, t.feature_id,
    t.claimed_by, t.claimed_at, t.lock_expires_at, t.tier, t.pre_merge_sha, t.review_result,
    t.current_phase, t.verification_result,
    t.raw_request, t.enrichment_status, t.enriched_by, t.enriched_at,
    t.complexity, t.autonomous,
    t.qa_status, t.qa_signoff_at, t.qa_signoff_by, t.qa_issues, t.agent_override, t.agent_hub_session_ids,
    t.labels,
    ts.objective, ts.spirit_anti, ts.decisions, ts.constraints, ts.done_when, ts.plan_status"""

EXPECTED_TASK_COLUMNS_WITH_SPIRIT = 46
