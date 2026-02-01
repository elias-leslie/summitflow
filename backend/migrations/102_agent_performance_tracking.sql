-- Migration 102: Agent performance tracking schema
-- Establishes tables for tracking model performance across different task types and complexities

CREATE TABLE IF NOT EXISTS model_performance_logs (
    id SERIAL PRIMARY KEY,
    task_id TEXT REFERENCES tasks(id) ON DELETE CASCADE,
    model_name TEXT NOT NULL,
    task_type TEXT NOT NULL,
    complexity TEXT NOT NULL,
    outcome TEXT NOT NULL CHECK (outcome IN ('success', 'failure', 'error')),
    quality_score DOUBLE PRECISION, -- 0.0 to 1.0
    tokens_used INTEGER,
    latency_ms INTEGER,
    error_category TEXT,
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexing for fast retrieval of historical performance
CREATE INDEX IF NOT EXISTS idx_model_perf_logs_lookup 
    ON model_performance_logs(model_name, task_type, complexity);
CREATE INDEX IF NOT EXISTS idx_model_perf_logs_task_id 
    ON model_performance_logs(task_id);
CREATE INDEX IF NOT EXISTS idx_model_perf_logs_created_at 
    ON model_performance_logs(created_at DESC);

-- Summary table for fast routing decisions
CREATE TABLE IF NOT EXISTS model_performance_metrics (
    model_name TEXT NOT NULL,
    task_type TEXT NOT NULL,
    complexity TEXT NOT NULL,
    success_count INTEGER DEFAULT 0,
    failure_count INTEGER DEFAULT 0,
    total_executions INTEGER DEFAULT 0,
    avg_quality_score DOUBLE PRECISION DEFAULT 0.0,
    avg_latency_ms DOUBLE PRECISION DEFAULT 0.0,
    avg_tokens_used DOUBLE PRECISION DEFAULT 0.0,
    last_executed_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (model_name, task_type, complexity)
);

-- Index for sorting by performance during routing
CREATE INDEX IF NOT EXISTS idx_model_perf_metrics_ranking
    ON model_performance_metrics(task_type, complexity, success_count DESC, avg_quality_score DESC);

-- Comments
COMMENT ON TABLE model_performance_logs IS 'Individual records of model execution outcomes for performance analysis.';
COMMENT ON TABLE model_performance_metrics IS 'Aggregated performance metrics for models, used for intelligent task routing.';
