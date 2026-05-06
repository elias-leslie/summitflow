--
-- PostgreSQL database dump
--

\restrict IQaHikaoYBGqGtEiTocohupnoeKE9aZh0xW9D8asSUTeeLb9JLfYgjbilD9gFdv

-- Dumped from database version 16.11 (Ubuntu 16.11-0ubuntu0.24.04.1)
-- Dumped by pg_dump version 16.11 (Ubuntu 16.11-0ubuntu0.24.04.1)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: vector; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public;


--
-- Name: EXTENSION vector; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION vector IS 'vector data type and ivfflat and hnsw access methods';


--
-- Name: check_subtask_dependency_cycle(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.check_subtask_dependency_cycle() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE
    cycle_detected BOOLEAN;
BEGIN
    -- Check for cycle using recursive CTE
    WITH RECURSIVE dependency_chain AS (
        -- Start from the dependency we're about to add
        SELECT NEW.depends_on_subtask_id AS subtask_id, 1 AS depth
        UNION ALL
        -- Follow the chain backwards
        SELECT sd.depends_on_subtask_id, dc.depth + 1
        FROM subtask_dependencies sd
        JOIN dependency_chain dc ON sd.subtask_id = dc.subtask_id
        WHERE dc.depth < 100  -- Prevent infinite loops
    )
    SELECT EXISTS (
        SELECT 1 FROM dependency_chain WHERE subtask_id = NEW.subtask_id
    ) INTO cycle_detected;

    IF cycle_detected THEN
        RAISE EXCEPTION 'Circular dependency detected: % -> % would create cycle',
            NEW.subtask_id, NEW.depends_on_subtask_id;
    END IF;

    RETURN NEW;
END;
$$;


--
-- Name: enforce_steps_complete_before_subtask_pass(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.enforce_steps_complete_before_subtask_pass() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE
    incomplete_steps INTEGER;
BEGIN
    -- Only check when setting passes to TRUE
    IF NEW.passes = TRUE AND (OLD.passes IS NULL OR OLD.passes = FALSE) THEN
        -- Count incomplete steps, EXCLUDING plan_defect status
        -- plan_defect steps have been acknowledged as plan issues and can be skipped
        SELECT COUNT(*) INTO incomplete_steps
        FROM task_subtask_steps
        WHERE subtask_id = NEW.id
          AND passes = FALSE
          AND (status IS NULL OR status != 'plan_defect');

        IF incomplete_steps > 0 THEN
            RAISE EXCEPTION 'Cannot pass subtask % with % incomplete steps. Use "st step list" to see them.',
                NEW.subtask_id, incomplete_steps;
        END IF;
    END IF;
    RETURN NEW;
END;
$$;


--
-- Name: FUNCTION enforce_steps_complete_before_subtask_pass(); Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON FUNCTION public.enforce_steps_complete_before_subtask_pass() IS 'Enforces that all steps must be complete (passes=true) before a subtask can be marked as passed.
Exception: Steps with status=''plan_defect'' are allowed to be skipped since they represent
acknowledged issues with the plan (wrong verify_command, impossible expected_output, etc.)
rather than implementation failures.';


--
-- Name: enforce_subtask_dependencies(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.enforce_subtask_dependencies() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE
    incomplete_deps TEXT[];
BEGIN
    -- Only check when setting passes to TRUE (marking subtask complete)
    IF NEW.passes = TRUE AND (OLD.passes IS NULL OR OLD.passes = FALSE) THEN
        -- Check for incomplete dependencies
        SELECT ARRAY_AGG(dep.subtask_id)
        INTO incomplete_deps
        FROM subtask_dependencies sd
        JOIN task_subtasks dep ON sd.depends_on_subtask_id = dep.id
        WHERE sd.subtask_id = NEW.id AND dep.passes = FALSE;

        IF incomplete_deps IS NOT NULL AND array_length(incomplete_deps, 1) > 0 THEN
            RAISE EXCEPTION 'Cannot pass subtask % with incomplete dependencies: %',
                NEW.subtask_id, array_to_string(incomplete_deps, ', ');
        END IF;
    END IF;
    RETURN NEW;
END;
$$;


--
-- Name: update_mockups_updated_at(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.update_mockups_updated_at() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;


--
-- Name: update_project_evidence_config_updated_at(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.update_project_evidence_config_updated_at() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;


--
-- Name: update_task_ac_updated_at(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.update_task_ac_updated_at() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;


--
-- Name: update_task_spirit_updated_at(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.update_task_spirit_updated_at() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: agent_sessions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agent_sessions (
    id integer NOT NULL,
    project_id text NOT NULL,
    session_id character varying(50) NOT NULL,
    agent_type character varying(50) NOT NULL,
    status character varying(20) DEFAULT 'running'::character varying,
    started_at timestamp with time zone DEFAULT now(),
    ended_at timestamp with time zone,
    capabilities_attempted text[] DEFAULT '{}'::text[],
    capabilities_passed text[] DEFAULT '{}'::text[],
    capabilities_failed text[] DEFAULT '{}'::text[],
    tests_run integer DEFAULT 0,
    tests_passed integer DEFAULT 0,
    tests_failed integer DEFAULT 0,
    notes text,
    git_commit_sha character varying(40),
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    build_state jsonb DEFAULT '{}'::jsonb
);


--
-- Name: COLUMN agent_sessions.build_state; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.agent_sessions.build_state IS 'JSON state for build recovery: attempt_history, good_commits, current_strategy';


--
-- Name: agent_sessions_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.agent_sessions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: agent_sessions_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.agent_sessions_id_seq OWNED BY public.agent_sessions.id;


--
-- Name: agent_tools; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agent_tools (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    name character varying(100) NOT NULL,
    slug character varying(50) NOT NULL,
    command text NOT NULL,
    process_name character varying(100) NOT NULL,
    description text,
    color character varying(20),
    display_order integer DEFAULT 0 NOT NULL,
    is_default boolean DEFAULT false NOT NULL,
    enabled boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: alembic_version; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.alembic_version (
    version_num character varying(32) NOT NULL
);


--
-- Name: artifacts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.artifacts (
    id integer NOT NULL,
    project_id text NOT NULL,
    artifact_id character varying(50) NOT NULL,
    feature_id character varying(20) NOT NULL,
    criterion_id character varying(20),
    artifact_type character varying(20) DEFAULT 'evidence'::character varying,
    file_path character varying(500) NOT NULL,
    file_size_bytes integer,
    version integer DEFAULT 1,
    is_current boolean DEFAULT true,
    captured_at timestamp with time zone DEFAULT now(),
    expires_at timestamp with time zone,
    quality_status character varying(20) DEFAULT 'pending'::character varying,
    quality_issues jsonb DEFAULT '[]'::jsonb,
    confidence double precision,
    ai_reviewed_at timestamp with time zone,
    ai_reviewed_by character varying(50),
    ai_evidence text,
    user_reviewed_at timestamp with time zone,
    user_approved boolean,
    user_notes text,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: artifacts_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.artifacts_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: artifacts_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.artifacts_id_seq OWNED BY public.artifacts.id;


--
-- Name: backup_sources; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.backup_sources (
    id text NOT NULL,
    name text NOT NULL,
    path text NOT NULL,
    source_type text DEFAULT 'project'::text NOT NULL,
    project_id text,
    enabled boolean DEFAULT false NOT NULL,
    frequency text DEFAULT 'daily'::text NOT NULL,
    retention_days integer DEFAULT 14 NOT NULL,
    last_run_at timestamp with time zone,
    next_run_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    storage_backend_id text,
    last_restore_tested_at timestamp with time zone,
    last_restore_test_ok boolean,
    last_restore_test_error text,
    last_drill_at timestamp with time zone,
    last_drill_ok boolean,
    last_drill_backup_id text,
    last_drill_result jsonb,
    CONSTRAINT source_frequency_check CHECK ((frequency = ANY (ARRAY['daily'::text, 'weekly'::text, 'monthly'::text, 'hourly'::text]))),
    CONSTRAINT source_type_check CHECK ((source_type = ANY (ARRAY['project'::text, 'config'::text, 'workspace'::text, 'infrastructure'::text])))
);


--
-- Name: backups; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.backups (
    id character varying(20) NOT NULL,
    project_id text NOT NULL,
    name character varying(100) NOT NULL,
    backup_type character varying(20) DEFAULT 'manual'::character varying NOT NULL,
    status character varying(30) DEFAULT 'pending'::character varying NOT NULL,
    size_bytes bigint,
    db_size_bytes bigint,
    files_size_bytes bigint,
    location text,
    note text,
    created_at timestamp with time zone DEFAULT now(),
    started_at timestamp with time zone,
    completed_at timestamp with time zone,
    error_message text,
    verified boolean,
    verified_at timestamp with time zone,
    checksum text,
    total_files integer,
    verification_json jsonb,
    source_id text NOT NULL,
    storage_backend_id text,
    wal_start_lsn text,
    wal_end_lsn text,
    CONSTRAINT backups_status_check CHECK (((status)::text = ANY (ARRAY[('pending'::character varying)::text, ('running'::character varying)::text, ('completed'::character varying)::text, ('failed'::character varying)::text, ('completed_pending_upload'::character varying)::text]))),
    CONSTRAINT backups_type_check CHECK (((backup_type)::text = ANY (ARRAY[('manual'::character varying)::text, ('scheduled'::character varying)::text])))
);


--
-- Name: design_asset_exports; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.design_asset_exports (
    id integer NOT NULL,
    asset_id integer NOT NULL,
    export_id character varying(50) NOT NULL,
    export_type character varying(30) NOT NULL,
    file_path text NOT NULL,
    manifest_path text,
    metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_design_asset_exports_type CHECK (((export_type)::text = ANY ((ARRAY['original'::character varying, 'sprite_frames'::character varying, 'atlas_json'::character varying])::text[])))
);


--
-- Name: design_asset_exports_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.design_asset_exports_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: design_asset_exports_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.design_asset_exports_id_seq OWNED BY public.design_asset_exports.id;


--
-- Name: design_assets; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.design_assets (
    id integer NOT NULL,
    project_id text NOT NULL,
    asset_id character varying(50) NOT NULL,
    name character varying(255) NOT NULL,
    description text,
    asset_type character varying(50) NOT NULL,
    workflow character varying(50) DEFAULT 'concept'::character varying NOT NULL,
    status character varying(30) DEFAULT 'generated'::character varying NOT NULL,
    prompt text NOT NULL,
    negative_prompt text,
    style_prompt text,
    background character varying(20) DEFAULT 'transparent'::character varying NOT NULL,
    width integer NOT NULL,
    height integer NOT NULL,
    transparent_background boolean DEFAULT false NOT NULL,
    model character varying(100),
    generator character varying(100),
    file_path text,
    source_asset_id integer,
    sheet_columns integer,
    sheet_rows integer,
    frame_width integer,
    frame_height integer,
    animation_labels text[] DEFAULT '{}'::text[] NOT NULL,
    tags text[] DEFAULT '{}'::text[] NOT NULL,
    metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    approved_at timestamp with time zone,
    approved_by character varying(100),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_design_assets_background CHECK (((background)::text = ANY ((ARRAY['transparent'::character varying, 'solid'::character varying, 'scene'::character varying])::text[]))),
    CONSTRAINT ck_design_assets_status CHECK (((status)::text = ANY ((ARRAY['generated'::character varying, 'approved'::character varying, 'rejected'::character varying, 'archived'::character varying, 'exported'::character varying])::text[]))),
    CONSTRAINT ck_design_assets_type CHECK (((asset_type)::text = ANY ((ARRAY['sprite'::character varying, 'sprite_sheet'::character varying, 'portrait'::character varying, 'environment'::character varying, 'icon'::character varying, 'illustration'::character varying, 'ui_texture'::character varying, 'marketing_mockup'::character varying, 'tile_set'::character varying, 'concept_art'::character varying])::text[]))),
    CONSTRAINT ck_design_assets_workflow CHECK (((workflow)::text = ANY ((ARRAY['concept'::character varying, 'production'::character varying, 'marketing'::character varying, 'ui'::character varying])::text[])))
);


--
-- Name: design_assets_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.design_assets_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: design_assets_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.design_assets_id_seq OWNED BY public.design_assets.id;


--
-- Name: design_rules; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.design_rules (
    id integer NOT NULL,
    standard_id integer NOT NULL,
    category character varying(50) NOT NULL,
    rule_id character varying(50) NOT NULL,
    name character varying(200) NOT NULL,
    requirements jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: design_rules_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.design_rules_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: design_rules_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.design_rules_id_seq OWNED BY public.design_rules.id;


--
-- Name: design_standards; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.design_standards (
    id integer NOT NULL,
    project_id text,
    name character varying(100) NOT NULL,
    description text,
    base_standard_id integer,
    is_base boolean DEFAULT false,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: design_standards_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.design_standards_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: design_standards_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.design_standards_id_seq OWNED BY public.design_standards.id;


--
-- Name: events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.events (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    project_id text NOT NULL,
    trace_id text NOT NULL,
    span_id text,
    parent_span_id text,
    event_type text NOT NULL,
    name text,
    source text NOT NULL,
    level text DEFAULT 'info'::text NOT NULL,
    visibility text DEFAULT 'user'::text NOT NULL,
    message text,
    attributes jsonb DEFAULT '{}'::jsonb,
    "timestamp" timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT events_level_check CHECK ((level = ANY (ARRAY['error'::text, 'warning'::text, 'info'::text, 'debug'::text]))),
    CONSTRAINT events_visibility_check CHECK ((visibility = ANY (ARRAY['user'::text, 'internal'::text, 'debug'::text])))
);


--
-- Name: TABLE events; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.events IS 'Unified execution events with OTel-inspired tracing';


--
-- Name: COLUMN events.trace_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.events.trace_id IS 'Execution trace ID (typically task_id)';


--
-- Name: COLUMN events.span_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.events.span_id IS 'Unique span identifier within trace';


--
-- Name: COLUMN events.parent_span_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.events.parent_span_id IS 'Parent span for hierarchical tracing';


--
-- Name: COLUMN events.event_type; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.events.event_type IS 'Event type (state_change, progress, error, log, etc)';


--
-- Name: COLUMN events.source; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.events.source IS 'Event source (orchestrator, worker, agent, system)';


--
-- Name: COLUMN events.level; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.events.level IS 'Log level: error, warning, info, debug';


--
-- Name: COLUMN events.visibility; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.events.visibility IS 'Visibility scope: user (shown in UI), internal, debug';


--
-- Name: COLUMN events.attributes; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.events.attributes IS 'Structured event metadata as JSONB';


--
-- Name: explorer_entries; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.explorer_entries (
    id integer NOT NULL,
    project_id character varying(50) NOT NULL,
    entry_type character varying(20) NOT NULL,
    path character varying(500) NOT NULL,
    name character varying(255) NOT NULL,
    health_status character varying(20) DEFAULT 'unknown'::character varying,
    last_scanned_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    metadata jsonb DEFAULT '{}'::jsonb,
    evidence_count integer DEFAULT 0,
    last_evidence_at timestamp with time zone
);


--
-- Name: explorer_entries_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.explorer_entries_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: explorer_entries_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.explorer_entries_id_seq OWNED BY public.explorer_entries.id;


--
-- Name: explorer_relationships; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.explorer_relationships (
    id integer NOT NULL,
    project_id character varying(50) NOT NULL,
    source_type character varying(20) NOT NULL,
    source_path character varying(500) NOT NULL,
    target_type character varying(20) NOT NULL,
    target_path character varying(500) NOT NULL,
    relationship character varying(50) NOT NULL,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: explorer_relationships_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.explorer_relationships_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: explorer_relationships_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.explorer_relationships_id_seq OWNED BY public.explorer_relationships.id;


--
-- Name: explorer_sub_elements; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.explorer_sub_elements (
    id integer NOT NULL,
    explorer_entry_id integer NOT NULL,
    selector character varying(500) NOT NULL,
    element_type character varying(50) NOT NULL,
    label character varying(200),
    discovered_at timestamp with time zone DEFAULT now(),
    last_captured_at timestamp with time zone,
    capture_count integer DEFAULT 0
);


--
-- Name: explorer_sub_elements_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.explorer_sub_elements_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: explorer_sub_elements_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.explorer_sub_elements_id_seq OWNED BY public.explorer_sub_elements.id;


--
-- Name: explorer_symbols; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.explorer_symbols (
    id bigint NOT NULL,
    project_id text NOT NULL,
    file_path text NOT NULL,
    symbol_id text NOT NULL,
    qualified_name text NOT NULL,
    name text NOT NULL,
    kind text NOT NULL,
    signature text NOT NULL,
    language text NOT NULL,
    start_line integer NOT NULL,
    end_line integer NOT NULL,
    byte_offset integer NOT NULL,
    byte_length integer NOT NULL,
    content_hash text NOT NULL,
    summary text,
    keywords text[] DEFAULT '{}'::text[] NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: explorer_symbols_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.explorer_symbols_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: explorer_symbols_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.explorer_symbols_id_seq OWNED BY public.explorer_symbols.id;


--
-- Name: maintenance_runs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.maintenance_runs (
    id bigint NOT NULL,
    workflow_name text NOT NULL,
    status text NOT NULL,
    started_at timestamp with time zone DEFAULT now() NOT NULL,
    finished_at timestamp with time zone,
    duration_ms integer,
    rows_cleaned integer DEFAULT 0 NOT NULL,
    summary jsonb DEFAULT '{}'::jsonb NOT NULL,
    error_message text,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: maintenance_runs_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.maintenance_runs_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: maintenance_runs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.maintenance_runs_id_seq OWNED BY public.maintenance_runs.id;


--
-- Name: mockups; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.mockups (
    id integer NOT NULL,
    project_id text NOT NULL,
    mockup_id character varying(50) NOT NULL,
    name character varying(255) NOT NULL,
    description text,
    mockup_type character varying(50) DEFAULT 'component'::character varying NOT NULL,
    file_path text,
    content text,
    status character varying(20) DEFAULT 'generated'::character varying NOT NULL,
    approved_at timestamp with time zone,
    approved_by character varying(100),
    applied_at timestamp with time zone,
    task_id text,
    page_path text,
    version integer DEFAULT 1 NOT NULL,
    parent_mockup_id integer,
    generator character varying(50),
    generation_prompt text,
    generation_time_ms integer,
    iteration_count integer DEFAULT 1 NOT NULL,
    metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT mockups_status_check CHECK (((status)::text = ANY (ARRAY[('generated'::character varying)::text, ('pending_approval'::character varying)::text, ('approved'::character varying)::text, ('rejected'::character varying)::text, ('applied'::character varying)::text, ('archived'::character varying)::text]))),
    CONSTRAINT mockups_type_check CHECK (((mockup_type)::text = ANY (ARRAY[('component'::character varying)::text, ('page'::character varying)::text, ('layout'::character varying)::text, ('icon'::character varying)::text, ('illustration'::character varying)::text])))
);


--
-- Name: mockups_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.mockups_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: mockups_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.mockups_id_seq OWNED BY public.mockups.id;


--
-- Name: notifications; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.notifications (
    id text NOT NULL,
    project_id text NOT NULL,
    task_id text,
    type character varying(50) NOT NULL,
    title text NOT NULL,
    message text NOT NULL,
    severity character varying(20) DEFAULT 'info'::character varying NOT NULL,
    status character varying(20) DEFAULT 'pending'::character varying NOT NULL,
    metadata jsonb DEFAULT '{}'::jsonb,
    created_at timestamp with time zone DEFAULT now(),
    read_at timestamp with time zone,
    dismissed_at timestamp with time zone,
    user_email text
);


--
-- Name: projects; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.projects (
    id text NOT NULL,
    name text NOT NULL,
    base_url text NOT NULL,
    health_endpoint text DEFAULT '/health'::text,
    created_at timestamp with time zone DEFAULT now(),
    frontend_port integer DEFAULT 3000,
    backend_port integer DEFAULT 8000,
    root_path text,
    backend_dir text,
    browser_scripts_dir text,
    data_dir text,
    category text DEFAULT 'dev'::text NOT NULL,
    sidebar_rank integer,
    agent_configs jsonb DEFAULT '{"claude_model": "sonnet", "gemini_model": "gemini-2.5-flash", "default_agent": "gemini", "claude_enabled": true, "gemini_enabled": true}'::jsonb,
    test_config jsonb DEFAULT '{"node_path": "npx", "pytest_path": ".venv/bin/pytest", "backend_root": "backend", "frontend_root": "frontend", "test_patterns": {"pytest": "tests/**/*.py", "vitest": "**/*.test.{ts,tsx}", "playwright": "tests/e2e/**/*.spec.ts"}}'::jsonb,
    CONSTRAINT projects_category_check CHECK ((category = ANY (ARRAY['production'::text, 'testing'::text, 'dev'::text]))),
    CONSTRAINT projects_sidebar_rank_check CHECK (((sidebar_rank IS NULL) OR (sidebar_rank >= 0)))
);


--
-- Name: COLUMN projects.agent_configs; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.projects.agent_configs IS 'Agent configuration for this project. Structure:
{
    "claude_enabled": boolean,      -- Whether Claude is enabled
    "gemini_enabled": boolean,      -- Whether Gemini is enabled
    "default_agent": string,        -- Default agent ("claude" or "gemini")
    "claude_model": string,         -- Claude model (sonnet, opus, haiku)
    "gemini_model": string          -- Gemini model (gemini-2.5-pro, gemini-2.5-flash)
}';


--
-- Name: qa_issues; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.qa_issues (
    id integer NOT NULL,
    project_id character varying(50) NOT NULL,
    issue_type character varying(50) NOT NULL,
    severity character varying(20) DEFAULT 'medium'::character varying NOT NULL,
    file_path text,
    entry_id integer,
    title character varying(255) NOT NULL,
    description text,
    metadata jsonb DEFAULT '{}'::jsonb,
    first_detected_at timestamp with time zone DEFAULT now() NOT NULL,
    last_detected_at timestamp with time zone DEFAULT now() NOT NULL,
    detected_in_scan_id integer,
    detection_count integer DEFAULT 1,
    status character varying(20) DEFAULT 'open'::character varying NOT NULL,
    resolved_at timestamp with time zone,
    resolution_scan_id integer,
    resolution_reason text,
    st_task_id text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: TABLE qa_issues; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.qa_issues IS 'Tracks QA-detected issues for self-healing task automation';


--
-- Name: COLUMN qa_issues.detection_count; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.qa_issues.detection_count IS 'Number of times this issue was detected (helps identify persistent problems)';


--
-- Name: COLUMN qa_issues.st_task_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.qa_issues.st_task_id IS 'Links to SummitFlow task for auto-close on resolution';


--
-- Name: qa_issues_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.qa_issues_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: qa_issues_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.qa_issues_id_seq OWNED BY public.qa_issues.id;


--
-- Name: quality_check_results; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.quality_check_results (
    id integer NOT NULL,
    project_id text NOT NULL,
    check_type character varying(20) NOT NULL,
    check_name character varying(100),
    status character varying(20) NOT NULL,
    error_count integer DEFAULT 0,
    warning_count integer DEFAULT 0,
    error_message text,
    file_path text,
    line_number integer,
    column_number integer,
    run_duration_ms integer,
    git_sha character varying(40),
    triggered_by character varying(50),
    fix_attempted boolean DEFAULT false,
    fix_attempts integer DEFAULT 0,
    fixed_at timestamp with time zone,
    fixed_by text,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    escalation_task_id text,
    CONSTRAINT quality_check_results_check_type_check CHECK (((check_type)::text = ANY ((ARRAY['pytest'::character varying, 'ruff'::character varying, 'types'::character varying, 'biome'::character varying, 'tsc'::character varying])::text[]))),
    CONSTRAINT quality_check_results_status_check CHECK (((status)::text = ANY (ARRAY[('pass'::character varying)::text, ('fail'::character varying)::text, ('error'::character varying)::text, ('skipped'::character varying)::text])))
);


--
-- Name: TABLE quality_check_results; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.quality_check_results IS 'Stores results from dt quality gate checks. Tracks failures, fix attempts, and resolution status.';


--
-- Name: COLUMN quality_check_results.check_type; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.quality_check_results.check_type IS 'Type of quality check: pytest, ruff, mypy, biome, tsc';


--
-- Name: COLUMN quality_check_results.triggered_by; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.quality_check_results.triggered_by IS 'What triggered this check: commit, manual, ci, agent';


--
-- Name: quality_check_results_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.quality_check_results_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: quality_check_results_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.quality_check_results_id_seq OWNED BY public.quality_check_results.id;


--
-- Name: refactor_sessions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.refactor_sessions (
    id integer NOT NULL,
    project_id character varying(50) NOT NULL,
    task_id text NOT NULL,
    baseline_scan_id integer,
    baseline_commit_sha character varying(40),
    status character varying(20) DEFAULT 'active'::character varying NOT NULL,
    session_id text,
    final_scan_id integer,
    final_commit_sha character varying(40),
    subtasks_planned integer DEFAULT 0,
    subtasks_completed integer DEFAULT 0,
    started_at timestamp with time zone DEFAULT now() NOT NULL,
    completed_at timestamp with time zone
);


--
-- Name: TABLE refactor_sessions; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.refactor_sessions IS 'Persists refactor_it baseline scan IDs and session metadata, replacing volatile /tmp storage';


--
-- Name: COLUMN refactor_sessions.baseline_scan_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.refactor_sessions.baseline_scan_id IS 'Reference to scan_history entry for the baseline scan';


--
-- Name: COLUMN refactor_sessions.baseline_commit_sha; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.refactor_sessions.baseline_commit_sha IS 'Git commit SHA when baseline was taken';


--
-- Name: refactor_sessions_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.refactor_sessions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: refactor_sessions_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.refactor_sessions_id_seq OWNED BY public.refactor_sessions.id;


--
-- Name: scan_history; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.scan_history (
    id integer NOT NULL,
    project_id character varying(50) NOT NULL,
    scan_type character varying(50) NOT NULL,
    triggered_by character varying(50) DEFAULT 'manual'::character varying NOT NULL,
    triggered_by_session text,
    triggered_by_user text,
    trigger_context jsonb DEFAULT '{}'::jsonb,
    started_at timestamp with time zone DEFAULT now() NOT NULL,
    completed_at timestamp with time zone,
    duration_ms integer,
    status character varying(20) DEFAULT 'running'::character varying NOT NULL,
    error_message text,
    metrics jsonb DEFAULT '{}'::jsonb,
    entries_found integer DEFAULT 0,
    entries_saved integer DEFAULT 0,
    previous_scan_id integer,
    metrics_delta jsonb DEFAULT '{}'::jsonb,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: TABLE scan_history; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.scan_history IS 'Tracks all explorer scan executions with trigger metadata and metrics for trend visualization';


--
-- Name: COLUMN scan_history.triggered_by; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.scan_history.triggered_by IS 'Source that initiated the scan: manual, refactor_it, daily_qa_scan, audit_it, celery_beat';


--
-- Name: COLUMN scan_history.trigger_context; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.scan_history.trigger_context IS 'Additional context about the trigger (phase name, goal, baseline_scan_id, etc.)';


--
-- Name: COLUMN scan_history.metrics_delta; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.scan_history.metrics_delta IS 'Computed difference from previous_scan_id metrics (added, removed, changed counts)';


--
-- Name: scan_history_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.scan_history_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: scan_history_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.scan_history_id_seq OWNED BY public.scan_history.id;


--
-- Name: scan_states; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.scan_states (
    project_id character varying(255) NOT NULL,
    status character varying(50) DEFAULT 'idle'::character varying NOT NULL,
    current_type character varying(50),
    types_total integer DEFAULT 0,
    types_completed integer DEFAULT 0,
    started_at timestamp with time zone,
    completed_at timestamp with time zone,
    error text,
    results jsonb DEFAULT '{}'::jsonb,
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: TABLE scan_states; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.scan_states IS 'Persists scan state across backend restarts';


--
-- Name: sitemap_entries; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sitemap_entries (
    id integer NOT NULL,
    project_id text NOT NULL,
    port integer NOT NULL,
    path text NOT NULL,
    method character varying(10) DEFAULT 'GET'::character varying,
    entry_type character varying(20) NOT NULL,
    source character varying(50),
    title text,
    parent_path text,
    health_status character varying(20) DEFAULT 'unknown'::character varying,
    console_errors integer DEFAULT 0,
    console_warnings integer DEFAULT 0,
    http_status integer,
    response_time_ms integer,
    last_error_message text,
    last_checked_at timestamp with time zone,
    discovered_at timestamp with time zone DEFAULT now(),
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: sitemap_entries_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.sitemap_entries_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: sitemap_entries_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.sitemap_entries_id_seq OWNED BY public.sitemap_entries.id;


--
-- Name: storage_backends; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.storage_backends (
    id text NOT NULL,
    name text NOT NULL,
    backend_type text DEFAULT 'smb'::text NOT NULL,
    config jsonb DEFAULT '{}'::jsonb NOT NULL,
    is_default boolean DEFAULT false,
    enabled boolean DEFAULT true,
    last_test_at timestamp with time zone,
    last_test_ok boolean,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: subtask_citations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.subtask_citations (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    subtask_id text NOT NULL,
    episode_uuid text NOT NULL,
    rating text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT subtask_citations_rating_check CHECK ((rating = ANY (ARRAY['used'::text, 'helpful'::text, 'harmful'::text])))
);


--
-- Name: subtask_dependencies; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.subtask_dependencies (
    id integer NOT NULL,
    subtask_id text NOT NULL,
    depends_on_subtask_id text NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    CONSTRAINT subtask_dependencies_check CHECK ((subtask_id <> depends_on_subtask_id))
);


--
-- Name: TABLE subtask_dependencies; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.subtask_dependencies IS 'DAG of subtask execution order. subtask_id depends on depends_on_subtask_id.';


--
-- Name: subtask_dependencies_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.subtask_dependencies_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: subtask_dependencies_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.subtask_dependencies_id_seq OWNED BY public.subtask_dependencies.id;


--
-- Name: subtask_summaries; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.subtask_summaries (
    id integer NOT NULL,
    subtask_id text NOT NULL,
    summary text NOT NULL,
    files_modified jsonb DEFAULT '[]'::jsonb,
    decisions_made jsonb DEFAULT '[]'::jsonb,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: TABLE subtask_summaries; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.subtask_summaries IS 'Handoff context for subtask-to-subtask transitions. Enables fresh context per subtask.';


--
-- Name: COLUMN subtask_summaries.subtask_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.subtask_summaries.subtask_id IS 'Reference to task_subtasks.id (e.g., "task-abc123-1.1")';


--
-- Name: COLUMN subtask_summaries.summary; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.subtask_summaries.summary IS 'Structured summary of work done, key decisions, and gotchas discovered';


--
-- Name: COLUMN subtask_summaries.files_modified; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.subtask_summaries.files_modified IS 'Array of file paths modified during this subtask';


--
-- Name: COLUMN subtask_summaries.decisions_made; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.subtask_summaries.decisions_made IS 'Array of key decisions made during execution';


--
-- Name: subtask_summaries_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.subtask_summaries_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: subtask_summaries_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.subtask_summaries_id_seq OWNED BY public.subtask_summaries.id;


--
-- Name: task_dependencies; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.task_dependencies (
    id integer NOT NULL,
    task_id text NOT NULL,
    depends_on_task_id text NOT NULL,
    dependency_type character varying(20) NOT NULL,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: TABLE task_dependencies; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.task_dependencies IS 'Dependency relationships between tasks';


--
-- Name: COLUMN task_dependencies.dependency_type; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.task_dependencies.dependency_type IS 'Type: blocks (must complete first), discovered-from (found during work)';


--
-- Name: task_dependencies_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.task_dependencies_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: task_dependencies_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.task_dependencies_id_seq OWNED BY public.task_dependencies.id;


--
-- Name: task_id_sequence; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.task_id_sequence
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: task_labels; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.task_labels (
    task_id text NOT NULL,
    label text NOT NULL,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: TABLE task_labels; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.task_labels IS 'Normalized storage for task labels. Replaces tasks.labels TEXT[].';


--
-- Name: task_spirit; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.task_spirit (
    task_id text NOT NULL,
    objective text NOT NULL,
    spirit_anti text,
    decisions jsonb DEFAULT '[]'::jsonb,
    constraints jsonb DEFAULT '[]'::jsonb,
    done_when jsonb DEFAULT '[]'::jsonb,
    context jsonb DEFAULT '{}'::jsonb,
    plan_status character varying(20) DEFAULT 'draft'::character varying,
    plan_approved_at timestamp with time zone,
    plan_approved_by text,
    plan_history jsonb DEFAULT '[]'::jsonb,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    complexity character varying(20),
    CONSTRAINT task_spirit_complexity_check CHECK (((complexity)::text = ANY (ARRAY[('SIMPLE'::character varying)::text, ('STANDARD'::character varying)::text, ('COMPLEX'::character varying)::text]))),
    CONSTRAINT task_spirit_plan_status_check CHECK (((plan_status)::text = ANY (ARRAY[('draft'::character varying)::text, ('pending_review'::character varying)::text, ('approved'::character varying)::text, ('rejected'::character varying)::text])))
);


--
-- Name: TABLE task_spirit; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.task_spirit IS 'Agent guidance and plan approval workflow. 1:1 with tasks.';


--
-- Name: COLUMN task_spirit.objective; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.task_spirit.objective IS 'What the task aims to achieve (from plan.json)';


--
-- Name: COLUMN task_spirit.spirit_anti; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.task_spirit.spirit_anti IS 'What to avoid during implementation (anti-patterns)';


--
-- Name: COLUMN task_spirit.decisions; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.task_spirit.decisions IS 'JSONB array of architectural/design decisions';


--
-- Name: COLUMN task_spirit.constraints; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.task_spirit.constraints IS 'JSONB array of implementation constraints';


--
-- Name: COLUMN task_spirit.done_when; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.task_spirit.done_when IS 'JSONB array of completion criteria';


--
-- Name: COLUMN task_spirit.context; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.task_spirit.context IS 'JSONB blob for plan.json context field (round-trip preservation)';


--
-- Name: COLUMN task_spirit.plan_status; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.task_spirit.plan_status IS 'draft|pending_review|approved|rejected - gates execution';


--
-- Name: COLUMN task_spirit.plan_history; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.task_spirit.plan_history IS 'JSONB array of {status, timestamp, actor, notes} transitions';


--
-- Name: task_subtask_steps; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.task_subtask_steps (
    id integer NOT NULL,
    subtask_id text NOT NULL,
    step_number integer NOT NULL,
    description text NOT NULL,
    passes boolean DEFAULT false,
    passed_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now(),
    spec jsonb,
    status character varying(20) DEFAULT 'pending'::character varying,
    fix_step_number integer,
    CONSTRAINT task_subtask_steps_status_check CHECK (((status)::text = ANY (ARRAY[('pending'::character varying)::text, ('passed'::character varying)::text, ('failed'::character varying)::text, ('plan_defect'::character varying)::text])))
);


--
-- Name: TABLE task_subtask_steps; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.task_subtask_steps IS 'Normalized step storage for subtasks (replaced task_subtasks.steps JSONB)';


--
-- Name: COLUMN task_subtask_steps.step_number; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.task_subtask_steps.step_number IS '1-indexed step number within the subtask';


--
-- Name: COLUMN task_subtask_steps.passes; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.task_subtask_steps.passes IS 'True when step has been completed and verified';


--
-- Name: COLUMN task_subtask_steps.passed_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.task_subtask_steps.passed_at IS 'Timestamp when step was marked as passing';


--
-- Name: COLUMN task_subtask_steps.spec; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.task_subtask_steps.spec IS 'JSONB for step implementation specs: API details, file operations, prompts, etc.';


--
-- Name: COLUMN task_subtask_steps.status; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.task_subtask_steps.status IS 'Step status: pending, passed, failed, or plan_defect (verification was wrong)';


--
-- Name: COLUMN task_subtask_steps.fix_step_number; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.task_subtask_steps.fix_step_number IS 'For plan_defect status: the step number within the same subtask that provides correct verification';


--
-- Name: task_subtask_steps_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.task_subtask_steps_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: task_subtask_steps_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.task_subtask_steps_id_seq OWNED BY public.task_subtask_steps.id;


--
-- Name: task_subtasks; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.task_subtasks (
    id text NOT NULL,
    task_id text NOT NULL,
    subtask_id text NOT NULL,
    phase text,
    description text NOT NULL,
    passes boolean DEFAULT false,
    passed_at timestamp with time zone,
    display_order integer NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    attempt_count integer DEFAULT 0,
    last_attempt_at timestamp with time zone,
    citations_acknowledged_at timestamp with time zone,
    subtask_type text
);


--
-- Name: TABLE task_subtasks; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.task_subtasks IS 'Normalized storage for task implementation subtasks. Each subtask has ordered steps and pass/fail tracking.';


--
-- Name: COLUMN task_subtasks.subtask_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.task_subtasks.subtask_id IS 'Hierarchical ID like "1.1", "2.3" representing phase.task order';


--
-- Name: COLUMN task_subtasks.phase; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.task_subtasks.phase IS 'Implementation phase: research, database, backend, frontend, testing';


--
-- Name: COLUMN task_subtasks.citations_acknowledged_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.task_subtasks.citations_acknowledged_at IS 'When agent acknowledged memory usage (cited memories or confirmed none needed)';


--
-- Name: tasks; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.tasks (
    id text NOT NULL,
    project_id text NOT NULL,
    title text NOT NULL,
    description text,
    status text DEFAULT 'pending'::text,
    error_message text,
    branch_name text,
    commits text[] DEFAULT '{}'::text[],
    total_sessions integer DEFAULT 0,
    total_tokens_used integer DEFAULT 0,
    created_at timestamp with time zone DEFAULT now(),
    started_at timestamp with time zone,
    completed_at timestamp with time zone,
    priority integer DEFAULT 2,
    task_type character varying(20) DEFAULT 'task'::character varying,
    parent_task_id text,
    capability_id integer,
    feature_id integer,
    claimed_by text,
    claimed_at timestamp with time zone,
    lock_expires_at timestamp with time zone,
    tier integer DEFAULT 2,
    pre_merge_sha text,
    review_result jsonb,
    current_phase text DEFAULT 'plan'::text,
    verification_result jsonb,
    raw_request text,
    enrichment_status text DEFAULT 'none'::text,
    enriched_by text,
    enriched_at timestamp with time zone,
    complexity character varying(20),
    autonomous boolean DEFAULT false,
    labels text[] DEFAULT '{}'::text[],
    updated_at timestamp with time zone DEFAULT now(),
    agent_override character varying(50),
    agent_hub_session_ids text[] DEFAULT '{}'::text[],
    ai_review boolean DEFAULT true NOT NULL,
    conflict_info jsonb,
    merge_sha text,
    execution_mode character varying(20) DEFAULT 'manual'::character varying NOT NULL,
    CONSTRAINT ck_tasks_execution_mode CHECK (((execution_mode)::text = ANY ((ARRAY['manual'::character varying, 'autonomous'::character varying, 'manual_only'::character varying])::text[]))),
    CONSTRAINT tasks_complexity_check CHECK (((complexity)::text = ANY (ARRAY[('SIMPLE'::character varying)::text, ('STANDARD'::character varying)::text, ('COMPLEX'::character varying)::text]))),
    CONSTRAINT tasks_enrichment_status_check CHECK ((enrichment_status = ANY (ARRAY['none'::text, 'draft'::text, 'enriching'::text, 'review'::text, 'discussing'::text, 'accepted'::text, 'failed'::text]))),
    CONSTRAINT tasks_status_check CHECK ((status = ANY (ARRAY['pending'::text, 'queue'::text, 'running'::text, 'paused'::text, 'failed'::text, 'blocked'::text, 'ai_reviewing'::text, 'completed'::text, 'cancelled'::text, 'abandoned'::text, 'conflicted'::text]))),
    CONSTRAINT tasks_task_type_check CHECK (((task_type)::text = ANY (ARRAY[('feature'::character varying)::text, ('bug'::character varying)::text, ('task'::character varying)::text, ('refactor'::character varying)::text, ('debt'::character varying)::text, ('regression'::character varying)::text])))
);


--
-- Name: COLUMN tasks.status; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tasks.status IS 'Task status: pending, queue, ready, running, paused, blocked, pr_created, ai_reviewing, human_review, needs_review, human_reviewing, completed, cancelled, failed';


--
-- Name: COLUMN tasks.priority; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tasks.priority IS 'Priority 0-4 scale: 0=critical, 1=high, 2=medium (default), 3=low, 4=backlog';


--
-- Name: COLUMN tasks.task_type; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tasks.task_type IS 'Task type: feature, bug, task, refactor, debt, regression';


--
-- Name: COLUMN tasks.parent_task_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tasks.parent_task_id IS 'Parent task ID for hierarchical subtasks';


--
-- Name: COLUMN tasks.current_phase; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tasks.current_phase IS 'Current phase of task execution';


--
-- Name: COLUMN tasks.verification_result; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tasks.verification_result IS 'Result of last verification run';


--
-- Name: COLUMN tasks.raw_request; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tasks.raw_request IS 'Original user input before AI enrichment';


--
-- Name: COLUMN tasks.enrichment_status; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tasks.enrichment_status IS 'Workflow state: none, draft, enriching, review, discussing, accepted, failed';


--
-- Name: COLUMN tasks.enriched_by; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tasks.enriched_by IS 'AI model that performed enrichment (e.g., claude-opus-4.5)';


--
-- Name: COLUMN tasks.enriched_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tasks.enriched_at IS 'Timestamp when enrichment completed';


--
-- Name: COLUMN tasks.labels; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tasks.labels IS 'Array of labels: complexity:small|medium|large, domains:backend|frontend|database';


--
-- Name: COLUMN tasks.agent_override; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tasks.agent_override IS 'Manual override of agent slug for task execution. If set, uses this agent instead of task_type default.';


--
-- Name: taskset_id_sequence; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.taskset_id_sequence
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: aterm_alembic_version; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.aterm_alembic_version (
    version_num character varying(32) NOT NULL
);


--
-- Name: aterm_maintenance_runs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.aterm_maintenance_runs (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    reason character varying(32) NOT NULL,
    status character varying(16) NOT NULL,
    started_at timestamp with time zone DEFAULT now() NOT NULL,
    completed_at timestamp with time zone,
    duration_ms double precision,
    reconciliation_purged integer DEFAULT 0 NOT NULL,
    reconciliation_orphans_killed integer DEFAULT 0 NOT NULL,
    upload_scanned_files integer DEFAULT 0 NOT NULL,
    upload_deleted_files integer DEFAULT 0 NOT NULL,
    upload_pruned_directories integer DEFAULT 0 NOT NULL,
    upload_errors integer DEFAULT 0 NOT NULL,
    orphaned_project_settings_deleted integer DEFAULT 0 NOT NULL,
    project_count integer DEFAULT 0 NOT NULL,
    default_agent_tool_slug character varying(50),
    error text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT aterm_maintenance_runs_status_check CHECK (((status)::text = ANY ((ARRAY['running'::character varying, 'success'::character varying, 'skipped'::character varying, 'failed'::character varying])::text[])))
);


--
-- Name: aterm_panes; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.aterm_panes (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    pane_type character varying(10) NOT NULL,
    project_id character varying(64),
    pane_order integer DEFAULT 0 NOT NULL,
    pane_name character varying(255) NOT NULL,
    active_mode character varying(16) DEFAULT 'shell'::character varying NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    width_percent double precision DEFAULT 100.0,
    height_percent double precision DEFAULT 100.0,
    grid_row integer DEFAULT 0,
    grid_col integer DEFAULT 0,
    CONSTRAINT chk_project_pane_id CHECK (((((pane_type)::text = 'adhoc'::text) AND (project_id IS NULL)) OR (((pane_type)::text = 'project'::text) AND (project_id IS NOT NULL)))),
    CONSTRAINT aterm_panes_pane_type_check CHECK (((pane_type)::text = ANY (ARRAY[('project'::character varying)::text, ('adhoc'::character varying)::text])))
);


--
-- Name: aterm_project_settings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.aterm_project_settings (
    project_id character varying(64) NOT NULL,
    enabled boolean DEFAULT false NOT NULL,
    display_order integer DEFAULT 0 NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    active_mode character varying(16) DEFAULT 'shell'::character varying
);


--
-- Name: TABLE aterm_project_settings; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.aterm_project_settings IS 'A-Term settings per SummitFlow project';


--
-- Name: aterm_sessions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.aterm_sessions (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    name text NOT NULL,
    user_id text,
    project_id text,
    working_dir text,
    display_order integer DEFAULT 0 NOT NULL,
    is_alive boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    last_accessed_at timestamp with time zone DEFAULT now(),
    last_claude_session character varying(255),
    mode character varying(16) DEFAULT 'shell'::character varying,
    claude_state character varying(16) DEFAULT 'not_started'::character varying,
    session_number integer DEFAULT 1,
    pane_id uuid,
    CONSTRAINT aterm_sessions_claude_state_check CHECK (((claude_state)::text = ANY (ARRAY[('not_started'::character varying)::text, ('starting'::character varying)::text, ('running'::character varying)::text, ('stopped'::character varying)::text, ('error'::character varying)::text])))
);


--
-- Name: user_prompts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.user_prompts (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    project_id text NOT NULL,
    session_id text NOT NULL,
    prompt_number integer NOT NULL,
    prompt_text text NOT NULL,
    embedding public.vector(768),
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: TABLE user_prompts; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.user_prompts IS 'User prompts captured for semantic search and context';


--
-- Name: COLUMN user_prompts.prompt_number; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.user_prompts.prompt_number IS 'Sequential prompt number within a session';


--
-- Name: COLUMN user_prompts.embedding; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.user_prompts.embedding IS 'Vector embedding (768 dims) for semantic search';


--
-- Name: agent_sessions id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_sessions ALTER COLUMN id SET DEFAULT nextval('public.agent_sessions_id_seq'::regclass);


--
-- Name: artifacts id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.artifacts ALTER COLUMN id SET DEFAULT nextval('public.artifacts_id_seq'::regclass);


--
-- Name: design_asset_exports id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.design_asset_exports ALTER COLUMN id SET DEFAULT nextval('public.design_asset_exports_id_seq'::regclass);


--
-- Name: design_assets id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.design_assets ALTER COLUMN id SET DEFAULT nextval('public.design_assets_id_seq'::regclass);


--
-- Name: design_rules id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.design_rules ALTER COLUMN id SET DEFAULT nextval('public.design_rules_id_seq'::regclass);


--
-- Name: design_standards id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.design_standards ALTER COLUMN id SET DEFAULT nextval('public.design_standards_id_seq'::regclass);


--
-- Name: explorer_entries id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.explorer_entries ALTER COLUMN id SET DEFAULT nextval('public.explorer_entries_id_seq'::regclass);


--
-- Name: explorer_relationships id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.explorer_relationships ALTER COLUMN id SET DEFAULT nextval('public.explorer_relationships_id_seq'::regclass);


--
-- Name: explorer_sub_elements id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.explorer_sub_elements ALTER COLUMN id SET DEFAULT nextval('public.explorer_sub_elements_id_seq'::regclass);


--
-- Name: explorer_symbols id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.explorer_symbols ALTER COLUMN id SET DEFAULT nextval('public.explorer_symbols_id_seq'::regclass);


--
-- Name: maintenance_runs id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.maintenance_runs ALTER COLUMN id SET DEFAULT nextval('public.maintenance_runs_id_seq'::regclass);


--
-- Name: mockups id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.mockups ALTER COLUMN id SET DEFAULT nextval('public.mockups_id_seq'::regclass);


--
-- Name: qa_issues id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.qa_issues ALTER COLUMN id SET DEFAULT nextval('public.qa_issues_id_seq'::regclass);


--
-- Name: quality_check_results id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quality_check_results ALTER COLUMN id SET DEFAULT nextval('public.quality_check_results_id_seq'::regclass);


--
-- Name: refactor_sessions id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.refactor_sessions ALTER COLUMN id SET DEFAULT nextval('public.refactor_sessions_id_seq'::regclass);


--
-- Name: scan_history id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scan_history ALTER COLUMN id SET DEFAULT nextval('public.scan_history_id_seq'::regclass);


--
-- Name: sitemap_entries id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sitemap_entries ALTER COLUMN id SET DEFAULT nextval('public.sitemap_entries_id_seq'::regclass);


--
-- Name: subtask_dependencies id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.subtask_dependencies ALTER COLUMN id SET DEFAULT nextval('public.subtask_dependencies_id_seq'::regclass);


--
-- Name: subtask_summaries id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.subtask_summaries ALTER COLUMN id SET DEFAULT nextval('public.subtask_summaries_id_seq'::regclass);


--
-- Name: task_dependencies id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_dependencies ALTER COLUMN id SET DEFAULT nextval('public.task_dependencies_id_seq'::regclass);


--
-- Name: task_subtask_steps id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_subtask_steps ALTER COLUMN id SET DEFAULT nextval('public.task_subtask_steps_id_seq'::regclass);


--
-- Name: agent_sessions agent_sessions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_sessions
    ADD CONSTRAINT agent_sessions_pkey PRIMARY KEY (id);


--
-- Name: agent_sessions agent_sessions_project_id_session_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_sessions
    ADD CONSTRAINT agent_sessions_project_id_session_id_key UNIQUE (project_id, session_id);


--
-- Name: agent_tools agent_tools_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_tools
    ADD CONSTRAINT agent_tools_pkey PRIMARY KEY (id);


--
-- Name: agent_tools agent_tools_slug_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_tools
    ADD CONSTRAINT agent_tools_slug_key UNIQUE (slug);


--
-- Name: alembic_version alembic_version_pkc; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alembic_version
    ADD CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num);


--
-- Name: artifacts artifacts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.artifacts
    ADD CONSTRAINT artifacts_pkey PRIMARY KEY (id);


--
-- Name: artifacts artifacts_project_id_artifact_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.artifacts
    ADD CONSTRAINT artifacts_project_id_artifact_id_key UNIQUE (project_id, artifact_id);


--
-- Name: backup_sources backup_sources_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.backup_sources
    ADD CONSTRAINT backup_sources_pkey PRIMARY KEY (id);


--
-- Name: backups backups_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.backups
    ADD CONSTRAINT backups_pkey PRIMARY KEY (id);


--
-- Name: design_asset_exports design_asset_exports_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.design_asset_exports
    ADD CONSTRAINT design_asset_exports_pkey PRIMARY KEY (id);


--
-- Name: design_assets design_assets_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.design_assets
    ADD CONSTRAINT design_assets_pkey PRIMARY KEY (id);


--
-- Name: design_rules design_rules_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.design_rules
    ADD CONSTRAINT design_rules_pkey PRIMARY KEY (id);


--
-- Name: design_rules design_rules_standard_id_rule_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.design_rules
    ADD CONSTRAINT design_rules_standard_id_rule_id_key UNIQUE (standard_id, rule_id);


--
-- Name: design_standards design_standards_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.design_standards
    ADD CONSTRAINT design_standards_pkey PRIMARY KEY (id);


--
-- Name: design_standards design_standards_project_id_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.design_standards
    ADD CONSTRAINT design_standards_project_id_name_key UNIQUE (project_id, name);


--
-- Name: events events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.events
    ADD CONSTRAINT events_pkey PRIMARY KEY (id);


--
-- Name: explorer_entries explorer_entries_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.explorer_entries
    ADD CONSTRAINT explorer_entries_pkey PRIMARY KEY (id);


--
-- Name: explorer_entries explorer_entries_project_entry_path_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.explorer_entries
    ADD CONSTRAINT explorer_entries_project_entry_path_key UNIQUE (project_id, entry_type, path);


--
-- Name: explorer_entries explorer_entries_project_id_entry_type_path_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.explorer_entries
    ADD CONSTRAINT explorer_entries_project_id_entry_type_path_key UNIQUE (project_id, entry_type, path);


--
-- Name: explorer_relationships explorer_relationships_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.explorer_relationships
    ADD CONSTRAINT explorer_relationships_pkey PRIMARY KEY (id);


--
-- Name: explorer_relationships explorer_relationships_project_id_source_type_source_path_t_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.explorer_relationships
    ADD CONSTRAINT explorer_relationships_project_id_source_type_source_path_t_key UNIQUE (project_id, source_type, source_path, target_type, target_path, relationship);


--
-- Name: explorer_sub_elements explorer_sub_elements_explorer_entry_id_selector_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.explorer_sub_elements
    ADD CONSTRAINT explorer_sub_elements_explorer_entry_id_selector_key UNIQUE (explorer_entry_id, selector);


--
-- Name: explorer_sub_elements explorer_sub_elements_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.explorer_sub_elements
    ADD CONSTRAINT explorer_sub_elements_pkey PRIMARY KEY (id);


--
-- Name: explorer_symbols explorer_symbols_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.explorer_symbols
    ADD CONSTRAINT explorer_symbols_pkey PRIMARY KEY (id);


--
-- Name: explorer_symbols explorer_symbols_project_id_symbol_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.explorer_symbols
    ADD CONSTRAINT explorer_symbols_project_id_symbol_id_key UNIQUE (project_id, symbol_id);


--
-- Name: maintenance_runs maintenance_runs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.maintenance_runs
    ADD CONSTRAINT maintenance_runs_pkey PRIMARY KEY (id);


--
-- Name: mockups mockups_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.mockups
    ADD CONSTRAINT mockups_pkey PRIMARY KEY (id);


--
-- Name: mockups mockups_project_mockup_unique; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.mockups
    ADD CONSTRAINT mockups_project_mockup_unique UNIQUE (project_id, mockup_id);


--
-- Name: notifications notifications_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notifications
    ADD CONSTRAINT notifications_pkey PRIMARY KEY (id);


--
-- Name: projects projects_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.projects
    ADD CONSTRAINT projects_pkey PRIMARY KEY (id);


--
-- Name: qa_issues qa_issues_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.qa_issues
    ADD CONSTRAINT qa_issues_pkey PRIMARY KEY (id);


--
-- Name: quality_check_results quality_check_results_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quality_check_results
    ADD CONSTRAINT quality_check_results_pkey PRIMARY KEY (id);


--
-- Name: refactor_sessions refactor_sessions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.refactor_sessions
    ADD CONSTRAINT refactor_sessions_pkey PRIMARY KEY (id);


--
-- Name: refactor_sessions refactor_sessions_project_id_task_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.refactor_sessions
    ADD CONSTRAINT refactor_sessions_project_id_task_id_key UNIQUE (project_id, task_id);


--
-- Name: scan_history scan_history_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scan_history
    ADD CONSTRAINT scan_history_pkey PRIMARY KEY (id);


--
-- Name: scan_states scan_states_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scan_states
    ADD CONSTRAINT scan_states_pkey PRIMARY KEY (project_id);


--
-- Name: sitemap_entries sitemap_entries_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sitemap_entries
    ADD CONSTRAINT sitemap_entries_pkey PRIMARY KEY (id);


--
-- Name: sitemap_entries sitemap_entries_project_id_port_path_method_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sitemap_entries
    ADD CONSTRAINT sitemap_entries_project_id_port_path_method_key UNIQUE (project_id, port, path, method);


--
-- Name: storage_backends storage_backends_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.storage_backends
    ADD CONSTRAINT storage_backends_pkey PRIMARY KEY (id);


--
-- Name: subtask_citations subtask_citations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.subtask_citations
    ADD CONSTRAINT subtask_citations_pkey PRIMARY KEY (id);


--
-- Name: subtask_dependencies subtask_dependencies_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.subtask_dependencies
    ADD CONSTRAINT subtask_dependencies_pkey PRIMARY KEY (id);


--
-- Name: subtask_dependencies subtask_dependencies_subtask_depends_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.subtask_dependencies
    ADD CONSTRAINT subtask_dependencies_subtask_depends_key UNIQUE (subtask_id, depends_on_subtask_id);


--
-- Name: subtask_dependencies subtask_dependencies_subtask_id_depends_on_subtask_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.subtask_dependencies
    ADD CONSTRAINT subtask_dependencies_subtask_id_depends_on_subtask_id_key UNIQUE (subtask_id, depends_on_subtask_id);


--
-- Name: subtask_summaries subtask_summaries_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.subtask_summaries
    ADD CONSTRAINT subtask_summaries_pkey PRIMARY KEY (id);


--
-- Name: subtask_summaries subtask_summaries_subtask_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.subtask_summaries
    ADD CONSTRAINT subtask_summaries_subtask_id_key UNIQUE (subtask_id);


--
-- Name: subtask_summaries subtask_summaries_unique_subtask; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.subtask_summaries
    ADD CONSTRAINT subtask_summaries_unique_subtask UNIQUE (subtask_id);


--
-- Name: task_dependencies task_dependencies_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_dependencies
    ADD CONSTRAINT task_dependencies_pkey PRIMARY KEY (id);


--
-- Name: task_dependencies task_dependencies_task_depends_type_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_dependencies
    ADD CONSTRAINT task_dependencies_task_depends_type_key UNIQUE (task_id, depends_on_task_id, dependency_type);


--
-- Name: task_dependencies task_dependencies_task_id_depends_on_task_id_dependency_typ_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_dependencies
    ADD CONSTRAINT task_dependencies_task_id_depends_on_task_id_dependency_typ_key UNIQUE (task_id, depends_on_task_id, dependency_type);


--
-- Name: task_labels task_labels_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_labels
    ADD CONSTRAINT task_labels_pkey PRIMARY KEY (task_id, label);


--
-- Name: task_spirit task_spirit_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_spirit
    ADD CONSTRAINT task_spirit_pkey PRIMARY KEY (task_id);


--
-- Name: task_subtask_steps task_subtask_steps_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_subtask_steps
    ADD CONSTRAINT task_subtask_steps_pkey PRIMARY KEY (id);


--
-- Name: task_subtask_steps task_subtask_steps_subtask_step_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_subtask_steps
    ADD CONSTRAINT task_subtask_steps_subtask_step_key UNIQUE (subtask_id, step_number);


--
-- Name: task_subtask_steps task_subtask_steps_unique; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_subtask_steps
    ADD CONSTRAINT task_subtask_steps_unique UNIQUE (subtask_id, step_number);


--
-- Name: task_subtasks task_subtasks_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_subtasks
    ADD CONSTRAINT task_subtasks_pkey PRIMARY KEY (id);


--
-- Name: task_subtasks task_subtasks_unique_subtask; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_subtasks
    ADD CONSTRAINT task_subtasks_unique_subtask UNIQUE (task_id, subtask_id);


--
-- Name: tasks tasks_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tasks
    ADD CONSTRAINT tasks_pkey PRIMARY KEY (id);


--
-- Name: aterm_alembic_version aterm_alembic_version_pkc; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.aterm_alembic_version
    ADD CONSTRAINT aterm_alembic_version_pkc PRIMARY KEY (version_num);


--
-- Name: aterm_maintenance_runs aterm_maintenance_runs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.aterm_maintenance_runs
    ADD CONSTRAINT aterm_maintenance_runs_pkey PRIMARY KEY (id);


--
-- Name: aterm_panes aterm_panes_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.aterm_panes
    ADD CONSTRAINT aterm_panes_pkey PRIMARY KEY (id);


--
-- Name: aterm_project_settings aterm_project_settings_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.aterm_project_settings
    ADD CONSTRAINT aterm_project_settings_pkey PRIMARY KEY (project_id);


--
-- Name: aterm_sessions aterm_sessions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.aterm_sessions
    ADD CONSTRAINT aterm_sessions_pkey PRIMARY KEY (id);


--
-- Name: design_asset_exports uq_design_asset_exports; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.design_asset_exports
    ADD CONSTRAINT uq_design_asset_exports UNIQUE (asset_id, export_id);


--
-- Name: design_assets uq_design_assets_project_asset; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.design_assets
    ADD CONSTRAINT uq_design_assets_project_asset UNIQUE (project_id, asset_id);


--
-- Name: user_prompts user_prompts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_prompts
    ADD CONSTRAINT user_prompts_pkey PRIMARY KEY (id);


--
-- Name: user_prompts user_prompts_session_id_prompt_number_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_prompts
    ADD CONSTRAINT user_prompts_session_id_prompt_number_key UNIQUE (session_id, prompt_number);


--
-- Name: idx_agent_sessions_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_agent_sessions_created ON public.agent_sessions USING btree (created_at DESC);


--
-- Name: idx_agent_sessions_project; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_agent_sessions_project ON public.agent_sessions USING btree (project_id);


--
-- Name: idx_agent_sessions_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_agent_sessions_status ON public.agent_sessions USING btree (status);


--
-- Name: idx_agent_tools_enabled; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_agent_tools_enabled ON public.agent_tools USING btree (enabled) WHERE (enabled = true);


--
-- Name: idx_artifacts_criterion; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_artifacts_criterion ON public.artifacts USING btree (criterion_id);


--
-- Name: idx_artifacts_current; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_artifacts_current ON public.artifacts USING btree (is_current) WHERE (is_current = true);


--
-- Name: idx_artifacts_feature; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_artifacts_feature ON public.artifacts USING btree (feature_id);


--
-- Name: idx_artifacts_project; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_artifacts_project ON public.artifacts USING btree (project_id);


--
-- Name: idx_artifacts_quality; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_artifacts_quality ON public.artifacts USING btree (quality_status);


--
-- Name: idx_backup_sources_enabled_next_run; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_backup_sources_enabled_next_run ON public.backup_sources USING btree (enabled, next_run_at);


--
-- Name: idx_backups_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_backups_created_at ON public.backups USING btree (created_at DESC);


--
-- Name: idx_backups_project; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_backups_project ON public.backups USING btree (project_id);


--
-- Name: idx_backups_project_event_time; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_backups_project_event_time ON public.backups USING btree (project_id, COALESCE(completed_at, created_at) DESC) WHERE ((status)::text = ANY ((ARRAY['completed'::character varying, 'failed'::character varying])::text[]));


--
-- Name: idx_backups_project_status_completed; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_backups_project_status_completed ON public.backups USING btree (project_id, status, completed_at DESC);


--
-- Name: idx_backups_source; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_backups_source ON public.backups USING btree (source_id);


--
-- Name: idx_backups_source_status_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_backups_source_status_created ON public.backups USING btree (source_id, status, created_at DESC);


--
-- Name: idx_backups_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_backups_status ON public.backups USING btree (status);


--
-- Name: idx_design_asset_exports_asset; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_design_asset_exports_asset ON public.design_asset_exports USING btree (asset_id);


--
-- Name: idx_design_assets_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_design_assets_created ON public.design_assets USING btree (project_id, created_at);


--
-- Name: idx_design_assets_project; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_design_assets_project ON public.design_assets USING btree (project_id);


--
-- Name: idx_design_assets_source; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_design_assets_source ON public.design_assets USING btree (source_asset_id);


--
-- Name: idx_design_assets_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_design_assets_status ON public.design_assets USING btree (project_id, status);


--
-- Name: idx_design_assets_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_design_assets_type ON public.design_assets USING btree (project_id, asset_type);


--
-- Name: idx_design_rules_category; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_design_rules_category ON public.design_rules USING btree (category);


--
-- Name: idx_design_rules_standard; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_design_rules_standard ON public.design_rules USING btree (standard_id);


--
-- Name: idx_design_standards_base; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_design_standards_base ON public.design_standards USING btree (is_base) WHERE (is_base = true);


--
-- Name: idx_design_standards_project; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_design_standards_project ON public.design_standards USING btree (project_id);


--
-- Name: idx_events_level; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_events_level ON public.events USING btree (level);


--
-- Name: idx_events_parent_span; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_events_parent_span ON public.events USING btree (parent_span_id) WHERE (parent_span_id IS NOT NULL);


--
-- Name: idx_events_project_timestamp; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_events_project_timestamp ON public.events USING btree (project_id, "timestamp" DESC);


--
-- Name: idx_events_trace_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_events_trace_id ON public.events USING btree (trace_id);


--
-- Name: idx_events_trace_timestamp; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_events_trace_timestamp ON public.events USING btree (trace_id, "timestamp");


--
-- Name: idx_events_visibility; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_events_visibility ON public.events USING btree (visibility);


--
-- Name: idx_explorer_entries_evidence; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_explorer_entries_evidence ON public.explorer_entries USING btree (evidence_count) WHERE (evidence_count > 0);


--
-- Name: idx_explorer_entries_health; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_explorer_entries_health ON public.explorer_entries USING btree (project_id, health_status);


--
-- Name: idx_explorer_entries_metadata; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_explorer_entries_metadata ON public.explorer_entries USING gin (metadata);


--
-- Name: idx_explorer_entries_project_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_explorer_entries_project_type ON public.explorer_entries USING btree (project_id, entry_type);


--
-- Name: idx_explorer_rel_source; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_explorer_rel_source ON public.explorer_relationships USING btree (project_id, source_type, source_path);


--
-- Name: idx_explorer_rel_target; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_explorer_rel_target ON public.explorer_relationships USING btree (project_id, target_type, target_path);


--
-- Name: idx_explorer_symbols_project_file; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_explorer_symbols_project_file ON public.explorer_symbols USING btree (project_id, file_path);


--
-- Name: idx_explorer_symbols_project_language_kind; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_explorer_symbols_project_language_kind ON public.explorer_symbols USING btree (project_id, language, kind);


--
-- Name: idx_maintenance_runs_status_started; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_maintenance_runs_status_started ON public.maintenance_runs USING btree (status, started_at DESC);


--
-- Name: idx_maintenance_runs_workflow_started; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_maintenance_runs_workflow_started ON public.maintenance_runs USING btree (workflow_name, started_at DESC);


--
-- Name: idx_mockups_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_mockups_created ON public.mockups USING btree (created_at DESC);


--
-- Name: idx_mockups_generator; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_mockups_generator ON public.mockups USING btree (generator);


--
-- Name: idx_mockups_page_path; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_mockups_page_path ON public.mockups USING btree (page_path);


--
-- Name: idx_mockups_parent; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_mockups_parent ON public.mockups USING btree (parent_mockup_id);


--
-- Name: idx_mockups_project; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_mockups_project ON public.mockups USING btree (project_id);


--
-- Name: idx_mockups_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_mockups_status ON public.mockups USING btree (status);


--
-- Name: idx_mockups_task; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_mockups_task ON public.mockups USING btree (task_id);


--
-- Name: idx_notification_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_notification_created ON public.notifications USING btree (created_at DESC);


--
-- Name: idx_notification_project; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_notification_project ON public.notifications USING btree (project_id);


--
-- Name: idx_notification_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_notification_status ON public.notifications USING btree (status);


--
-- Name: idx_notification_task; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_notification_task ON public.notifications USING btree (task_id);


--
-- Name: idx_notification_user_email; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_notification_user_email ON public.notifications USING btree (user_email);


--
-- Name: idx_notifications_project_status_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_notifications_project_status_created ON public.notifications USING btree (project_id, status, created_at DESC);


--
-- Name: idx_qa_issues_entry; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_qa_issues_entry ON public.qa_issues USING btree (entry_id) WHERE (entry_id IS NOT NULL);


--
-- Name: idx_qa_issues_file; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_qa_issues_file ON public.qa_issues USING btree (file_path) WHERE (file_path IS NOT NULL);


--
-- Name: idx_qa_issues_project_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_qa_issues_project_status ON public.qa_issues USING btree (project_id, status);


--
-- Name: idx_qa_issues_project_status_detected; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_qa_issues_project_status_detected ON public.qa_issues USING btree (project_id, status, last_detected_at DESC);


--
-- Name: idx_qa_issues_project_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_qa_issues_project_type ON public.qa_issues USING btree (project_id, issue_type);


--
-- Name: idx_qa_issues_task_link; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_qa_issues_task_link ON public.qa_issues USING btree (st_task_id) WHERE (st_task_id IS NOT NULL);


--
-- Name: idx_qa_issues_unique; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX idx_qa_issues_unique ON public.qa_issues USING btree (project_id, issue_type, file_path) WHERE ((file_path IS NOT NULL) AND ((status)::text = 'open'::text));


--
-- Name: idx_qcr_escalation_task_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_qcr_escalation_task_id ON public.quality_check_results USING btree (escalation_task_id) WHERE (escalation_task_id IS NOT NULL);


--
-- Name: idx_qcr_project_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_qcr_project_created ON public.quality_check_results USING btree (project_id, created_at DESC);


--
-- Name: idx_qcr_project_type_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_qcr_project_type_created ON public.quality_check_results USING btree (project_id, check_type, created_at DESC);


--
-- Name: idx_quality_check_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_quality_check_created ON public.quality_check_results USING btree (created_at DESC);


--
-- Name: idx_quality_check_project; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_quality_check_project ON public.quality_check_results USING btree (project_id);


--
-- Name: idx_quality_check_project_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_quality_check_project_type ON public.quality_check_results USING btree (project_id, check_type);


--
-- Name: idx_quality_check_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_quality_check_status ON public.quality_check_results USING btree (status);


--
-- Name: idx_quality_check_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_quality_check_type ON public.quality_check_results USING btree (check_type);


--
-- Name: idx_quality_check_unfixed; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_quality_check_unfixed ON public.quality_check_results USING btree (project_id, status) WHERE (((status)::text = 'fail'::text) AND (fixed_at IS NULL));


--
-- Name: idx_refactor_sessions_project; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_refactor_sessions_project ON public.refactor_sessions USING btree (project_id);


--
-- Name: idx_refactor_sessions_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_refactor_sessions_status ON public.refactor_sessions USING btree (status) WHERE ((status)::text = 'active'::text);


--
-- Name: idx_refactor_sessions_task; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_refactor_sessions_task ON public.refactor_sessions USING btree (task_id);


--
-- Name: idx_scan_history_project_started; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_scan_history_project_started ON public.scan_history USING btree (project_id, started_at DESC);


--
-- Name: idx_scan_history_project_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_scan_history_project_type ON public.scan_history USING btree (project_id, scan_type);


--
-- Name: idx_scan_history_started_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_scan_history_started_at ON public.scan_history USING btree (started_at DESC);


--
-- Name: idx_scan_history_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_scan_history_status ON public.scan_history USING btree (status) WHERE ((status)::text = 'running'::text);


--
-- Name: idx_scan_history_triggered_by; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_scan_history_triggered_by ON public.scan_history USING btree (triggered_by);


--
-- Name: idx_scan_history_unique; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX idx_scan_history_unique ON public.scan_history USING btree (project_id, started_at);


--
-- Name: idx_scan_states_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_scan_states_status ON public.scan_states USING btree (status);


--
-- Name: idx_sitemap_entry_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_sitemap_entry_type ON public.sitemap_entries USING btree (entry_type);


--
-- Name: idx_sitemap_health; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_sitemap_health ON public.sitemap_entries USING btree (health_status);


--
-- Name: idx_sitemap_last_checked; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_sitemap_last_checked ON public.sitemap_entries USING btree (last_checked_at);


--
-- Name: idx_sitemap_port; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_sitemap_port ON public.sitemap_entries USING btree (port);


--
-- Name: idx_sitemap_project; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_sitemap_project ON public.sitemap_entries USING btree (project_id);


--
-- Name: idx_sub_elements_entry; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_sub_elements_entry ON public.explorer_sub_elements USING btree (explorer_entry_id);


--
-- Name: idx_sub_elements_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_sub_elements_type ON public.explorer_sub_elements USING btree (element_type);


--
-- Name: idx_subtask_citations_episode; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_subtask_citations_episode ON public.subtask_citations USING btree (episode_uuid);


--
-- Name: idx_subtask_citations_rating; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_subtask_citations_rating ON public.subtask_citations USING btree (rating);


--
-- Name: idx_subtask_citations_subtask; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_subtask_citations_subtask ON public.subtask_citations USING btree (subtask_id);


--
-- Name: idx_subtask_deps_depends; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_subtask_deps_depends ON public.subtask_dependencies USING btree (depends_on_subtask_id);


--
-- Name: idx_subtask_deps_subtask; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_subtask_deps_subtask ON public.subtask_dependencies USING btree (subtask_id);


--
-- Name: idx_subtask_summaries_subtask_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_subtask_summaries_subtask_id ON public.subtask_summaries USING btree (subtask_id);


--
-- Name: idx_task_deps_depends; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_task_deps_depends ON public.task_dependencies USING btree (depends_on_task_id);


--
-- Name: idx_task_deps_task; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_task_deps_task ON public.task_dependencies USING btree (task_id);


--
-- Name: idx_task_labels_label; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_task_labels_label ON public.task_labels USING btree (label);


--
-- Name: idx_task_spirit_complexity; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_task_spirit_complexity ON public.task_spirit USING btree (complexity);


--
-- Name: idx_task_spirit_plan_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_task_spirit_plan_status ON public.task_spirit USING btree (plan_status);


--
-- Name: idx_task_subtask_steps_passes; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_task_subtask_steps_passes ON public.task_subtask_steps USING btree (passes);


--
-- Name: idx_task_subtask_steps_subtask_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_task_subtask_steps_subtask_id ON public.task_subtask_steps USING btree (subtask_id);


--
-- Name: idx_task_subtasks_attempts; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_task_subtasks_attempts ON public.task_subtasks USING btree (attempt_count DESC) WHERE (attempt_count > 0);


--
-- Name: idx_task_subtasks_passes; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_task_subtasks_passes ON public.task_subtasks USING btree (passes);


--
-- Name: idx_task_subtasks_phase; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_task_subtasks_phase ON public.task_subtasks USING btree (phase);


--
-- Name: idx_task_subtasks_task_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_task_subtasks_task_id ON public.task_subtasks USING btree (task_id);


--
-- Name: idx_task_subtasks_task_passes; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_task_subtasks_task_passes ON public.task_subtasks USING btree (task_id, passes);


--
-- Name: INDEX idx_task_subtasks_task_passes; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON INDEX public.idx_task_subtasks_task_passes IS 'Composite index for subtask lookups by task and completion status';


--
-- Name: idx_task_subtasks_updated; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_task_subtasks_updated ON public.task_subtasks USING btree (updated_at DESC);


--
-- Name: idx_tasks_capability; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_tasks_capability ON public.tasks USING btree (capability_id);


--
-- Name: idx_tasks_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_tasks_created ON public.tasks USING btree (created_at DESC);


--
-- Name: idx_tasks_enrichment_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_tasks_enrichment_status ON public.tasks USING btree (enrichment_status);


--
-- Name: idx_tasks_feature; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_tasks_feature ON public.tasks USING btree (feature_id);


--
-- Name: idx_tasks_parent; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_tasks_parent ON public.tasks USING btree (parent_task_id);


--
-- Name: idx_tasks_priority; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_tasks_priority ON public.tasks USING btree (priority);


--
-- Name: idx_tasks_project; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_tasks_project ON public.tasks USING btree (project_id);


--
-- Name: idx_tasks_project_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_tasks_project_created ON public.tasks USING btree (project_id, created_at DESC);


--
-- Name: INDEX idx_tasks_project_created; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON INDEX public.idx_tasks_project_created IS 'Composite index for project+created_at sort pattern';


--
-- Name: idx_tasks_project_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_tasks_project_status ON public.tasks USING btree (project_id, status);


--
-- Name: INDEX idx_tasks_project_status; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON INDEX public.idx_tasks_project_status IS 'Composite index for common project+status filter pattern';


--
-- Name: idx_tasks_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_tasks_status ON public.tasks USING btree (status);


--
-- Name: idx_tasks_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_tasks_type ON public.tasks USING btree (task_type);


--
-- Name: idx_tasks_updated; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_tasks_updated ON public.tasks USING btree (updated_at DESC);


--
-- Name: idx_aterm_maintenance_runs_started_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_aterm_maintenance_runs_started_at ON public.aterm_maintenance_runs USING btree (started_at DESC);


--
-- Name: idx_aterm_maintenance_runs_status_started_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_aterm_maintenance_runs_status_started_at ON public.aterm_maintenance_runs USING btree (status, started_at DESC);


--
-- Name: idx_aterm_panes_order; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_aterm_panes_order ON public.aterm_panes USING btree (pane_order);


--
-- Name: idx_aterm_panes_project_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_aterm_panes_project_id ON public.aterm_panes USING btree (project_id) WHERE (project_id IS NOT NULL);


--
-- Name: idx_aterm_project_settings_display_order; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_aterm_project_settings_display_order ON public.aterm_project_settings USING btree (display_order, project_id);


--
-- Name: idx_aterm_sessions_alive; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_aterm_sessions_alive ON public.aterm_sessions USING btree (is_alive);


--
-- Name: idx_aterm_sessions_dead_last_accessed; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_aterm_sessions_dead_last_accessed ON public.aterm_sessions USING btree (last_accessed_at) WHERE (is_alive = false);


--
-- Name: idx_aterm_sessions_display_order_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_aterm_sessions_display_order_created ON public.aterm_sessions USING btree (display_order, created_at);


--
-- Name: idx_aterm_sessions_pane_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_aterm_sessions_pane_id ON public.aterm_sessions USING btree (pane_id) WHERE (pane_id IS NOT NULL);


--
-- Name: idx_aterm_sessions_project; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_aterm_sessions_project ON public.aterm_sessions USING btree (project_id) WHERE (project_id IS NOT NULL);


--
-- Name: idx_aterm_sessions_project_mode_alive_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_aterm_sessions_project_mode_alive_created ON public.aterm_sessions USING btree (project_id, mode, is_alive, created_at DESC) WHERE (project_id IS NOT NULL);


--
-- Name: idx_aterm_sessions_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_aterm_sessions_user ON public.aterm_sessions USING btree (user_id);


--
-- Name: idx_tps_enabled; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_tps_enabled ON public.aterm_project_settings USING btree (enabled) WHERE (enabled = true);


--
-- Name: idx_user_prompts_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_user_prompts_created ON public.user_prompts USING btree (project_id, created_at DESC);


--
-- Name: idx_user_prompts_embedding; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_user_prompts_embedding ON public.user_prompts USING ivfflat (embedding public.vector_cosine_ops) WITH (lists='100');


--
-- Name: idx_user_prompts_project; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_user_prompts_project ON public.user_prompts USING btree (project_id);


--
-- Name: idx_user_prompts_session; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_user_prompts_session ON public.user_prompts USING btree (session_id);


--
-- Name: uq_agent_tools_single_default; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_agent_tools_single_default ON public.agent_tools USING btree (is_default) WHERE (is_default = true);


--
-- Name: subtask_dependencies check_subtask_dep_cycle; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER check_subtask_dep_cycle BEFORE INSERT OR UPDATE ON public.subtask_dependencies FOR EACH ROW EXECUTE FUNCTION public.check_subtask_dependency_cycle();


--
-- Name: task_subtasks enforce_steps_complete_before_subtask_pass; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER enforce_steps_complete_before_subtask_pass BEFORE UPDATE ON public.task_subtasks FOR EACH ROW EXECUTE FUNCTION public.enforce_steps_complete_before_subtask_pass();


--
-- Name: task_subtasks enforce_subtask_dependencies; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER enforce_subtask_dependencies BEFORE UPDATE ON public.task_subtasks FOR EACH ROW EXECUTE FUNCTION public.enforce_subtask_dependencies();


--
-- Name: task_spirit task_spirit_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER task_spirit_updated_at BEFORE UPDATE ON public.task_spirit FOR EACH ROW EXECUTE FUNCTION public.update_task_spirit_updated_at();


--
-- Name: mockups trigger_mockups_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trigger_mockups_updated_at BEFORE UPDATE ON public.mockups FOR EACH ROW EXECUTE FUNCTION public.update_mockups_updated_at();


--
-- Name: agent_sessions agent_sessions_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_sessions
    ADD CONSTRAINT agent_sessions_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE CASCADE;


--
-- Name: artifacts artifacts_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.artifacts
    ADD CONSTRAINT artifacts_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE CASCADE;


--
-- Name: backup_sources backup_sources_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.backup_sources
    ADD CONSTRAINT backup_sources_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE SET NULL;


--
-- Name: backup_sources backup_sources_storage_backend_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.backup_sources
    ADD CONSTRAINT backup_sources_storage_backend_id_fkey FOREIGN KEY (storage_backend_id) REFERENCES public.storage_backends(id);


--
-- Name: backups backups_source_fk; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.backups
    ADD CONSTRAINT backups_source_fk FOREIGN KEY (source_id) REFERENCES public.backup_sources(id) ON DELETE CASCADE;


--
-- Name: design_asset_exports design_asset_exports_asset_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.design_asset_exports
    ADD CONSTRAINT design_asset_exports_asset_id_fkey FOREIGN KEY (asset_id) REFERENCES public.design_assets(id) ON DELETE CASCADE;


--
-- Name: design_assets design_assets_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.design_assets
    ADD CONSTRAINT design_assets_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE CASCADE;


--
-- Name: design_assets design_assets_source_asset_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.design_assets
    ADD CONSTRAINT design_assets_source_asset_id_fkey FOREIGN KEY (source_asset_id) REFERENCES public.design_assets(id) ON DELETE SET NULL;


--
-- Name: design_rules design_rules_standard_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.design_rules
    ADD CONSTRAINT design_rules_standard_id_fkey FOREIGN KEY (standard_id) REFERENCES public.design_standards(id) ON DELETE CASCADE;


--
-- Name: design_standards design_standards_base_standard_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.design_standards
    ADD CONSTRAINT design_standards_base_standard_id_fkey FOREIGN KEY (base_standard_id) REFERENCES public.design_standards(id) ON DELETE SET NULL;


--
-- Name: design_standards design_standards_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.design_standards
    ADD CONSTRAINT design_standards_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE CASCADE;


--
-- Name: events events_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.events
    ADD CONSTRAINT events_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE CASCADE;


--
-- Name: explorer_entries explorer_entries_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.explorer_entries
    ADD CONSTRAINT explorer_entries_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE CASCADE;


--
-- Name: explorer_sub_elements explorer_sub_elements_explorer_entry_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.explorer_sub_elements
    ADD CONSTRAINT explorer_sub_elements_explorer_entry_id_fkey FOREIGN KEY (explorer_entry_id) REFERENCES public.explorer_entries(id) ON DELETE CASCADE;


--
-- Name: explorer_symbols explorer_symbols_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.explorer_symbols
    ADD CONSTRAINT explorer_symbols_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE CASCADE;


--
-- Name: mockups mockups_parent_mockup_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.mockups
    ADD CONSTRAINT mockups_parent_mockup_id_fkey FOREIGN KEY (parent_mockup_id) REFERENCES public.mockups(id) ON DELETE SET NULL;


--
-- Name: mockups mockups_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.mockups
    ADD CONSTRAINT mockups_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE CASCADE;


--
-- Name: mockups mockups_task_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.mockups
    ADD CONSTRAINT mockups_task_id_fkey FOREIGN KEY (task_id) REFERENCES public.tasks(id) ON DELETE SET NULL;


--
-- Name: notifications notifications_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notifications
    ADD CONSTRAINT notifications_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE CASCADE;


--
-- Name: notifications notifications_task_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notifications
    ADD CONSTRAINT notifications_task_id_fkey FOREIGN KEY (task_id) REFERENCES public.tasks(id) ON DELETE SET NULL;


--
-- Name: qa_issues qa_issues_entry_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.qa_issues
    ADD CONSTRAINT qa_issues_entry_id_fkey FOREIGN KEY (entry_id) REFERENCES public.explorer_entries(id) ON DELETE SET NULL;


--
-- Name: qa_issues qa_issues_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.qa_issues
    ADD CONSTRAINT qa_issues_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE CASCADE;


--
-- Name: quality_check_results quality_check_results_escalation_task_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quality_check_results
    ADD CONSTRAINT quality_check_results_escalation_task_id_fkey FOREIGN KEY (escalation_task_id) REFERENCES public.tasks(id) ON DELETE SET NULL;


--
-- Name: quality_check_results quality_check_results_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quality_check_results
    ADD CONSTRAINT quality_check_results_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE CASCADE;


--
-- Name: refactor_sessions refactor_sessions_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.refactor_sessions
    ADD CONSTRAINT refactor_sessions_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE CASCADE;


--
-- Name: scan_history scan_history_previous_scan_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scan_history
    ADD CONSTRAINT scan_history_previous_scan_id_fkey FOREIGN KEY (previous_scan_id) REFERENCES public.scan_history(id);


--
-- Name: scan_history scan_history_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scan_history
    ADD CONSTRAINT scan_history_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE CASCADE;


--
-- Name: scan_states scan_states_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scan_states
    ADD CONSTRAINT scan_states_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE CASCADE;


--
-- Name: sitemap_entries sitemap_entries_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sitemap_entries
    ADD CONSTRAINT sitemap_entries_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE CASCADE;


--
-- Name: subtask_citations subtask_citations_subtask_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.subtask_citations
    ADD CONSTRAINT subtask_citations_subtask_id_fkey FOREIGN KEY (subtask_id) REFERENCES public.task_subtasks(id) ON DELETE CASCADE;


--
-- Name: subtask_dependencies subtask_dependencies_depends_on_subtask_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.subtask_dependencies
    ADD CONSTRAINT subtask_dependencies_depends_on_subtask_id_fkey FOREIGN KEY (depends_on_subtask_id) REFERENCES public.task_subtasks(id) ON DELETE CASCADE;


--
-- Name: subtask_dependencies subtask_dependencies_subtask_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.subtask_dependencies
    ADD CONSTRAINT subtask_dependencies_subtask_id_fkey FOREIGN KEY (subtask_id) REFERENCES public.task_subtasks(id) ON DELETE CASCADE;


--
-- Name: subtask_summaries subtask_summaries_subtask_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.subtask_summaries
    ADD CONSTRAINT subtask_summaries_subtask_id_fkey FOREIGN KEY (subtask_id) REFERENCES public.task_subtasks(id) ON DELETE CASCADE;


--
-- Name: task_dependencies task_dependencies_depends_on_task_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_dependencies
    ADD CONSTRAINT task_dependencies_depends_on_task_id_fkey FOREIGN KEY (depends_on_task_id) REFERENCES public.tasks(id) ON DELETE CASCADE;


--
-- Name: task_dependencies task_dependencies_task_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_dependencies
    ADD CONSTRAINT task_dependencies_task_id_fkey FOREIGN KEY (task_id) REFERENCES public.tasks(id) ON DELETE CASCADE;


--
-- Name: task_labels task_labels_task_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_labels
    ADD CONSTRAINT task_labels_task_id_fkey FOREIGN KEY (task_id) REFERENCES public.tasks(id) ON DELETE CASCADE;


--
-- Name: task_spirit task_spirit_task_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_spirit
    ADD CONSTRAINT task_spirit_task_id_fkey FOREIGN KEY (task_id) REFERENCES public.tasks(id) ON DELETE CASCADE;


--
-- Name: task_subtask_steps task_subtask_steps_subtask_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_subtask_steps
    ADD CONSTRAINT task_subtask_steps_subtask_id_fkey FOREIGN KEY (subtask_id) REFERENCES public.task_subtasks(id) ON DELETE CASCADE;


--
-- Name: task_subtasks task_subtasks_task_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_subtasks
    ADD CONSTRAINT task_subtasks_task_id_fkey FOREIGN KEY (task_id) REFERENCES public.tasks(id) ON DELETE CASCADE;


--
-- Name: tasks tasks_parent_task_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tasks
    ADD CONSTRAINT tasks_parent_task_id_fkey FOREIGN KEY (parent_task_id) REFERENCES public.tasks(id) ON DELETE SET NULL;


--
-- Name: tasks tasks_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tasks
    ADD CONSTRAINT tasks_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE CASCADE;


--
-- Name: aterm_sessions aterm_sessions_pane_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.aterm_sessions
    ADD CONSTRAINT aterm_sessions_pane_id_fkey FOREIGN KEY (pane_id) REFERENCES public.aterm_panes(id) ON DELETE CASCADE;


--
-- Name: user_prompts user_prompts_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_prompts
    ADD CONSTRAINT user_prompts_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE CASCADE;


--
-- PostgreSQL database dump complete
--

\unrestrict IQaHikaoYBGqGtEiTocohupnoeKE9aZh0xW9D8asSUTeeLb9JLfYgjbilD9gFdv
