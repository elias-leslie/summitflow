-- Migration 051: Explorer Sub-Elements
-- Tracks discoverable sub-elements within pages (tabs, accordions, expandable rows)
-- Part of Evidence Capture System (task-74a098a5)

CREATE TABLE IF NOT EXISTS explorer_sub_elements (
    id SERIAL PRIMARY KEY,
    explorer_entry_id INTEGER NOT NULL REFERENCES explorer_entries(id) ON DELETE CASCADE,
    selector VARCHAR(500) NOT NULL,
    element_type VARCHAR(50) NOT NULL,
    label VARCHAR(200),
    discovered_at TIMESTAMPTZ DEFAULT NOW(),
    last_captured_at TIMESTAMPTZ,
    capture_count INTEGER DEFAULT 0,
    UNIQUE(explorer_entry_id, selector)
);

CREATE INDEX IF NOT EXISTS idx_sub_elements_entry ON explorer_sub_elements(explorer_entry_id);
CREATE INDEX IF NOT EXISTS idx_sub_elements_type ON explorer_sub_elements(element_type);
