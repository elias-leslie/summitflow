-- Migration 012: Add attribution columns
-- Track which model extracted observations and reflected patterns

-- Add extracted_by to observations table
ALTER TABLE observations
ADD COLUMN IF NOT EXISTS extracted_by VARCHAR(50);

-- Add reflected_by to learned_patterns table
ALTER TABLE learned_patterns
ADD COLUMN IF NOT EXISTS reflected_by VARCHAR(50);

-- Optional index for querying by extractor/reflector
CREATE INDEX IF NOT EXISTS idx_observations_extracted_by
ON observations(extracted_by) WHERE extracted_by IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_learned_patterns_reflected_by
ON learned_patterns(reflected_by) WHERE reflected_by IS NOT NULL;

COMMENT ON COLUMN observations.extracted_by IS 'Model that extracted this observation (e.g., claude-opus-4)';
COMMENT ON COLUMN learned_patterns.reflected_by IS 'Model that generated this pattern (e.g., claude-opus-4)';
