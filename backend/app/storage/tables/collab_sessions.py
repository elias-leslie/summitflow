"""Collaborative Design Review browser session tables."""

from __future__ import annotations

import psycopg


def create_collab_session_tables(cur: psycopg.Cursor) -> None:
    """Create collaboration session tables and indexes."""
    _create_collab_sessions_table(cur)
    _create_collab_participants_table(cur)
    _create_collab_annotations_table(cur)
    _create_collab_evidence_packets_table(cur)
    _create_collab_audit_events_table(cur)


def _create_collab_sessions_table(cur: psycopg.Cursor) -> None:
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS collab_sessions (
            id BIGSERIAL PRIMARY KEY,
            session_id TEXT NOT NULL UNIQUE,
            project_id TEXT REFERENCES projects(id) ON DELETE CASCADE,
            title TEXT NOT NULL,
            target_url TEXT,
            target_mode TEXT NOT NULL DEFAULT 'live_browser',
            state TEXT NOT NULL DEFAULT 'active',
            sensitive BOOLEAN NOT NULL DEFAULT TRUE,
            control_owner TEXT,
            control_expires_at TIMESTAMPTZ,
            browser_target_source TEXT,
            media_strategy TEXT NOT NULL DEFAULT 'webrtc_staged',
            evidence_policy TEXT NOT NULL DEFAULT 'compact_only',
            created_by_kind TEXT NOT NULL DEFAULT 'user',
            created_by_display TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            closed_at TIMESTAMPTZ,
            CONSTRAINT ck_collab_sessions_target_mode CHECK (
                target_mode IN ('live_browser', 'windows_co_browser', 'st_browser', 'manual')
            ),
            CONSTRAINT ck_collab_sessions_state CHECK (state IN ('active', 'closed')),
            CONSTRAINT ck_collab_sessions_evidence_policy CHECK (
                evidence_policy IN ('compact_only', 'sensitive_blocked')
            )
        )
        """
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_collab_sessions_project_state_created "
        "ON collab_sessions(project_id, state, created_at DESC)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_collab_sessions_state_created "
        "ON collab_sessions(state, created_at DESC)"
    )


def _create_collab_participants_table(cur: psycopg.Cursor) -> None:
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS collab_participants (
            id BIGSERIAL PRIMARY KEY,
            participant_id TEXT NOT NULL UNIQUE,
            session_id TEXT NOT NULL REFERENCES collab_sessions(session_id) ON DELETE CASCADE,
            participant_key TEXT NOT NULL,
            actor_kind TEXT NOT NULL DEFAULT 'user',
            display_name TEXT,
            role TEXT NOT NULL DEFAULT 'viewer',
            status TEXT NOT NULL DEFAULT 'active',
            last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            joined_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT ck_collab_participants_actor_kind CHECK (
                actor_kind IN ('user', 'agent', 'system')
            ),
            CONSTRAINT ck_collab_participants_role CHECK (
                role IN ('viewer', 'controller', 'observer')
            ),
            CONSTRAINT ck_collab_participants_status CHECK (
                status IN ('active', 'idle', 'left')
            ),
            CONSTRAINT uq_collab_participants_session_key UNIQUE (session_id, participant_key)
        )
        """
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_collab_participants_session_seen "
        "ON collab_participants(session_id, last_seen_at DESC)"
    )


def _create_collab_annotations_table(cur: psycopg.Cursor) -> None:
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS collab_annotations (
            id BIGSERIAL PRIMARY KEY,
            annotation_id TEXT NOT NULL UNIQUE,
            session_id TEXT NOT NULL REFERENCES collab_sessions(session_id) ON DELETE CASCADE,
            kind TEXT NOT NULL,
            page_key TEXT,
            page_url_snapshot TEXT,
            selector TEXT,
            anchor JSONB NOT NULL DEFAULT '{}'::jsonb,
            comment TEXT NOT NULL,
            created_by_kind TEXT NOT NULL DEFAULT 'user',
            created_by_display TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT ck_collab_annotations_kind CHECK (
                kind IN ('pin', 'box', 'highlight', 'pointer', 'comment')
            )
        )
        """
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_collab_annotations_session_created "
        "ON collab_annotations(session_id, created_at DESC)"
    )


def _create_collab_evidence_packets_table(cur: psycopg.Cursor) -> None:
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS collab_evidence_packets (
            id BIGSERIAL PRIMARY KEY,
            evidence_id TEXT NOT NULL UNIQUE,
            session_id TEXT NOT NULL REFERENCES collab_sessions(session_id) ON DELETE CASCADE,
            annotation_id TEXT REFERENCES collab_annotations(annotation_id) ON DELETE SET NULL,
            title TEXT,
            url TEXT,
            page_url_snapshot TEXT,
            viewport JSONB NOT NULL DEFAULT '{}'::jsonb,
            selector TEXT,
            bbox JSONB,
            context_summary TEXT NOT NULL,
            artifact_id TEXT,
            token_estimate INTEGER NOT NULL DEFAULT 0,
            created_by_kind TEXT NOT NULL DEFAULT 'user',
            created_by_display TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_collab_evidence_packets_session_created "
        "ON collab_evidence_packets(session_id, created_at DESC)"
    )


def _create_collab_audit_events_table(cur: psycopg.Cursor) -> None:
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS collab_audit_events (
            id BIGSERIAL PRIMARY KEY,
            audit_id TEXT NOT NULL UNIQUE,
            session_id TEXT NOT NULL REFERENCES collab_sessions(session_id) ON DELETE CASCADE,
            actor_kind TEXT NOT NULL DEFAULT 'user',
            action TEXT NOT NULL,
            detail JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_collab_audit_events_session_created "
        "ON collab_audit_events(session_id, created_at DESC)"
    )
