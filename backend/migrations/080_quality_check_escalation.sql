-- Add escalation tracking column to quality_check_results
-- When fix attempts exceed MAX_FIX_ATTEMPTS, a blocking task is created
-- and linked here for tracking

ALTER TABLE quality_check_results
    ADD COLUMN IF NOT EXISTS escalation_task_id TEXT REFERENCES tasks(id) ON DELETE SET NULL;

-- Index for looking up escalated results by task
CREATE INDEX IF NOT EXISTS idx_qcr_escalation_task_id ON quality_check_results(escalation_task_id)
    WHERE escalation_task_id IS NOT NULL;
