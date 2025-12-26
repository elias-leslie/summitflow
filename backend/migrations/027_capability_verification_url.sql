-- Add verification_url column to capabilities table
-- This optional field holds the URL to screenshot/verify when all tests pass

ALTER TABLE capabilities ADD COLUMN IF NOT EXISTS verification_url TEXT;

COMMENT ON COLUMN capabilities.verification_url IS 'Optional URL to capture evidence from when capability tests pass';
