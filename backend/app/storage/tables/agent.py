"""Agent-related tables: agent_sessions."""

import psycopg


def create_agent_tables(cur: psycopg.Cursor) -> None:
    """Create agent-related tables and their indexes."""
    _create_agent_sessions_table(cur)


def _create_agent_sessions_table(cur: psycopg.Cursor) -> None:
    """Create agent_sessions table and indexes."""
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_sessions (
            id SERIAL PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            session_id VARCHAR(50) NOT NULL,
            agent_type VARCHAR(50) NOT NULL,
            status VARCHAR(20) DEFAULT 'running',
            started_at TIMESTAMPTZ DEFAULT NOW(),
            ended_at TIMESTAMPTZ,
            -- Context tracking
            capabilities_attempted TEXT[] DEFAULT '{}',
            capabilities_passed TEXT[] DEFAULT '{}',
            capabilities_failed TEXT[] DEFAULT '{}',
            -- Stats
            tests_run INTEGER DEFAULT 0,
            tests_passed INTEGER DEFAULT 0,
            tests_failed INTEGER DEFAULT 0,
            -- Handoff
            notes TEXT,
            git_commit_sha VARCHAR(40),
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE(project_id, session_id)
        )
        """
    )

    # Create indexes
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_agent_sessions_project ON agent_sessions(project_id)"
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_agent_sessions_status ON agent_sessions(status)")
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_agent_sessions_created ON agent_sessions(created_at DESC)"
    )
