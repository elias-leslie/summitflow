-- Migration 054: Add verify_command to acceptance_criteria
-- Supports structured, verifiable acceptance criteria per Ralph Wiggum / Anthropic harness guidance

-- Add verify_command column for bash commands to verify criteria
ALTER TABLE acceptance_criteria
ADD COLUMN IF NOT EXISTS verify_command TEXT;

-- Add verify_by column to track how criterion should be verified
-- (measurement column was VARCHAR(20) and intended for type tags, keeping it for backwards compat)
ALTER TABLE acceptance_criteria
ADD COLUMN IF NOT EXISTS verify_by VARCHAR(20) DEFAULT 'test'
CHECK (verify_by IN ('test', 'opus', 'human', 'agent'));

-- Add expected_output column (threshold was already TEXT, but let's be explicit with a dedicated column)
ALTER TABLE acceptance_criteria
ADD COLUMN IF NOT EXISTS expected_output TEXT;

-- Comment for documentation
COMMENT ON COLUMN acceptance_criteria.verify_command IS 'Bash command to verify this criterion (e.g., pytest ..., grep ..., curl ...)';
COMMENT ON COLUMN acceptance_criteria.verify_by IS 'How criterion should be verified: test (automated), opus (AI review), human (manual), agent (during execution)';
COMMENT ON COLUMN acceptance_criteria.expected_output IS 'Expected output pattern or description for verify_command';

-- Index for finding unverified criteria by task
CREATE INDEX IF NOT EXISTS idx_task_criteria_unverified
ON task_criteria(task_id)
WHERE verified = false;
