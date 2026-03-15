--
-- PostgreSQL database dump
--

\restrict vkRqVkwyYCmVowZW2ufUzKpekNWJXTQWEO9gJhoIOnqaZgyp4PioeKk2flFDqaM

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
-- Name: public; Type: SCHEMA; Schema: -; Owner: -
--

-- *not* creating schema, since initdb creates it


--
-- Name: pg_stat_statements; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS pg_stat_statements WITH SCHEMA public;


--
-- Name: EXTENSION pg_stat_statements; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION pg_stat_statements IS 'track planning and execution statistics of all SQL statements executed';


--
-- Name: uuid-ossp; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS "uuid-ossp" WITH SCHEMA public;


--
-- Name: EXTENSION "uuid-ossp"; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION "uuid-ossp" IS 'generate universally unique identifiers (UUIDs)';


--
-- Name: market_event_type; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.market_event_type AS ENUM (
    'fomc_decision',
    'cpi_release',
    'nfp_release',
    'fed_speech',
    'pce_release',
    'gdp_release'
);


--
-- Name: cleanup_old_audit_records(integer); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.cleanup_old_audit_records(days_to_keep integer DEFAULT 90) RETURNS TABLE(deleted_count bigint, oldest_remaining_date timestamp with time zone)
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_deleted_count BIGINT;
    v_oldest_date TIMESTAMPTZ;
BEGIN
    -- Delete records older than retention period
    DELETE FROM deletion_audit
    WHERE deleted_at < NOW() - (days_to_keep || ' days')::INTERVAL;

    GET DIAGNOSTICS v_deleted_count = ROW_COUNT;

    -- Get oldest remaining record
    SELECT MIN(da.deleted_at) INTO v_oldest_date
    FROM deletion_audit da;

    RETURN QUERY
    SELECT v_deleted_count, v_oldest_date;
END;
$$;


--
-- Name: create_thesis_version(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.create_thesis_version() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE
    change_type VARCHAR(50);
    snapshot_data JSONB;
BEGIN
    -- Determine change reason
    IF TG_OP = 'INSERT' THEN
        change_type := 'created';
    ELSIF NEW.status = 'invalidated' AND OLD.status != 'invalidated' THEN
        change_type := 'invalidated';
    ELSE
        change_type := 'updated';
    END IF;

    -- Build snapshot of current thesis state
    snapshot_data := jsonb_build_object(
        'symbol', NEW.symbol,
        'version', NEW.version,
        'status', NEW.status,
        'action', NEW.action,
        'core_reasons', NEW.core_reasons,
        'key_catalysts', NEW.key_catalysts,
        'risks', NEW.risks,
        'value_drivers', NEW.value_drivers,
        'expected_return_pct', NEW.expected_return_pct,
        'expected_timeframe_days', NEW.expected_timeframe_days,
        'claude_validation', NEW.claude_validation,
        'gemini_validation', NEW.gemini_validation,
        'cross_validation_score', NEW.cross_validation_score,
        'invalidation_reason', NEW.invalidation_reason,
        'invalidated_at', NEW.invalidated_at,
        'created_at', NEW.created_at,
        'updated_at', NEW.updated_at
    );

    -- Insert version history
    INSERT INTO thesis_versions (thesis_id, version, snapshot, change_reason)
    VALUES (NEW.id, NEW.version, snapshot_data, change_type);

    RETURN NEW;
END;
$$;


--
-- Name: detect_mass_deletions(integer, integer); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.detect_mass_deletions(threshold integer DEFAULT 100, time_window_minutes integer DEFAULT 60) RETURNS TABLE(table_name text, deletion_count bigint, time_window text, deleted_by text[])
    LANGUAGE plpgsql
    AS $$
BEGIN
    RETURN QUERY
    WITH deletion_windows AS (
        SELECT
            da.table_name,
            date_trunc('minute', da.deleted_at) AS minute_window,
            COUNT(*) AS deletions_in_minute,
            array_agg(DISTINCT da.deleted_by) AS users
        FROM deletion_audit da
        WHERE da.deleted_at > NOW() - (time_window_minutes || ' minutes')::INTERVAL
        GROUP BY da.table_name, date_trunc('minute', da.deleted_at)
    )
    SELECT
        dw.table_name,
        SUM(dw.deletions_in_minute)::BIGINT AS deletion_count,
        MIN(dw.minute_window)::TEXT || ' to ' || MAX(dw.minute_window)::TEXT AS time_window,
        array_agg(DISTINCT u)::TEXT[] AS deleted_by
    FROM deletion_windows dw,
         LATERAL unnest(dw.users) AS u
    WHERE dw.deletions_in_minute > threshold
    GROUP BY dw.table_name
    HAVING SUM(dw.deletions_in_minute) > threshold;
END;
$$;


--
-- Name: ensure_single_active_profile(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.ensure_single_active_profile() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    IF NEW.is_active = TRUE THEN
        -- Deactivate all other profiles for this user
        UPDATE settings_profiles
        SET is_active = FALSE, updated_at = CURRENT_TIMESTAMP
        WHERE user_id = NEW.user_id AND id != NEW.id AND is_active = TRUE;
    END IF;
    RETURN NEW;
END;
$$;


--
-- Name: get_deletion_summary(integer); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.get_deletion_summary(hours_ago integer DEFAULT 24) RETURNS TABLE(table_name text, total_deletions bigint, first_deletion timestamp with time zone, last_deletion timestamp with time zone)
    LANGUAGE plpgsql
    AS $$
BEGIN
    RETURN QUERY
    SELECT
        da.table_name,
        COUNT(*)::BIGINT AS total_deletions,
        MIN(da.deleted_at) AS first_deletion,
        MAX(da.deleted_at) AS last_deletion
    FROM deletion_audit da
    WHERE da.deleted_at > NOW() - (hours_ago || ' hours')::INTERVAL
    GROUP BY da.table_name
    ORDER BY total_deletions DESC;
END;
$$;


--
-- Name: get_recent_deletions(integer); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.get_recent_deletions(hours_ago integer DEFAULT 24) RETURNS TABLE(table_name text, record_id text, deleted_by text, deleted_at timestamp with time zone, deletion_reason text, row_count integer)
    LANGUAGE plpgsql
    AS $$
BEGIN
    RETURN QUERY
    SELECT
        da.table_name,
        da.record_id,
        da.deleted_by,
        da.deleted_at,
        da.deletion_reason,
        da.row_count
    FROM deletion_audit da
    WHERE da.deleted_at > NOW() - (hours_ago || ' hours')::INTERVAL
    ORDER BY da.deleted_at DESC;
END;
$$;


--
-- Name: log_deletion(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.log_deletion() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_record_id TEXT;
    v_symbol TEXT;
    v_json_row JSONB;
BEGIN
    -- Convert row to JSONB once
    v_json_row := to_jsonb(OLD);

    -- Extract ID (handle tables with different primary key names)
    -- Check if 'id' key exists by checking if extracted value is not null
    v_record_id := v_json_row->>'id';
    IF v_record_id IS NULL THEN
        v_record_id := 'unknown';
    END IF;

    -- Try to get symbol column if it exists
    v_symbol := v_json_row->>'symbol';
    IF v_symbol IS NULL THEN
        v_symbol := 'N/A';
    END IF;

    INSERT INTO deletion_audit (
        table_name,
        record_id,
        deleted_by,
        deletion_reason,
        metadata
    ) VALUES (
        TG_TABLE_NAME,
        v_record_id,
        CURRENT_USER,
        'trigger',
        jsonb_build_object(
            'symbol', v_symbol,
            'trigger_operation', TG_OP,
            'trigger_time', NOW()
        )
    );
    RETURN OLD;
END;
$$;


--
-- Name: log_migration_deletion(text, text, integer, text); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.log_migration_deletion(p_table_name text, p_deleted_by text, p_row_count integer, p_reason text DEFAULT 'migration'::text) RETURNS void
    LANGUAGE plpgsql
    AS $$
BEGIN
    INSERT INTO deletion_audit (
        table_name,
        record_id,
        deleted_by,
        deletion_reason,
        row_count,
        metadata
    ) VALUES (
        p_table_name,
        'bulk_operation',
        p_deleted_by,
        p_reason,
        p_row_count,
        jsonb_build_object(
            'operation', 'bulk_delete',
            'logged_at', NOW()
        )
    );
END;
$$;


--
-- Name: update_artifacts_updated_at(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.update_artifacts_updated_at() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;


--
-- Name: update_corporate_actions_timestamp(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.update_corporate_actions_timestamp() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;


--
-- Name: update_market_events_updated_at(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.update_market_events_updated_at() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$;


--
-- Name: update_qa_issues_updated_at(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.update_qa_issues_updated_at() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;


--
-- Name: update_settings_profiles_updated_at(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.update_settings_profiles_updated_at() RETURNS trigger
    LANGUAGE plpgsql
    AS $$ BEGIN NEW.updated_at = CURRENT_TIMESTAMP; RETURN NEW; END; $$;


--
-- Name: update_sitemap_entries_updated_at(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.update_sitemap_entries_updated_at() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;


--
-- Name: update_symbols_updated_at(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.update_symbols_updated_at() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;


--
-- Name: update_updated_at_column(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.update_updated_at_column() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
   NEW.updated_at = NOW() AT TIME ZONE 'UTC';
   RETURN NEW;
END;
$$;


--
-- Name: update_watchlist_thesis_updated_at(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.update_watchlist_thesis_updated_at() RETURNS trigger
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
-- Name: agent_conversation_messages; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agent_conversation_messages (
    id text DEFAULT (gen_random_uuid())::text NOT NULL,
    agent_run_id text NOT NULL,
    sequence_num integer NOT NULL,
    role text NOT NULL,
    content text NOT NULL,
    token_count integer,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    metadata jsonb,
    CONSTRAINT chk_agent_conversation_messages_role CHECK ((role = ANY (ARRAY['user'::text, 'assistant'::text, 'system'::text, 'tool_call'::text, 'tool_result'::text])))
);


--
-- Name: agent_messages; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agent_messages (
    id text DEFAULT (gen_random_uuid())::text NOT NULL,
    from_agent_run_id text,
    to_agent_type text NOT NULL,
    message_type text NOT NULL,
    content jsonb NOT NULL,
    status text DEFAULT 'pending'::text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    read_at timestamp with time zone,
    replied_at timestamp with time zone,
    priority integer DEFAULT 5,
    timeout_seconds integer DEFAULT 300,
    CONSTRAINT agent_messages_message_type_check CHECK ((message_type = ANY (ARRAY['question'::text, 'answer'::text, 'data'::text, 'consensus'::text]))),
    CONSTRAINT agent_messages_priority_check CHECK (((priority >= 1) AND (priority <= 10))),
    CONSTRAINT agent_messages_read_at_check CHECK (((status <> 'read'::text) OR (read_at IS NOT NULL))),
    CONSTRAINT agent_messages_replied_at_check CHECK (((status <> 'replied'::text) OR (replied_at IS NOT NULL))),
    CONSTRAINT agent_messages_status_check CHECK ((status = ANY (ARRAY['pending'::text, 'read'::text, 'replied'::text])))
);


--
-- Name: TABLE agent_messages; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.agent_messages IS 'Inter-agent communication: questions, answers, data sharing, consensus';


--
-- Name: COLUMN agent_messages.from_agent_run_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.agent_messages.from_agent_run_id IS 'Source agent run (NULL for system messages)';


--
-- Name: COLUMN agent_messages.to_agent_type; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.agent_messages.to_agent_type IS 'Target agent type (e.g., gemini, claude, strategy_analyzer)';


--
-- Name: COLUMN agent_messages.message_type; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.agent_messages.message_type IS 'Type of message: question, answer, data, consensus';


--
-- Name: COLUMN agent_messages.content; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.agent_messages.content IS 'Message payload (structure varies by message_type)';


--
-- Name: COLUMN agent_messages.status; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.agent_messages.status IS 'Message state: pending → read → replied';


--
-- Name: COLUMN agent_messages.priority; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.agent_messages.priority IS '1 (urgent) to 10 (low priority), default 5';


--
-- Name: agent_runs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agent_runs (
    id text NOT NULL,
    agent_type text NOT NULL,
    started_at timestamp with time zone NOT NULL,
    completed_at timestamp with time zone,
    status text NOT NULL,
    num_ideas integer DEFAULT 0,
    cost_usd double precision DEFAULT 0.0,
    error_message text,
    metadata jsonb,
    celery_task_id text,
    provider text,
    model text,
    cli_command text,
    exit_code integer,
    duration_ms integer,
    token_usage jsonb,
    session_id text,
    run_type text DEFAULT 'automated'::text,
    parent_run_id text,
    workflow_id text,
    user_id text,
    CONSTRAINT chk_agent_runs_run_type CHECK ((run_type = ANY (ARRAY['automated'::text, 'user_chat'::text, 'cross_validation'::text])))
);


--
-- Name: COLUMN agent_runs.provider; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.agent_runs.provider IS 'CLI provider: gemini, claude, or anthropic_api';


--
-- Name: COLUMN agent_runs.model; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.agent_runs.model IS 'Specific model name (e.g., gemini-2.5-pro, claude-sonnet-4-5-20250929)';


--
-- Name: COLUMN agent_runs.cli_command; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.agent_runs.cli_command IS 'Full CLI command executed (sanitized, for debugging)';


--
-- Name: COLUMN agent_runs.exit_code; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.agent_runs.exit_code IS 'Process exit code: 0 = success, non-zero = error';


--
-- Name: COLUMN agent_runs.duration_ms; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.agent_runs.duration_ms IS 'Execution duration in milliseconds';


--
-- Name: COLUMN agent_runs.token_usage; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.agent_runs.token_usage IS 'Token counts: {input_tokens, output_tokens, total_tokens}';


--
-- Name: COLUMN agent_runs.session_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.agent_runs.session_id IS 'CLI session ID for resume/continue support';


--
-- Name: agent_tool_calls; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agent_tool_calls (
    id text NOT NULL,
    agent_run_id text NOT NULL,
    tool_name text NOT NULL,
    parameters jsonb NOT NULL,
    response_summary text,
    duration_ms integer,
    called_at timestamp with time zone DEFAULT now()
);


--
-- Name: agent_workflows; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agent_workflows (
    id text DEFAULT (gen_random_uuid())::text NOT NULL,
    workflow_type text NOT NULL,
    status text DEFAULT 'pending'::text NOT NULL,
    current_step text,
    agents_involved text[] DEFAULT '{}'::text[] NOT NULL,
    shared_context jsonb DEFAULT '{}'::jsonb NOT NULL,
    result jsonb,
    error text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    started_at timestamp with time zone,
    completed_at timestamp with time zone,
    last_updated_at timestamp with time zone DEFAULT now() NOT NULL,
    max_duration_seconds integer DEFAULT 3600,
    retry_count integer DEFAULT 0,
    max_retries integer DEFAULT 3,
    triggered_by text,
    priority integer DEFAULT 5,
    CONSTRAINT agent_workflows_completed_at_check CHECK (((status <> ALL (ARRAY['complete'::text, 'failed'::text])) OR (completed_at IS NOT NULL))),
    CONSTRAINT agent_workflows_error_check CHECK (((status <> 'failed'::text) OR (error IS NOT NULL))),
    CONSTRAINT agent_workflows_priority_check CHECK (((priority >= 1) AND (priority <= 10))),
    CONSTRAINT agent_workflows_result_check CHECK (((status <> 'complete'::text) OR (result IS NOT NULL))),
    CONSTRAINT agent_workflows_started_at_check CHECK (((status <> ALL (ARRAY['running'::text, 'blocked'::text, 'complete'::text, 'failed'::text])) OR (started_at IS NOT NULL))),
    CONSTRAINT agent_workflows_status_check CHECK ((status = ANY (ARRAY['pending'::text, 'running'::text, 'blocked'::text, 'complete'::text, 'failed'::text])))
);


--
-- Name: TABLE agent_workflows; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.agent_workflows IS 'Multi-agent workflow orchestration state tracking

Common workflow types:
- daily_gap_analysis: Gemini → Claude → Consensus → Report
- paper_trade_validation: Strategy agent → Risk agent → Consensus → Execution
- research_corroboration: Agent A researches → Agent B verifies → Consensus
- strategy_backtest: Backtest → Analysis → Paper trade decision';


--
-- Name: COLUMN agent_workflows.workflow_type; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.agent_workflows.workflow_type IS 'Workflow identifier (e.g., daily_gap_analysis, paper_trade_validation)';


--
-- Name: COLUMN agent_workflows.status; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.agent_workflows.status IS 'Workflow state: pending → running → blocked/complete/failed';


--
-- Name: COLUMN agent_workflows.current_step; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.agent_workflows.current_step IS 'Current execution step description';


--
-- Name: COLUMN agent_workflows.agents_involved; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.agent_workflows.agents_involved IS 'Array of agent types participating';


--
-- Name: COLUMN agent_workflows.shared_context; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.agent_workflows.shared_context IS 'Shared data accessible to all agents in workflow';


--
-- Name: COLUMN agent_workflows.result; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.agent_workflows.result IS 'Final workflow output (only set when complete)';


--
-- Name: COLUMN agent_workflows.max_duration_seconds; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.agent_workflows.max_duration_seconds IS 'Maximum workflow runtime (prevents infinite loops)';


--
-- Name: COLUMN agent_workflows.retry_count; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.agent_workflows.retry_count IS 'Number of retry attempts for failed workflows';


--
-- Name: alembic_version; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.alembic_version (
    version_num character varying(32) NOT NULL
);


--
-- Name: analyst_revisions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.analyst_revisions (
    id integer NOT NULL,
    symbol character varying(10) NOT NULL,
    metric character varying(50) NOT NULL,
    period character varying(20) NOT NULL,
    current_estimate numeric(15,4),
    estimate_7d_ago numeric(15,4),
    estimate_30d_ago numeric(15,4),
    estimate_90d_ago numeric(15,4),
    revision_direction character varying(10),
    revision_magnitude numeric(8,4),
    num_analysts integer,
    fetched_at timestamp with time zone DEFAULT now()
);


--
-- Name: TABLE analyst_revisions; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.analyst_revisions IS 'Analyst estimate revisions for earnings momentum signals (GAP-005)';


--
-- Name: analyst_revisions_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.analyst_revisions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: analyst_revisions_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.analyst_revisions_id_seq OWNED BY public.analyst_revisions.id;


--
-- Name: artifacts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.artifacts (
    id integer NOT NULL,
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
-- Name: automation_preferences; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.automation_preferences (
    id text NOT NULL,
    thesis_generation_enabled boolean,
    auto_remove_on_invalidation boolean,
    auto_trim_enabled boolean,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: backtest_equity; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.backtest_equity (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    run_id uuid NOT NULL,
    date date NOT NULL,
    equity numeric(15,2) NOT NULL,
    cash numeric(15,2) NOT NULL,
    position_value numeric(15,2) NOT NULL,
    drawdown_pct numeric(10,4) NOT NULL,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT backtest_equity_values_check CHECK (((equity >= (0)::numeric) AND (cash >= (0)::numeric) AND (position_value >= (0)::numeric)))
);


--
-- Name: TABLE backtest_equity; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.backtest_equity IS 'Daily equity curve snapshots for drawdown calculation and visualization.';


--
-- Name: COLUMN backtest_equity.drawdown_pct; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.backtest_equity.drawdown_pct IS 'Current drawdown from peak equity. Calculated as (peak - current) / peak * 100.';


--
-- Name: backtest_runs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.backtest_runs (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    strategy_name character varying(100) NOT NULL,
    symbol character varying(20) NOT NULL,
    start_date date NOT NULL,
    end_date date NOT NULL,
    initial_capital numeric(15,2) NOT NULL,
    final_equity numeric(15,2),
    total_return_pct numeric(10,4),
    sharpe_ratio numeric(10,4),
    max_drawdown_pct numeric(10,4),
    win_rate numeric(10,4),
    num_trades integer,
    profit_factor numeric(10,4),
    status character varying(20) DEFAULT 'pending'::character varying NOT NULL,
    error_message text,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    completed_at timestamp with time zone,
    strategy_definition_id uuid,
    buy_hold_return numeric(12,4),
    excess_return numeric(12,4),
    beats_buy_hold boolean,
    alpha numeric(12,6),
    information_ratio numeric(12,4),
    beta numeric(8,4),
    benchmark_symbol character varying(20) DEFAULT 'SPY'::character varying,
    CONSTRAINT backtest_runs_capital_check CHECK ((initial_capital > (0)::numeric)),
    CONSTRAINT backtest_runs_dates_check CHECK ((end_date >= start_date)),
    CONSTRAINT backtest_runs_status_check CHECK (((status)::text = ANY ((ARRAY['pending'::character varying, 'running'::character varying, 'completed'::character varying, 'failed'::character varying])::text[])))
);


--
-- Name: TABLE backtest_runs; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.backtest_runs IS 'Backtest execution metadata and final performance metrics. Single-symbol backtests for Phase A MVP.';


--
-- Name: COLUMN backtest_runs.strategy_name; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.backtest_runs.strategy_name IS 'Strategy used (e.g., signal_classifier). Extensible for custom strategies in Phase B.';


--
-- Name: COLUMN backtest_runs.profit_factor; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.backtest_runs.profit_factor IS 'Sum of winning trades divided by sum of losing trades. >1.0 indicates profitable strategy.';


--
-- Name: COLUMN backtest_runs.buy_hold_return; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.backtest_runs.buy_hold_return IS 'Buy-and-hold return (%) for benchmark over same period';


--
-- Name: COLUMN backtest_runs.excess_return; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.backtest_runs.excess_return IS 'Strategy return minus buy-hold return (%)';


--
-- Name: COLUMN backtest_runs.beats_buy_hold; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.backtest_runs.beats_buy_hold IS 'Whether strategy outperformed buy-and-hold';


--
-- Name: COLUMN backtest_runs.alpha; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.backtest_runs.alpha IS 'Jensen alpha (CAPM risk-adjusted excess return)';


--
-- Name: COLUMN backtest_runs.information_ratio; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.backtest_runs.information_ratio IS 'Excess return per unit tracking error';


--
-- Name: COLUMN backtest_runs.beta; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.backtest_runs.beta IS 'Strategy beta vs benchmark';


--
-- Name: COLUMN backtest_runs.benchmark_symbol; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.backtest_runs.benchmark_symbol IS 'Benchmark symbol used (default SPY)';


--
-- Name: backtest_trades; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.backtest_trades (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    run_id uuid NOT NULL,
    symbol character varying(20) NOT NULL,
    entry_date date NOT NULL,
    entry_price numeric(15,4) NOT NULL,
    exit_date date,
    exit_price numeric(15,4),
    shares integer NOT NULL,
    pnl numeric(15,2),
    pnl_pct numeric(10,4),
    exit_reason character varying(20),
    max_favorable_pct numeric(10,4) DEFAULT 0.0,
    max_adverse_pct numeric(10,4) DEFAULT 0.0,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT backtest_trades_exit_reason_check CHECK ((((exit_reason)::text = ANY ((ARRAY['target'::character varying, 'stop'::character varying, 'signal'::character varying, 'time'::character varying, 'eod'::character varying])::text[])) OR (exit_reason IS NULL))),
    CONSTRAINT backtest_trades_prices_check CHECK (((entry_price > (0)::numeric) AND ((exit_price > (0)::numeric) OR (exit_price IS NULL)))),
    CONSTRAINT backtest_trades_shares_check CHECK ((shares > 0))
);


--
-- Name: TABLE backtest_trades; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.backtest_trades IS 'Individual trade entry/exit details within backtest runs. Tracks excursions and exit reasons.';


--
-- Name: COLUMN backtest_trades.exit_reason; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.backtest_trades.exit_reason IS 'Why trade was closed: target (profit target), stop (stop loss), signal (exit signal), time (max holding period), eod (end of backtest).';


--
-- Name: COLUMN backtest_trades.max_favorable_pct; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.backtest_trades.max_favorable_pct IS 'Best return percentage achieved during trade (for MAE/MFE analysis).';


--
-- Name: COLUMN backtest_trades.max_adverse_pct; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.backtest_trades.max_adverse_pct IS 'Worst return percentage during trade (for drawdown analysis).';


--
-- Name: cash_flow_metrics; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.cash_flow_metrics (
    id bigint NOT NULL,
    symbol character varying(20) NOT NULL,
    as_of_date date NOT NULL,
    operating_cash_flow double precision,
    free_cash_flow double precision,
    capital_expenditure double precision,
    fcf_yield double precision,
    cash_flow_margin double precision,
    fcf_per_share double precision,
    cash_conversion_ratio double precision,
    source character varying(50) DEFAULT 'yfinance'::character varying,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: cash_flow_metrics_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.cash_flow_metrics_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: cash_flow_metrics_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.cash_flow_metrics_id_seq OWNED BY public.cash_flow_metrics.id;


--
-- Name: claude_progress_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.claude_progress_log (
    id integer NOT NULL,
    session_id text,
    logged_at timestamp with time zone DEFAULT now(),
    action text NOT NULL,
    action_type text,
    feature_id text,
    task_file text,
    files_modified text[],
    details jsonb,
    git_commit text,
    context_percent integer
);


--
-- Name: TABLE claude_progress_log; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.claude_progress_log IS 'Session progress tracking for Claude Code sessions. Replaces text-based claude-progress.txt';


--
-- Name: COLUMN claude_progress_log.action_type; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.claude_progress_log.action_type IS 'Categories: start, progress, complete, verify, audit, pause, plan';


--
-- Name: claude_progress_log_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.claude_progress_log_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: claude_progress_log_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.claude_progress_log_id_seq OWNED BY public.claude_progress_log.id;


--
-- Name: corporate_actions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.corporate_actions (
    id integer NOT NULL,
    symbol character varying(20) NOT NULL,
    action_type character varying(50) NOT NULL,
    action_date date NOT NULL,
    repurchase_amount numeric(20,2),
    shares_repurchased bigint,
    dividend_amount numeric(10,4),
    dividend_yield numeric(6,4),
    ex_dividend_date date,
    split_ratio character varying(10),
    source character varying(50) DEFAULT 'yfinance'::character varying NOT NULL,
    raw_data jsonb,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: TABLE corporate_actions; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.corporate_actions IS 'Corporate actions: buybacks, dividends, splits. FEAT-175';


--
-- Name: corporate_actions_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.corporate_actions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: corporate_actions_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.corporate_actions_id_seq OWNED BY public.corporate_actions.id;


--
-- Name: criteria_verification_runs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.criteria_verification_runs (
    id integer NOT NULL,
    run_at timestamp with time zone DEFAULT now(),
    total_criteria integer,
    passed integer,
    failed integer,
    errors integer,
    type_filter text,
    duration_seconds double precision
);


--
-- Name: criteria_verification_runs_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.criteria_verification_runs_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: criteria_verification_runs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.criteria_verification_runs_id_seq OWNED BY public.criteria_verification_runs.id;


--
-- Name: cross_validation_results; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.cross_validation_results (
    id text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    generator_provider text DEFAULT 'gemini'::text NOT NULL,
    generator_model text,
    generator_output text NOT NULL,
    generator_confidence double precision,
    validator_provider text DEFAULT 'claude'::text NOT NULL,
    validator_model text,
    validator_review text,
    validator_approved boolean DEFAULT false,
    validator_confidence double precision,
    has_disagreement boolean DEFAULT false,
    disagreement_reasons jsonb DEFAULT '[]'::jsonb,
    disagreement_details text,
    status text DEFAULT 'pending'::text NOT NULL,
    resolved_at timestamp with time zone,
    resolved_by text,
    final_output text,
    context_type text DEFAULT 'insight'::text NOT NULL,
    context_symbol text,
    metadata jsonb DEFAULT '{}'::jsonb,
    generator_run_id text,
    validator_run_id text
);


--
-- Name: TABLE cross_validation_results; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.cross_validation_results IS 'Stores results of multi-agent cross-validation (Gemini generates, Claude validates)';


--
-- Name: COLUMN cross_validation_results.disagreement_reasons; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.cross_validation_results.disagreement_reasons IS 'Array of: factual, logical, risk_assessment, confidence, other';


--
-- Name: COLUMN cross_validation_results.status; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.cross_validation_results.status IS 'pending, approved, rejected, auto_applied, modified';


--
-- Name: day_bars; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.day_bars (
    symbol text NOT NULL,
    date date NOT NULL,
    open double precision NOT NULL,
    high double precision NOT NULL,
    low double precision NOT NULL,
    close double precision NOT NULL,
    volume bigint NOT NULL,
    vwap double precision,
    source text NOT NULL,
    ingest_run_id text
);


--
-- Name: deletion_audit; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.deletion_audit (
    id bigint NOT NULL,
    table_name text NOT NULL,
    record_id text NOT NULL,
    deleted_by text NOT NULL,
    deleted_at timestamp with time zone DEFAULT now() NOT NULL,
    deletion_reason text,
    row_count integer DEFAULT 1,
    metadata jsonb,
    restored_at timestamp with time zone
);


--
-- Name: deletion_audit_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.deletion_audit_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: deletion_audit_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.deletion_audit_id_seq OWNED BY public.deletion_audit.id;


--
-- Name: earnings_surprises; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.earnings_surprises (
    id integer NOT NULL,
    symbol character varying(20) NOT NULL,
    earnings_date date NOT NULL,
    fiscal_quarter character varying(10),
    eps_estimate numeric(10,4),
    eps_actual numeric(10,4),
    surprise_pct numeric(10,4),
    surprise_direction character varying(10),
    revenue_estimate numeric(20,2),
    revenue_actual numeric(20,2),
    data_source character varying(50) DEFAULT 'finnhub'::character varying NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: TABLE earnings_surprises; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.earnings_surprises IS 'Stores historical earnings results with surprise metrics (GAP-003)';


--
-- Name: COLUMN earnings_surprises.surprise_pct; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.earnings_surprises.surprise_pct IS 'Percentage surprise = (actual - estimate) / |estimate| * 100';


--
-- Name: COLUMN earnings_surprises.surprise_direction; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.earnings_surprises.surprise_direction IS 'beat = positive surprise, miss = negative surprise, inline = within 2%';


--
-- Name: earnings_surprises_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.earnings_surprises_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: earnings_surprises_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.earnings_surprises_id_seq OWNED BY public.earnings_surprises.id;


--
-- Name: endpoint_catalog; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.endpoint_catalog (
    id text NOT NULL,
    source_id text NOT NULL,
    endpoint_key text NOT NULL,
    target_table text NOT NULL,
    path_template text NOT NULL,
    field_mapping jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: fear_greed_components; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.fear_greed_components (
    as_of_date date NOT NULL,
    vix_pct smallint,
    momentum_pct smallint,
    rsi_pct smallint,
    pcr_pct smallint,
    credit_pct smallint,
    breadth_pct smallint,
    window_days integer DEFAULT 252,
    created_at timestamp with time zone DEFAULT now(),
    CONSTRAINT fear_greed_components_breadth_pct_check CHECK (((breadth_pct IS NULL) OR ((breadth_pct >= 0) AND (breadth_pct <= 100)))),
    CONSTRAINT fear_greed_components_credit_pct_check CHECK (((credit_pct >= 0) AND (credit_pct <= 100))),
    CONSTRAINT fear_greed_components_momentum_pct_check CHECK (((momentum_pct >= 0) AND (momentum_pct <= 100))),
    CONSTRAINT fear_greed_components_pcr_pct_check CHECK (((pcr_pct >= 0) AND (pcr_pct <= 100))),
    CONSTRAINT fear_greed_components_rsi_pct_check CHECK (((rsi_pct >= 0) AND (rsi_pct <= 100))),
    CONSTRAINT fear_greed_components_vix_pct_check CHECK (((vix_pct >= 0) AND (vix_pct <= 100)))
);


--
-- Name: TABLE fear_greed_components; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.fear_greed_components IS 'Percentile-ranked Fear & Greed components (0=Extreme Fear, 100=Extreme Greed). Uses 252-day rolling window for historical context.';


--
-- Name: COLUMN fear_greed_components.vix_pct; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.fear_greed_components.vix_pct IS 'VIX percentile - INVERTED (low VIX = low fear = greed)';


--
-- Name: COLUMN fear_greed_components.momentum_pct; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.fear_greed_components.momentum_pct IS 'SPY momentum vs SMA_200 - price above MA = greed';


--
-- Name: COLUMN fear_greed_components.rsi_pct; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.fear_greed_components.rsi_pct IS 'RSI percentile - high RSI = overbought = greed';


--
-- Name: COLUMN fear_greed_components.pcr_pct; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.fear_greed_components.pcr_pct IS 'Put/Call ratio percentile - INVERTED (low P/C = bullish = greed)';


--
-- Name: COLUMN fear_greed_components.credit_pct; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.fear_greed_components.credit_pct IS 'Credit spread percentile - INVERTED (low spread = low risk = greed)';


--
-- Name: COLUMN fear_greed_components.window_days; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.fear_greed_components.window_days IS 'Number of trading days used for percentile calculation (default 252 = 1 year)';


--
-- Name: fear_greed_daily; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.fear_greed_daily (
    as_of_date date NOT NULL,
    score double precision NOT NULL,
    label text NOT NULL,
    previous_score double precision,
    score_change double precision,
    signal_count smallint DEFAULT 5,
    created_at timestamp with time zone DEFAULT now(),
    CONSTRAINT fear_greed_daily_label_check CHECK ((label = ANY (ARRAY['Extreme Fear'::text, 'Fear'::text, 'Neutral'::text, 'Greed'::text, 'Extreme Greed'::text]))),
    CONSTRAINT fear_greed_daily_score_check CHECK (((score >= (0)::double precision) AND (score <= (100)::double precision)))
);


--
-- Name: TABLE fear_greed_daily; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.fear_greed_daily IS 'Final Fear & Greed Index scores with regime labels. Score ranges: 0-25=Extreme Fear, 25-45=Fear, 45-55=Neutral, 55-75=Greed, 75-100=Extreme Greed';


--
-- Name: COLUMN fear_greed_daily.score; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.fear_greed_daily.score IS 'Composite Fear & Greed score (0-100, equal-weighted average of components)';


--
-- Name: COLUMN fear_greed_daily.label; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.fear_greed_daily.label IS 'Regime label based on score thresholds';


--
-- Name: COLUMN fear_greed_daily.previous_score; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.fear_greed_daily.previous_score IS 'Previous trading day score for trend analysis';


--
-- Name: COLUMN fear_greed_daily.score_change; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.fear_greed_daily.score_change IS 'Daily change in score (positive = trending toward greed)';


--
-- Name: COLUMN fear_greed_daily.signal_count; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.fear_greed_daily.signal_count IS 'Number of signals included in calculation (5 for current version)';


--
-- Name: fear_greed_inputs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.fear_greed_inputs (
    as_of_date date NOT NULL,
    vix_close double precision,
    spy_close double precision,
    spy_sma_200 double precision,
    rsi_14 double precision,
    put_call_ratio double precision,
    hy_spread double precision,
    breadth_pct double precision,
    source_map jsonb DEFAULT '{}'::jsonb,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: COLUMN fear_greed_inputs.vix_close; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.fear_greed_inputs.vix_close IS 'CBOE VIX closing value - fear gauge (higher = more fear)';


--
-- Name: COLUMN fear_greed_inputs.spy_close; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.fear_greed_inputs.spy_close IS 'SPY ETF closing price for momentum calculation';


--
-- Name: COLUMN fear_greed_inputs.spy_sma_200; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.fear_greed_inputs.spy_sma_200 IS 'SPY 200-day simple moving average - trend indicator';


--
-- Name: COLUMN fear_greed_inputs.rsi_14; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.fear_greed_inputs.rsi_14 IS 'SPY 14-period RSI - overbought/oversold indicator';


--
-- Name: COLUMN fear_greed_inputs.put_call_ratio; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.fear_greed_inputs.put_call_ratio IS 'CBOE equity put/call ratio - options sentiment (higher = more bearish)';


--
-- Name: COLUMN fear_greed_inputs.hy_spread; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.fear_greed_inputs.hy_spread IS 'High-yield bond OAS spread in basis points - credit risk indicator (higher = more fear)';


--
-- Name: COLUMN fear_greed_inputs.breadth_pct; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.fear_greed_inputs.breadth_pct IS 'Percentage of S&P 500 stocks above 50-day MA - market breadth (future feature)';


--
-- Name: COLUMN fear_greed_inputs.source_map; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.fear_greed_inputs.source_map IS 'JSON map of signal names to data sources (e.g., {"vix": "FRED", "put_call": "CBOE"})';


--
-- Name: file_audit; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.file_audit (
    id integer NOT NULL,
    path text NOT NULL,
    is_directory boolean DEFAULT false,
    extension text,
    size_bytes integer,
    lines_of_code integer,
    file_count integer,
    total_loc integer,
    bloat_level text,
    last_modified timestamp with time zone,
    scanned_at timestamp with time zone DEFAULT now(),
    last_commit_days integer,
    reference_count integer DEFAULT 0,
    stale_status text
);


--
-- Name: file_audit_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.file_audit_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: file_audit_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.file_audit_id_seq OWNED BY public.file_audit.id;


--
-- Name: financial_health_scores; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.financial_health_scores (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    symbol character varying(20) NOT NULL,
    as_of_date timestamp with time zone DEFAULT now() NOT NULL,
    f_score integer,
    f_score_components jsonb,
    z_score numeric(12,4),
    z_score_zone character varying(20),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT financial_health_scores_f_score_check CHECK (((f_score >= 0) AND (f_score <= 9)))
);


--
-- Name: TABLE financial_health_scores; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.financial_health_scores IS 'Normalized financial health scores (F-score, Z-score)';


--
-- Name: gap_analysis_history; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.gap_analysis_history (
    analysis_id integer NOT NULL,
    analysis_timestamp timestamp with time zone DEFAULT (now() AT TIME ZONE 'UTC'::text) NOT NULL,
    total_gaps integer NOT NULL,
    p0_gaps integer NOT NULL,
    p1_gaps integer NOT NULL,
    p2_gaps integer NOT NULL,
    p3_gaps integer NOT NULL,
    avg_coverage_pct numeric(5,2),
    analysis_results jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT (now() AT TIME ZONE 'UTC'::text) NOT NULL
);


--
-- Name: TABLE gap_analysis_history; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.gap_analysis_history IS 'Historical snapshots of gap analysis (trending over time)';


--
-- Name: COLUMN gap_analysis_history.avg_coverage_pct; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.gap_analysis_history.avg_coverage_pct IS 'Average coverage % across all analysis types (0-100)';


--
-- Name: COLUMN gap_analysis_history.analysis_results; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.gap_analysis_history.analysis_results IS 'Full JSON result from gap_detector.analyze_gaps()';


--
-- Name: gap_analysis_history_analysis_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.gap_analysis_history_analysis_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: gap_analysis_history_analysis_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.gap_analysis_history_analysis_id_seq OWNED BY public.gap_analysis_history.analysis_id;


--
-- Name: household_confirmed_facts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.household_confirmed_facts (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    fact_key text NOT NULL,
    fact_value text NOT NULL,
    confirmed_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    metadata json DEFAULT '{}'::jsonb NOT NULL
);


--
-- Name: household_debt_obligations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.household_debt_obligations (
    id uuid NOT NULL,
    label text NOT NULL,
    debt_type text NOT NULL,
    lender text,
    balance numeric(14,2),
    monthly_payment numeric(12,2),
    interest_rate numeric(6,3),
    payoff_target_date date,
    secured_by text,
    notes text,
    confirmation_status text DEFAULT 'confirmed'::text NOT NULL,
    provenance text DEFAULT 'manual'::text NOT NULL,
    evidence_note text,
    source_document_id uuid,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: household_document_requirements; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.household_document_requirements (
    id uuid NOT NULL,
    requirement_key text NOT NULL,
    document_kind text NOT NULL,
    label text NOT NULL,
    status text DEFAULT 'missing'::text NOT NULL,
    priority text DEFAULT 'medium'::text NOT NULL,
    related_section text,
    related_record_id uuid,
    rationale text,
    notes text,
    source text DEFAULT 'system'::text NOT NULL,
    satisfied_by_document_id uuid,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: household_document_reviews; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.household_document_reviews (
    id uuid NOT NULL,
    document_id uuid NOT NULL,
    status text NOT NULL,
    summary text,
    confidence double precision,
    extracted_text text,
    structured_data jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: household_document_signatures; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.household_document_signatures (
    id uuid NOT NULL,
    signature_key character varying(255) NOT NULL,
    signature_type character varying(64) NOT NULL,
    source_type character varying(64) NOT NULL,
    document_type character varying(64) NOT NULL,
    merchant character varying(255),
    account_hint character varying(255),
    confidence double precision,
    sample_document_id uuid,
    metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    match_count integer DEFAULT 1 NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    last_seen_at timestamp with time zone NOT NULL
);


--
-- Name: household_documents; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.household_documents (
    id uuid NOT NULL,
    filename text NOT NULL,
    stored_path text NOT NULL,
    source_type text NOT NULL,
    document_type text NOT NULL,
    status text DEFAULT 'staged'::text NOT NULL,
    account_label text,
    content_type text,
    file_size_bytes bigint NOT NULL,
    classification_confidence double precision,
    statement_start date,
    statement_end date,
    uploaded_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    parsed_at timestamp with time zone,
    metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    review_status text,
    review_summary text,
    review_confidence double precision
);


--
-- Name: household_housing_costs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.household_housing_costs (
    id uuid NOT NULL,
    label text NOT NULL,
    housing_type text NOT NULL,
    occupancy_role text DEFAULT 'primary'::text NOT NULL,
    monthly_payment numeric(12,2),
    property_tax_monthly numeric(12,2),
    hoa_monthly numeric(12,2),
    insurance_monthly numeric(12,2),
    utilities_monthly numeric(12,2),
    maintenance_monthly numeric(12,2),
    mortgage_balance numeric(14,2),
    interest_rate numeric(6,3),
    notes text,
    confirmation_status text DEFAULT 'confirmed'::text NOT NULL,
    provenance text DEFAULT 'manual'::text NOT NULL,
    evidence_note text,
    source_document_id uuid,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: household_import_rows; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.household_import_rows (
    id uuid NOT NULL,
    document_id uuid NOT NULL,
    dataset_type character varying(64) NOT NULL,
    row_hash character varying(255) NOT NULL,
    external_row_id character varying(255),
    row_date timestamp with time zone,
    merchant character varying(255),
    description text,
    amount numeric(18,4),
    currency character varying(8),
    row_metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


--
-- Name: household_income_sources; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.household_income_sources (
    id uuid NOT NULL,
    label text NOT NULL,
    owner_name text,
    source_type text NOT NULL,
    pay_frequency text,
    employer_or_source text,
    gross_amount numeric(12,2),
    net_amount numeric(12,2),
    monthly_amount numeric(12,2),
    annual_amount numeric(12,2),
    variable_income_notes text,
    notes text,
    confirmation_status text DEFAULT 'confirmed'::text NOT NULL,
    provenance text DEFAULT 'manual'::text NOT NULL,
    evidence_note text,
    source_document_id uuid,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: household_inferred_values; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.household_inferred_values (
    id uuid NOT NULL,
    field_name text NOT NULL,
    value_text text,
    confidence double precision,
    status text DEFAULT 'inferred'::text NOT NULL,
    rationale text,
    source_document_id uuid,
    metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: household_insurance_policies; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.household_insurance_policies (
    id uuid NOT NULL,
    label text NOT NULL,
    coverage_type text NOT NULL,
    carrier text,
    premium_monthly numeric(12,2),
    coverage_amount numeric(14,2),
    deductible numeric(12,2),
    employer_sponsored boolean DEFAULT false NOT NULL,
    notes text,
    confirmation_status text DEFAULT 'confirmed'::text NOT NULL,
    provenance text DEFAULT 'manual'::text NOT NULL,
    evidence_note text,
    source_document_id uuid,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: household_members; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.household_members (
    id uuid NOT NULL,
    display_name text NOT NULL,
    role text NOT NULL,
    relationship text,
    birth_year integer,
    is_dependent boolean DEFAULT false NOT NULL,
    lives_in_household boolean DEFAULT true NOT NULL,
    notes text,
    confirmation_status text DEFAULT 'confirmed'::text NOT NULL,
    provenance text DEFAULT 'manual'::text NOT NULL,
    evidence_note text,
    source_document_id uuid,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: household_merchants; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.household_merchants (
    id uuid NOT NULL,
    canonical_name text NOT NULL,
    normalized_key text NOT NULL,
    display_name text,
    primary_category text,
    essentiality text,
    metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: household_planned_expenses; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.household_planned_expenses (
    id uuid NOT NULL,
    label text NOT NULL,
    expense_kind text NOT NULL,
    category text NOT NULL,
    target_amount numeric(12,2),
    target_date date,
    monthly_saving_target numeric(12,2),
    priority text DEFAULT 'medium'::text NOT NULL,
    notes text,
    confirmation_status text DEFAULT 'confirmed'::text NOT NULL,
    provenance text DEFAULT 'manual'::text NOT NULL,
    evidence_note text,
    source_document_id uuid,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: household_profiles; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.household_profiles (
    id uuid NOT NULL,
    household_name text DEFAULT 'Household'::text NOT NULL,
    monthly_net_income_target numeric(12,2),
    monthly_essential_target numeric(12,2),
    monthly_discretionary_target numeric(12,2),
    monthly_savings_target numeric(12,2),
    target_retirement_age integer,
    target_retirement_spend numeric(12,2),
    notes text,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    adult_count integer,
    dependent_count integer,
    filing_status text,
    state_of_residence text,
    effective_tax_rate numeric(6,2),
    marginal_federal_tax_rate numeric(6,2),
    marginal_state_tax_rate numeric(6,2),
    emergency_fund_target_months numeric(6,2),
    emergency_fund_target_amount numeric(12,2)
);


--
-- Name: household_questions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.household_questions (
    id uuid NOT NULL,
    field_name text,
    status text DEFAULT 'open'::text NOT NULL,
    priority text DEFAULT 'medium'::text NOT NULL,
    question text NOT NULL,
    rationale text,
    answer_text text,
    source_document_id uuid,
    metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    answered_at timestamp with time zone,
    question_format text DEFAULT 'short_text'::text NOT NULL,
    options jsonb,
    direction text DEFAULT 'jenny_to_user'::text NOT NULL
);


--
-- Name: household_retirement_income_sources; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.household_retirement_income_sources (
    id uuid NOT NULL,
    label text NOT NULL,
    source_type text NOT NULL,
    owner_name text,
    start_age integer,
    monthly_amount numeric(12,2),
    annual_amount numeric(12,2),
    inflation_adjusted boolean DEFAULT false NOT NULL,
    survivor_benefit boolean DEFAULT false NOT NULL,
    notes text,
    confirmation_status text DEFAULT 'confirmed'::text NOT NULL,
    provenance text DEFAULT 'manual'::text NOT NULL,
    evidence_note text,
    source_document_id uuid,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: household_transactions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.household_transactions (
    id uuid NOT NULL,
    document_id uuid NOT NULL,
    merchant_id uuid,
    row_hash character varying(128) NOT NULL,
    transaction_date timestamp with time zone NOT NULL,
    posted_date timestamp with time zone,
    description text NOT NULL,
    raw_merchant text,
    account_label text,
    amount numeric(18,4) NOT NULL,
    currency character varying(8) DEFAULT 'USD'::character varying NOT NULL,
    flow_type text NOT NULL,
    category text,
    essentiality text,
    confidence double precision,
    metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: idea_outcomes; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.idea_outcomes (
    idea_id text NOT NULL,
    agent_run_id text NOT NULL,
    symbol text NOT NULL,
    idea_type text NOT NULL,
    entry_price double precision,
    entry_date date,
    target_price double precision,
    stop_loss_price double precision,
    current_price double precision,
    current_return_pct double precision,
    status text NOT NULL,
    exit_price double precision,
    exit_date date,
    exit_reason text,
    realized_return_pct double precision,
    holding_days integer,
    max_favorable_pct double precision,
    max_adverse_pct double precision,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    shares integer,
    entry_amount double precision,
    exit_amount double precision,
    realized_pnl double precision,
    strategy_id uuid,
    backtest_sharpe numeric(10,4),
    backtest_win_rate numeric(10,4),
    backtest_max_drawdown numeric(10,4),
    backtest_run_id uuid,
    CONSTRAINT chk_entry_amount_positive CHECK (((entry_amount >= (0)::double precision) OR (entry_amount IS NULL))),
    CONSTRAINT chk_entry_price_positive CHECK (((entry_price >= (0)::double precision) OR (entry_price IS NULL))),
    CONSTRAINT chk_shares_positive CHECK (((shares >= 0) OR (shares IS NULL))),
    CONSTRAINT idea_outcomes_entry_price_positive CHECK (((entry_price > (0)::double precision) OR (status = 'error'::text)))
);


--
-- Name: COLUMN idea_outcomes.backtest_sharpe; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.idea_outcomes.backtest_sharpe IS 'Strategy expected Sharpe ratio from backtest';


--
-- Name: COLUMN idea_outcomes.backtest_win_rate; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.idea_outcomes.backtest_win_rate IS 'Strategy expected win rate from backtest (0-100)';


--
-- Name: COLUMN idea_outcomes.backtest_max_drawdown; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.idea_outcomes.backtest_max_drawdown IS 'Strategy expected max drawdown from backtest (0-100)';


--
-- Name: insider_transactions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.insider_transactions (
    id bigint NOT NULL,
    symbol character varying(20) NOT NULL,
    insider_name character varying(255),
    insider_title character varying(255),
    transaction_type character varying(50),
    transaction_date date NOT NULL,
    shares double precision,
    value double precision,
    shares_owned_after double precision,
    source character varying(50) DEFAULT 'yfinance'::character varying,
    raw_data jsonb,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: insider_transactions_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.insider_transactions_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: insider_transactions_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.insider_transactions_id_seq OWNED BY public.insider_transactions.id;


--
-- Name: institutional_holdings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.institutional_holdings (
    id bigint NOT NULL,
    symbol character varying(20) NOT NULL,
    holder_name character varying(255) NOT NULL,
    shares double precision,
    value double precision,
    pct_held double precision,
    pct_change double precision,
    report_date date,
    source character varying(50) DEFAULT 'yfinance'::character varying,
    raw_data jsonb,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: institutional_holdings_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.institutional_holdings_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: institutional_holdings_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.institutional_holdings_id_seq OWNED BY public.institutional_holdings.id;


--
-- Name: institutional_ownership_summary; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.institutional_ownership_summary (
    id bigint NOT NULL,
    symbol character varying(20) NOT NULL,
    as_of_date date NOT NULL,
    total_institutions integer,
    total_shares_held double precision,
    pct_held_institutions double precision,
    pct_held_insiders double precision,
    institutions_increased integer,
    institutions_decreased integer,
    source character varying(50) DEFAULT 'yfinance'::character varying,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: institutional_ownership_summary_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.institutional_ownership_summary_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: institutional_ownership_summary_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.institutional_ownership_summary_id_seq OWNED BY public.institutional_ownership_summary.id;


--
-- Name: jenny_agent_evaluations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.jenny_agent_evaluations (
    id uuid NOT NULL,
    routine_id uuid NOT NULL,
    symbol text NOT NULL,
    agent_name text NOT NULL,
    provider text,
    model text,
    verdict text NOT NULL,
    confidence double precision,
    rationale text NOT NULL,
    recommendation text,
    strengths jsonb DEFAULT '[]'::jsonb NOT NULL,
    weaknesses jsonb DEFAULT '[]'::jsonb NOT NULL,
    metadata jsonb,
    thesis_id uuid,
    agent_run_id text,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: jenny_agent_scorecards; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.jenny_agent_scorecards (
    agent_name text NOT NULL,
    total_evaluations integer DEFAULT 0 NOT NULL,
    completed_reviews integer DEFAULT 0 NOT NULL,
    positive_verdicts integer DEFAULT 0 NOT NULL,
    win_rate double precision,
    avg_return_pct double precision,
    agreement_rate double precision,
    calibration_score double precision,
    strengths jsonb DEFAULT '[]'::jsonb NOT NULL,
    weaknesses jsonb DEFAULT '[]'::jsonb NOT NULL,
    last_evaluation_at timestamp with time zone,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    entry_quality_score double precision,
    risk_judgment_score double precision,
    exit_timing_score double precision,
    alert_discipline_score double precision
);


--
-- Name: jenny_notifications; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.jenny_notifications (
    id uuid NOT NULL,
    routine_id uuid,
    symbol text,
    category text NOT NULL,
    severity text NOT NULL,
    status text DEFAULT 'open'::text NOT NULL,
    title text NOT NULL,
    detail text NOT NULL,
    recommendation text,
    metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    acknowledged_at timestamp with time zone
);


--
-- Name: jenny_routines; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.jenny_routines (
    id uuid NOT NULL,
    routine_type text NOT NULL,
    status text NOT NULL,
    triggered_by text DEFAULT 'system'::text NOT NULL,
    summary text,
    metadata jsonb,
    agents_used jsonb DEFAULT '[]'::jsonb NOT NULL,
    symbols_scanned integer DEFAULT 0 NOT NULL,
    notifications_created integer DEFAULT 0 NOT NULL,
    started_at timestamp with time zone DEFAULT now() NOT NULL,
    completed_at timestamp with time zone
);


--
-- Name: jenny_trade_reviews; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.jenny_trade_reviews (
    id uuid NOT NULL,
    symbol text NOT NULL,
    thesis_id uuid,
    idea_id text,
    review_source text NOT NULL,
    outcome_label text NOT NULL,
    return_pct double precision,
    lesson text NOT NULL,
    what_worked text,
    what_failed text,
    next_time text,
    agent_consensus jsonb DEFAULT '{}'::jsonb NOT NULL,
    metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: macro_indicators; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.macro_indicators (
    id bigint NOT NULL,
    indicator_name character varying(50) NOT NULL,
    series_id character varying(50),
    observation_date date NOT NULL,
    value double precision NOT NULL,
    source character varying(50) DEFAULT 'fred'::character varying,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: macro_indicators_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.macro_indicators_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: macro_indicators_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.macro_indicators_id_seq OWNED BY public.macro_indicators.id;


--
-- Name: maintenance_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.maintenance_log (
    id integer NOT NULL,
    task_name text NOT NULL,
    started_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    completed_at timestamp with time zone,
    status text NOT NULL,
    dry_run boolean DEFAULT false NOT NULL,
    summary jsonb,
    error_message text,
    CONSTRAINT maintenance_log_status_check CHECK ((status = ANY (ARRAY['running'::text, 'success'::text, 'error'::text])))
);


--
-- Name: COLUMN maintenance_log.task_name; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.maintenance_log.task_name IS 'Task name (no constraint - allows dynamic task names for monitoring)';


--
-- Name: COLUMN maintenance_log.started_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.maintenance_log.started_at IS 'Timestamp when task started (timezone-aware)';


--
-- Name: COLUMN maintenance_log.completed_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.maintenance_log.completed_at IS 'Timestamp when task completed (timezone-aware)';


--
-- Name: maintenance_log_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.maintenance_log_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: maintenance_log_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.maintenance_log_id_seq OWNED BY public.maintenance_log.id;


--
-- Name: maintenance_stats; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.maintenance_stats (
    id integer NOT NULL,
    recorded_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    metric_name text NOT NULL,
    metric_value numeric NOT NULL,
    metric_unit text,
    metadata jsonb,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: TABLE maintenance_stats; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.maintenance_stats IS 'Tracks maintenance metrics over time (database size, disk space, cleanup counts, etc.)';


--
-- Name: COLUMN maintenance_stats.metric_name; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.maintenance_stats.metric_name IS 'Name of metric (e.g., database_size_bytes, disk_space_used_percentage, news_cleaned_count)';


--
-- Name: COLUMN maintenance_stats.metric_value; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.maintenance_stats.metric_value IS 'Numeric value of metric';


--
-- Name: COLUMN maintenance_stats.metric_unit; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.maintenance_stats.metric_unit IS 'Unit of measurement (bytes, count, percentage, seconds, etc.)';


--
-- Name: COLUMN maintenance_stats.metadata; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.maintenance_stats.metadata IS 'Additional context (e.g., {"table": "news_cache", "partition": "/"})';


--
-- Name: maintenance_stats_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.maintenance_stats_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: maintenance_stats_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.maintenance_stats_id_seq OWNED BY public.maintenance_stats.id;


--
-- Name: market_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.market_events (
    id integer NOT NULL,
    event_type public.market_event_type NOT NULL,
    event_date date NOT NULL,
    event_time time without time zone,
    title character varying(255) NOT NULL,
    description text,
    expected_value numeric(12,4),
    actual_value numeric(12,4),
    prior_value numeric(12,4),
    surprise_pct numeric(8,4),
    impact_score smallint,
    spy_change_1h numeric(8,4),
    spy_change_1d numeric(8,4),
    source character varying(50) DEFAULT 'manual'::character varying,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT market_events_impact_score_check CHECK (((impact_score >= '-5'::integer) AND (impact_score <= 5)))
);


--
-- Name: TABLE market_events; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.market_events IS 'Market-wide macro events for sentiment chart overlays';


--
-- Name: COLUMN market_events.event_type; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.market_events.event_type IS 'Event category: fomc_decision, cpi_release, nfp_release, fed_speech, pce_release, gdp_release';


--
-- Name: COLUMN market_events.surprise_pct; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.market_events.surprise_pct IS 'Percentage surprise: (actual - expected) / expected * 100';


--
-- Name: COLUMN market_events.impact_score; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.market_events.impact_score IS 'Market impact from -5 (very bearish) to +5 (very bullish)';


--
-- Name: market_events_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.market_events_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: market_events_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.market_events_id_seq OWNED BY public.market_events.id;


--
-- Name: ml_model_metrics; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ml_model_metrics (
    id integer NOT NULL,
    model_name character varying(100) NOT NULL,
    model_version character varying(50) NOT NULL,
    trained_at timestamp with time zone DEFAULT now() NOT NULL,
    training_samples integer NOT NULL,
    test_samples integer NOT NULL,
    accuracy double precision NOT NULL,
    precision_score double precision NOT NULL,
    recall_score double precision NOT NULL,
    f1_score double precision NOT NULL,
    useful_count integer NOT NULL,
    not_useful_count integer NOT NULL,
    model_path text NOT NULL,
    training_duration_seconds double precision,
    notes text,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: TABLE ml_model_metrics; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.ml_model_metrics IS 'Tracks ML model retraining history and performance metrics';


--
-- Name: COLUMN ml_model_metrics.model_name; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.ml_model_metrics.model_name IS 'Model identifier (e.g., article_quality)';


--
-- Name: COLUMN ml_model_metrics.model_version; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.ml_model_metrics.model_version IS 'Version string (e.g., v1, v2, v2025-11-11)';


--
-- Name: COLUMN ml_model_metrics.trained_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.ml_model_metrics.trained_at IS 'Timestamp when model was trained (timezone-aware)';


--
-- Name: COLUMN ml_model_metrics.created_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.ml_model_metrics.created_at IS 'Timestamp when record was created (timezone-aware)';


--
-- Name: ml_model_metrics_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.ml_model_metrics_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: ml_model_metrics_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.ml_model_metrics_id_seq OWNED BY public.ml_model_metrics.id;


--
-- Name: ml_training_progress; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ml_training_progress (
    id integer NOT NULL,
    session_id character varying(50) NOT NULL,
    status character varying(50) NOT NULL,
    current_step character varying(200),
    progress_percent integer DEFAULT 0,
    articles_found integer DEFAULT 0,
    articles_labeled integer DEFAULT 0,
    articles_total integer DEFAULT 0,
    started_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    completed_at timestamp without time zone,
    model_version character varying(50),
    accuracy double precision,
    error_message text,
    created_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: TABLE ml_training_progress; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.ml_training_progress IS 'Real-time progress tracking for manual ML training runs';


--
-- Name: COLUMN ml_training_progress.session_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.ml_training_progress.session_id IS 'Unique session ID for this training run';


--
-- Name: COLUMN ml_training_progress.status; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.ml_training_progress.status IS 'Current status: querying, labeling, training, complete, failed';


--
-- Name: ml_training_progress_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.ml_training_progress_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: ml_training_progress_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.ml_training_progress_id_seq OWNED BY public.ml_training_progress.id;


--
-- Name: news_cache; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.news_cache (
    id bigint NOT NULL,
    symbol text NOT NULL,
    headline text NOT NULL,
    url text,
    summary text,
    news_source_name text,
    author text,
    image_url text,
    published_at timestamp with time zone,
    sentiment_score double precision,
    sentiment_label text,
    sentiment_confidence double precision,
    sentiment_model text,
    raw_payload jsonb,
    content_hash text NOT NULL,
    fetched_at timestamp with time zone DEFAULT now() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    filing_type text,
    is_material_event boolean DEFAULT false,
    story_id text,
    is_primary_article boolean DEFAULT false,
    coverage_count integer DEFAULT 1,
    impact_summary text,
    actionable_insight text,
    quality_prediction boolean,
    quality_confidence real
);


--
-- Name: COLUMN news_cache.filing_type; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.news_cache.filing_type IS 'SEC filing type (8-K, 10-Q, 10-K, 4, 13F, etc.)';


--
-- Name: COLUMN news_cache.is_material_event; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.news_cache.is_material_event IS 'True if filing represents material event (8-K items, large insider trades)';


--
-- Name: COLUMN news_cache.story_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.news_cache.story_id IS 'UUID linking articles about the same story/event (semantic clustering)';


--
-- Name: COLUMN news_cache.is_primary_article; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.news_cache.is_primary_article IS 'True if this is the primary article for a clustered story (highest priority source)';


--
-- Name: COLUMN news_cache.coverage_count; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.news_cache.coverage_count IS 'Number of sources that covered this story (indicates importance)';


--
-- Name: COLUMN news_cache.impact_summary; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.news_cache.impact_summary IS 'Plain language explanation of what the news means (e.g., "Strong results may drive stock higher short-term")';


--
-- Name: COLUMN news_cache.actionable_insight; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.news_cache.actionable_insight IS 'Context-aware recommendation for what to do (e.g., "Good news - consider adding to position if you own it")';


--
-- Name: COLUMN news_cache.quality_prediction; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.news_cache.quality_prediction IS 'ML model prediction: true=useful, false=not useful, null=not scored';


--
-- Name: COLUMN news_cache.quality_confidence; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.news_cache.quality_confidence IS 'ML model confidence score (0.0-1.0)';


--
-- Name: news_cache_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.news_cache_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: news_cache_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.news_cache_id_seq OWNED BY public.news_cache.id;


--
-- Name: news_summary_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.news_summary_log (
    id bigint NOT NULL,
    symbol text NOT NULL,
    window_start timestamp with time zone NOT NULL,
    window_end timestamp with time zone NOT NULL,
    sentiment_score double precision,
    sentiment_delta double precision,
    positive_count integer,
    neutral_count integer,
    negative_count integer,
    article_count integer,
    model_breakdown jsonb,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: news_summary_log_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.news_summary_log_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: news_summary_log_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.news_summary_log_id_seq OWNED BY public.news_summary_log.id;


--
-- Name: options_market_metrics; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.options_market_metrics (
    as_of_date date NOT NULL,
    most_active_call_pct numeric(5,2) NOT NULL,
    near_term_pct numeric(5,2) NOT NULL,
    concentration_pct numeric(5,2) NOT NULL,
    sector_weights jsonb NOT NULL,
    source_timestamp timestamp with time zone NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT options_market_metrics_concentration_pct_check CHECK (((concentration_pct >= (0)::numeric) AND (concentration_pct <= (100)::numeric))),
    CONSTRAINT options_market_metrics_most_active_call_pct_check CHECK (((most_active_call_pct >= (0)::numeric) AND (most_active_call_pct <= (100)::numeric))),
    CONSTRAINT options_market_metrics_near_term_pct_check CHECK (((near_term_pct >= (0)::numeric) AND (near_term_pct <= (100)::numeric)))
);


--
-- Name: TABLE options_market_metrics; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.options_market_metrics IS 'Aggregated daily metrics from CBOE Most Active Options.
Tracks sentiment (call/put mix), time horizon (near vs far-term),
concentration (focused vs dispersed), and sector distribution.
Data source: https://www.cboe.com/us/options/market_statistics/most_active/';


--
-- Name: COLUMN options_market_metrics.most_active_call_pct; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.options_market_metrics.most_active_call_pct IS 'Percentage of top 25 most active options that are calls (0-100).
Higher values indicate bullish positioning.';


--
-- Name: COLUMN options_market_metrics.near_term_pct; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.options_market_metrics.near_term_pct IS 'Percentage of top 25 options expiring within 30 days (0-100).
Higher values suggest event-driven or short-term positioning.';


--
-- Name: COLUMN options_market_metrics.concentration_pct; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.options_market_metrics.concentration_pct IS 'Percentage of volume concentrated in top 5 vs all top 25 contracts (0-100).
Higher values indicate focused institutional positioning.';


--
-- Name: COLUMN options_market_metrics.sector_weights; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.options_market_metrics.sector_weights IS 'Distribution of top 25 options across sectors as JSON object.
Example: {"Technology": 45.2, "Financials": 25.8}';


--
-- Name: paper_trade_transactions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.paper_trade_transactions (
    id text DEFAULT (gen_random_uuid())::text NOT NULL,
    trade_id text NOT NULL,
    transaction_type text NOT NULL,
    symbol text NOT NULL,
    shares integer NOT NULL,
    price double precision NOT NULL,
    amount double precision NOT NULL,
    cash_before double precision NOT NULL,
    cash_after double precision NOT NULL,
    "timestamp" timestamp with time zone DEFAULT now() NOT NULL,
    notes text,
    agent_run_id text,
    expected_price double precision,
    slippage_amount double precision DEFAULT 0.0,
    slippage_bps double precision DEFAULT 0.0,
    adv double precision,
    slippage_model text DEFAULT 'NONE'::text,
    CONSTRAINT paper_trade_transactions_transaction_type_check CHECK ((transaction_type = ANY (ARRAY['ENTRY'::text, 'EXIT'::text])))
);


--
-- Name: portfolio_accounts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.portfolio_accounts (
    id text NOT NULL,
    name text NOT NULL,
    account_type text NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    cash_balance double precision DEFAULT 100000.0 NOT NULL,
    initial_cash double precision DEFAULT 100000.0 NOT NULL
);


--
-- Name: portfolio_covariance; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.portfolio_covariance (
    symbol1 text NOT NULL,
    symbol2 text NOT NULL,
    covariance double precision NOT NULL,
    correlation double precision NOT NULL,
    volatility1 double precision NOT NULL,
    volatility2 double precision NOT NULL,
    observation_count integer NOT NULL,
    lookback_days integer DEFAULT 252 NOT NULL,
    calculated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: TABLE portfolio_covariance; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.portfolio_covariance IS 'Pairwise asset covariance matrix for correct portfolio risk calculation (GAP-020).
Uses 252-day lookback by default. Calculated from day_bars returns.';


--
-- Name: portfolio_positions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.portfolio_positions (
    id text NOT NULL,
    account_id text NOT NULL,
    symbol text NOT NULL,
    shares double precision NOT NULL,
    cost_basis double precision NOT NULL,
    position_type text NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    strategy_id uuid
);


--
-- Name: portfolio_snapshots; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.portfolio_snapshots (
    id integer NOT NULL,
    account_id text NOT NULL,
    snapshot_date date NOT NULL,
    equity numeric(15,2) NOT NULL,
    cash numeric(15,2) DEFAULT 0 NOT NULL,
    position_value numeric(15,2) DEFAULT 0 NOT NULL,
    peak_equity numeric(15,2) NOT NULL,
    drawdown_pct numeric(8,4) DEFAULT 0 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: TABLE portfolio_snapshots; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.portfolio_snapshots IS 'Daily portfolio equity snapshots for drawdown tracking (GAP-023)';


--
-- Name: COLUMN portfolio_snapshots.peak_equity; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.portfolio_snapshots.peak_equity IS 'Running peak equity value for drawdown calculation';


--
-- Name: COLUMN portfolio_snapshots.drawdown_pct; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.portfolio_snapshots.drawdown_pct IS 'Drawdown from peak as positive percentage (10.0 = -10% from peak)';


--
-- Name: portfolio_snapshots_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.portfolio_snapshots_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: portfolio_snapshots_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.portfolio_snapshots_id_seq OWNED BY public.portfolio_snapshots.id;


--
-- Name: portfolio_volatility_cache; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.portfolio_volatility_cache (
    portfolio_id text NOT NULL,
    weight_hash text NOT NULL,
    portfolio_volatility double precision NOT NULL,
    weighted_avg_volatility double precision NOT NULL,
    diversification_benefit double precision NOT NULL,
    calculated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: COLUMN portfolio_volatility_cache.diversification_benefit; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.portfolio_volatility_cache.diversification_benefit IS 'Shows how much lower portfolio vol is vs naive weighted average. 0.35 means 35% lower risk from diversification.';


--
-- Name: price_cache; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.price_cache (
    symbol text NOT NULL,
    price double precision NOT NULL,
    beta double precision,
    volatility double precision,
    sector text,
    cached_at timestamp with time zone NOT NULL,
    source text NOT NULL,
    error text,
    bid double precision,
    ask double precision,
    bid_size integer,
    ask_size integer
);


--
-- Name: COLUMN price_cache.bid; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.price_cache.bid IS 'Best bid price';


--
-- Name: COLUMN price_cache.ask; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.price_cache.ask IS 'Best ask price';


--
-- Name: COLUMN price_cache.bid_size; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.price_cache.bid_size IS 'Size at bid (shares)';


--
-- Name: COLUMN price_cache.ask_size; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.price_cache.ask_size IS 'Size at ask (shares)';


--
-- Name: qa_issues; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.qa_issues (
    id integer NOT NULL,
    issue_id character varying(20) NOT NULL,
    category character varying(50) NOT NULL,
    severity character varying(20) NOT NULL,
    file_path text,
    line_start integer,
    line_end integer,
    description text NOT NULL,
    detection_source character varying(50),
    first_detected_at timestamp with time zone DEFAULT now(),
    last_detected_at timestamp with time zone DEFAULT now(),
    resolved_at timestamp with time zone,
    resolved_by character varying(100),
    resolution_notes text,
    false_positive boolean DEFAULT false,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


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
-- Name: qa_snapshots; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.qa_snapshots (
    id integer NOT NULL,
    snapshot_date date NOT NULL,
    total_issues integer NOT NULL,
    critical_count integer DEFAULT 0,
    high_count integer DEFAULT 0,
    medium_count integer DEFAULT 0,
    low_count integer DEFAULT 0,
    by_category jsonb,
    issues_added integer DEFAULT 0,
    issues_resolved integer DEFAULT 0,
    lines_of_code integer,
    file_count integer,
    table_count integer,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: qa_snapshots_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.qa_snapshots_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: qa_snapshots_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.qa_snapshots_id_seq OWNED BY public.qa_snapshots.id;


--
-- Name: reference_cache; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.reference_cache (
    symbol text NOT NULL,
    as_of_date date NOT NULL,
    payload jsonb NOT NULL,
    source text NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    pe_ratio_trailing double precision,
    pe_ratio_forward double precision,
    ps_ratio double precision,
    pb_ratio double precision,
    peg_ratio double precision,
    dividend_yield double precision,
    payout_ratio double precision,
    f_score integer,
    f_score_components jsonb,
    z_score numeric(10,2),
    z_score_zone character varying(20),
    shares_short double precision,
    short_ratio double precision,
    short_percent_of_float double precision,
    free_cash_flow double precision,
    operating_cash_flow double precision
);


--
-- Name: COLUMN reference_cache.f_score; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.reference_cache.f_score IS 'Piotroski F-Score (0-9, higher=better quality)';


--
-- Name: COLUMN reference_cache.f_score_components; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.reference_cache.f_score_components IS 'Individual F-Score component scores (JSON)';


--
-- Name: COLUMN reference_cache.z_score; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.reference_cache.z_score IS 'Altman Z-Score (>2.99=safe, 1.81-2.99=grey, <1.81=distress)';


--
-- Name: COLUMN reference_cache.z_score_zone; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.reference_cache.z_score_zone IS 'Z-Score interpretation: safe, grey, or distress';


--
-- Name: rules_validation_reports; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.rules_validation_reports (
    id integer NOT NULL,
    rules_version character varying(50) NOT NULL,
    validation_time timestamp with time zone DEFAULT now() NOT NULL,
    overall_status character varying(20) NOT NULL,
    critical_count integer DEFAULT 0 NOT NULL,
    warning_count integer DEFAULT 0 NOT NULL,
    info_count integer DEFAULT 0 NOT NULL,
    validation_errors jsonb DEFAULT '[]'::jsonb NOT NULL,
    recommendations jsonb DEFAULT '[]'::jsonb NOT NULL,
    summary text NOT NULL,
    performance_data jsonb,
    CONSTRAINT rules_validation_reports_overall_status_check CHECK (((overall_status)::text = ANY ((ARRAY['valid'::character varying, 'warnings'::character varying, 'critical'::character varying])::text[])))
);


--
-- Name: TABLE rules_validation_reports; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.rules_validation_reports IS 'Automated trading rules validation results and optimization recommendations';


--
-- Name: COLUMN rules_validation_reports.rules_version; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.rules_validation_reports.rules_version IS 'Version from rules.yaml at time of validation';


--
-- Name: COLUMN rules_validation_reports.overall_status; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.rules_validation_reports.overall_status IS 'valid = no errors, warnings = non-critical issues, critical = blocking errors';


--
-- Name: COLUMN rules_validation_reports.validation_errors; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.rules_validation_reports.validation_errors IS 'JSON array: [{severity, category, field_path, message, current_value, expected_range}]';


--
-- Name: COLUMN rules_validation_reports.recommendations; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.rules_validation_reports.recommendations IS 'JSON array: [{priority, category, field_path, recommendation, rationale, suggested_value}]';


--
-- Name: COLUMN rules_validation_reports.performance_data; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.rules_validation_reports.performance_data IS 'Recent trading performance metrics used for optimization analysis';


--
-- Name: rules_validation_reports_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.rules_validation_reports_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: rules_validation_reports_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.rules_validation_reports_id_seq OWNED BY public.rules_validation_reports.id;


--
-- Name: schema_migrations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.schema_migrations (
    version integer NOT NULL,
    description text NOT NULL,
    applied_at timestamp without time zone NOT NULL,
    checksum text NOT NULL
);


--
-- Name: sec_cik_cache; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sec_cik_cache (
    symbol text NOT NULL,
    cik text NOT NULL,
    company_name text,
    last_updated timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: TABLE sec_cik_cache; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.sec_cik_cache IS 'SEC EDGAR ticker to CIK mapping cache. CIK numbers are permanent (never recycled), so cached values remain valid forever.';


--
-- Name: COLUMN sec_cik_cache.symbol; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.sec_cik_cache.symbol IS 'Stock ticker symbol (uppercase, e.g., NVDA)';


--
-- Name: COLUMN sec_cik_cache.cik; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.sec_cik_cache.cik IS 'SEC Central Index Key (10-digit zero-padded string, e.g., 0001045810)';


--
-- Name: COLUMN sec_cik_cache.company_name; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.sec_cik_cache.company_name IS 'Company name from SEC (optional, for reference)';


--
-- Name: COLUMN sec_cik_cache.last_updated; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.sec_cik_cache.last_updated IS 'Last time this mapping was verified/updated';


--
-- Name: COLUMN sec_cik_cache.created_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.sec_cik_cache.created_at IS 'When this mapping was first cached';


--
-- Name: settings_profiles; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.settings_profiles (
    id integer NOT NULL,
    user_id integer DEFAULT 1 NOT NULL,
    name character varying(255) NOT NULL,
    description text,
    is_active boolean DEFAULT false NOT NULL,
    profile_data jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT valid_profile_name CHECK (((length((name)::text) > 0) AND (length((name)::text) <= 255)))
);


--
-- Name: TABLE settings_profiles; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.settings_profiles IS 'Saved settings profiles for different trading strategies';


--
-- Name: COLUMN settings_profiles.is_active; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.settings_profiles.is_active IS 'Only one profile can be active per user at a time';


--
-- Name: COLUMN settings_profiles.profile_data; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.settings_profiles.profile_data IS 'Complete snapshot of user preferences as JSON';


--
-- Name: settings_profiles_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.settings_profiles_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: settings_profiles_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.settings_profiles_id_seq OWNED BY public.settings_profiles.id;


--
-- Name: short_interest; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.short_interest (
    id bigint NOT NULL,
    symbol character varying(20) NOT NULL,
    as_of_date date NOT NULL,
    short_shares double precision,
    short_ratio double precision,
    short_percent_of_float double precision,
    short_percent_of_outstanding double precision,
    short_prior_month double precision,
    short_pct_change double precision,
    source character varying(50) DEFAULT 'yfinance'::character varying,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: short_interest_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.short_interest_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: short_interest_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.short_interest_id_seq OWNED BY public.short_interest.id;


--
-- Name: short_interest_summary; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.short_interest_summary (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    symbol character varying(20) NOT NULL,
    as_of_date timestamp with time zone DEFAULT now() NOT NULL,
    shares_short bigint,
    short_ratio numeric(12,4),
    short_percent_of_float numeric(8,4),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: TABLE short_interest_summary; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.short_interest_summary IS 'Normalized short interest data';


--
-- Name: sitemap_entries; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sitemap_entries (
    id integer NOT NULL,
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
    artifact_id integer,
    last_evidence_captured_at timestamp with time zone,
    last_checked_at timestamp with time zone,
    discovered_at timestamp with time zone DEFAULT now(),
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: TABLE sitemap_entries; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.sitemap_entries IS 'Registry of all discoverable endpoints for health monitoring';


--
-- Name: COLUMN sitemap_entries.entry_type; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.sitemap_entries.entry_type IS 'frontend_page = Next.js pages, api_endpoint = FastAPI routes, manual = user-added';


--
-- Name: COLUMN sitemap_entries.health_status; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.sitemap_entries.health_status IS 'Based on console errors: healthy(0), warning(warnings only), error(errors)';


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
-- Name: sitemap_health_history; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sitemap_health_history (
    id integer NOT NULL,
    sitemap_entry_id integer NOT NULL,
    checked_at timestamp with time zone NOT NULL,
    health_status character varying(20),
    console_errors integer DEFAULT 0,
    console_warnings integer DEFAULT 0,
    http_status integer,
    response_time_ms integer,
    error_details jsonb,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: TABLE sitemap_health_history; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.sitemap_health_history IS 'Historical health check results with 7-day retention';


--
-- Name: COLUMN sitemap_health_history.error_details; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.sitemap_health_history.error_details IS 'JSONB with console errors/warnings, truncated to 10 entries';


--
-- Name: sitemap_health_history_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.sitemap_health_history_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: sitemap_health_history_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.sitemap_health_history_id_seq OWNED BY public.sitemap_health_history.id;


--
-- Name: source_credentials; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.source_credentials (
    source_id text NOT NULL,
    field text NOT NULL,
    value text NOT NULL,
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: source_metrics; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.source_metrics (
    id integer NOT NULL,
    vendor character varying(100) NOT NULL,
    duplicate_rate double precision NOT NULL,
    diversity_score double precision NOT NULL,
    confidence_avg double precision NOT NULL,
    freshness_score double precision NOT NULL,
    user_useful_rate double precision,
    quality_score double precision NOT NULL,
    article_count integer DEFAULT 0 NOT NULL,
    sample_period_start timestamp with time zone NOT NULL,
    calculated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT source_metrics_article_count_check CHECK ((article_count >= 0)),
    CONSTRAINT source_metrics_confidence_avg_check CHECK (((confidence_avg >= (0.0)::double precision) AND (confidence_avg <= (1.0)::double precision))),
    CONSTRAINT source_metrics_diversity_score_check CHECK (((diversity_score >= (0.0)::double precision) AND (diversity_score <= (1.0)::double precision))),
    CONSTRAINT source_metrics_duplicate_rate_check CHECK (((duplicate_rate >= (0.0)::double precision) AND (duplicate_rate <= (1.0)::double precision))),
    CONSTRAINT source_metrics_freshness_score_check CHECK (((freshness_score >= (0.0)::double precision) AND (freshness_score <= (1.0)::double precision))),
    CONSTRAINT source_metrics_quality_score_check CHECK (((quality_score >= (0.0)::double precision) AND (quality_score <= (1.0)::double precision))),
    CONSTRAINT source_metrics_user_useful_rate_check CHECK (((user_useful_rate >= (0.0)::double precision) AND (user_useful_rate <= (1.0)::double precision)))
);


--
-- Name: TABLE source_metrics; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.source_metrics IS 'Quality metrics for news vendors calculated by profiling task';


--
-- Name: COLUMN source_metrics.vendor; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.source_metrics.vendor IS 'Vendor/source identifier (e.g., polygon, finnhub, sec_edgar)';


--
-- Name: COLUMN source_metrics.duplicate_rate; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.source_metrics.duplicate_rate IS 'Proportion of duplicate articles (0=none, 1=all)';


--
-- Name: COLUMN source_metrics.diversity_score; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.source_metrics.diversity_score IS 'Headline uniqueness score (1=all unique, 0=all same)';


--
-- Name: COLUMN source_metrics.confidence_avg; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.source_metrics.confidence_avg IS 'Average sentiment confidence from FinBERT/VADER';


--
-- Name: COLUMN source_metrics.freshness_score; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.source_metrics.freshness_score IS 'Recency score (1=24h old, 0=7d old)';


--
-- Name: COLUMN source_metrics.user_useful_rate; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.source_metrics.user_useful_rate IS 'User feedback score (NULL if no feedback yet)';


--
-- Name: COLUMN source_metrics.quality_score; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.source_metrics.quality_score IS 'Weighted composite quality score';


--
-- Name: COLUMN source_metrics.article_count; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.source_metrics.article_count IS 'Number of articles in sample period';


--
-- Name: COLUMN source_metrics.sample_period_start; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.source_metrics.sample_period_start IS 'Start of analysis window';


--
-- Name: COLUMN source_metrics.calculated_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.source_metrics.calculated_at IS 'When metrics were calculated';


--
-- Name: source_metrics_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.source_metrics_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: source_metrics_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.source_metrics_id_seq OWNED BY public.source_metrics.id;


--
-- Name: source_performance; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.source_performance (
    source_name text NOT NULL,
    success_count integer DEFAULT 0,
    failure_count integer DEFAULT 0,
    total_latency_ms bigint DEFAULT 0,
    rate_limit_hits integer DEFAULT 0,
    last_success_at timestamp with time zone
);


--
-- Name: source_registry; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.source_registry (
    source_id text NOT NULL,
    display_name text NOT NULL,
    priority integer NOT NULL,
    enabled boolean DEFAULT true,
    definition jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: strategy_definitions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.strategy_definitions (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    name character varying(255) NOT NULL,
    symbol character varying(10) NOT NULL,
    strategy_type character varying(50) NOT NULL,
    parameters jsonb NOT NULL,
    research_summary jsonb NOT NULL,
    generation_reasoning text,
    backtest_metrics jsonb NOT NULL,
    expected_sharpe numeric(10,4),
    expected_win_rate numeric(5,4),
    expected_max_drawdown numeric(5,4),
    created_by character varying(255),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    version integer DEFAULT 1 NOT NULL,
    status character varying(50) DEFAULT 'testing'::character varying NOT NULL,
    activation_date timestamp with time zone,
    archive_date timestamp with time zone,
    archive_reason text,
    live_trades_count integer DEFAULT 0,
    live_win_rate numeric(5,4),
    live_sharpe_ratio numeric(10,4),
    last_used_at timestamp with time zone,
    live_metrics_updated_at timestamp with time zone,
    seed_id uuid,
    seed_thesis text,
    seed_confidence numeric(3,1)
);


--
-- Name: COLUMN strategy_definitions.seed_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.strategy_definitions.seed_id IS 'UUID reference to the seed that triggered this strategy (if AI-generated)';


--
-- Name: COLUMN strategy_definitions.seed_thesis; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.strategy_definitions.seed_thesis IS 'Original AI thesis preserved for evolution tracking';


--
-- Name: COLUMN strategy_definitions.seed_confidence; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.strategy_definitions.seed_confidence IS 'Original confidence score (1-10) from seed generation';


--
-- Name: strategy_lineage; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.strategy_lineage (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    child_strategy_id uuid NOT NULL,
    parent_strategy_id uuid,
    changes_description text NOT NULL,
    evolution_reason text NOT NULL,
    metrics_before jsonb,
    metrics_after jsonb,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: strategy_metrics; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.strategy_metrics (
    id text NOT NULL,
    metric_date date NOT NULL,
    metric_type text NOT NULL,
    total_signals integer DEFAULT 0 NOT NULL,
    buy_signals integer DEFAULT 0 NOT NULL,
    hold_signals integer DEFAULT 0 NOT NULL,
    avoid_signals integer DEFAULT 0 NOT NULL,
    signals_traded integer DEFAULT 0 NOT NULL,
    winning_trades integer DEFAULT 0 NOT NULL,
    losing_trades integer DEFAULT 0 NOT NULL,
    win_rate_pct numeric(5,2),
    avg_return_pct numeric(8,4),
    best_return_pct numeric(8,4),
    worst_return_pct numeric(8,4),
    cumulative_return_pct numeric(10,4),
    avg_overall_score numeric(5,2),
    avg_technical_score numeric(5,2),
    avg_fundamental_score numeric(5,2),
    score_stdev numeric(5,2),
    reviews_count integer DEFAULT 0 NOT NULL,
    disagreements_count integer DEFAULT 0 NOT NULL,
    disagreement_rate_pct numeric(5,2),
    provider_disagreements_count integer DEFAULT 0,
    provider_disagreement_rate_pct numeric(5,2),
    avg_agreement_score numeric(5,4),
    major_disagreements_count integer DEFAULT 0,
    minor_disagreements_count integer DEFAULT 0,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: strategy_performance; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.strategy_performance (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    strategy_id uuid NOT NULL,
    date date NOT NULL,
    trades_today integer DEFAULT 0,
    wins_today integer DEFAULT 0,
    losses_today integer DEFAULT 0,
    pnl_today numeric(15,2) DEFAULT 0,
    trades_30d integer DEFAULT 0,
    win_rate_30d numeric(5,4),
    sharpe_ratio_30d numeric(10,4),
    max_drawdown_30d numeric(5,4),
    status character varying(50) DEFAULT 'active'::character varying NOT NULL,
    notes text,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: strategy_reviews; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.strategy_reviews (
    id text NOT NULL,
    watchlist_item_id text NOT NULL,
    snapshot_id text,
    symbol text NOT NULL,
    review_text text NOT NULL,
    provider text NOT NULL,
    is_valid boolean NOT NULL,
    disagreement boolean NOT NULL,
    token_usage jsonb,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    review_pair_id text,
    disagreement_severity text,
    provider_disagreement boolean DEFAULT false,
    agreement_score real,
    agent_run_id text,
    CONSTRAINT strategy_reviews_disagreement_severity_check CHECK ((disagreement_severity = ANY (ARRAY['none'::text, 'minor'::text, 'major'::text])))
);


--
-- Name: strategy_seeds; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.strategy_seeds (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    symbol character varying(10) NOT NULL,
    thesis text NOT NULL,
    confidence numeric(3,1) NOT NULL,
    agent_run_id uuid,
    source_type character varying(50) DEFAULT 'discovery'::character varying NOT NULL,
    source_data jsonb,
    status character varying(50) DEFAULT 'pending'::character varying NOT NULL,
    strategy_id uuid,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    processed_at timestamp with time zone,
    CONSTRAINT strategy_seeds_confidence_check CHECK (((confidence >= (1)::numeric) AND (confidence <= (10)::numeric))),
    CONSTRAINT valid_status CHECK (((status)::text = ANY ((ARRAY['pending'::character varying, 'processing'::character varying, 'converted'::character varying, 'rejected'::character varying])::text[])))
);


--
-- Name: strategy_signals; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.strategy_signals (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    strategy_id uuid NOT NULL,
    symbol character varying(10) NOT NULL,
    signal_date date NOT NULL,
    signal_type character varying(10) NOT NULL,
    signal_strength integer NOT NULL,
    reasons text[],
    market_data jsonb,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT strategy_signals_signal_strength_check CHECK (((signal_strength >= 0) AND (signal_strength <= 10))),
    CONSTRAINT strategy_signals_signal_type_check CHECK (((signal_type)::text = ANY ((ARRAY['BUY'::character varying, 'HOLD'::character varying, 'SELL'::character varying, 'AVOID'::character varying])::text[])))
);


--
-- Name: symbol_risk_metrics; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.symbol_risk_metrics (
    id integer NOT NULL,
    symbol character varying(20) NOT NULL,
    as_of_date date NOT NULL,
    var_95 numeric(10,6),
    var_99 numeric(10,6),
    cvar_95 numeric(10,6),
    cvar_99 numeric(10,6),
    beta_90d numeric(8,4),
    beta_1y numeric(8,4),
    beta_2y numeric(8,4),
    r_squared_1y numeric(6,4),
    observations integer,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: TABLE symbol_risk_metrics; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.symbol_risk_metrics IS 'Daily risk metrics per symbol: VaR, CVaR, multi-window betas';


--
-- Name: COLUMN symbol_risk_metrics.var_95; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.symbol_risk_metrics.var_95 IS '95% daily VaR - max expected loss 95% of the time';


--
-- Name: COLUMN symbol_risk_metrics.cvar_95; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.symbol_risk_metrics.cvar_95 IS 'Conditional VaR - average loss beyond VaR threshold';


--
-- Name: COLUMN symbol_risk_metrics.beta_1y; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.symbol_risk_metrics.beta_1y IS '1-year beta vs SPY (less noisy than 90-day)';


--
-- Name: symbol_risk_metrics_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.symbol_risk_metrics_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: symbol_risk_metrics_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.symbol_risk_metrics_id_seq OWNED BY public.symbol_risk_metrics.id;


--
-- Name: symbol_workflow_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.symbol_workflow_events (
    id uuid NOT NULL,
    symbol text NOT NULL,
    from_stage text,
    to_stage text NOT NULL,
    note text NOT NULL,
    created_by text NOT NULL,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    metadata json DEFAULT '{}'::json NOT NULL,
    CONSTRAINT ck_symbol_workflow_events_to_stage CHECK ((to_stage = ANY (ARRAY['discover'::text, 'thesis_ready'::text, 'tracked'::text, 'live'::text, 'review_due'::text, 'invalidated'::text, 'exited'::text])))
);


--
-- Name: symbol_workflows; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.symbol_workflows (
    symbol text NOT NULL,
    current_stage text NOT NULL,
    notes text,
    updated_by text DEFAULT 'system'::text NOT NULL,
    last_transition_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    next_review_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    metadata json DEFAULT '{}'::json NOT NULL,
    CONSTRAINT ck_symbol_workflows_stage CHECK ((current_stage = ANY (ARRAY['discover'::text, 'thesis_ready'::text, 'tracked'::text, 'live'::text, 'review_due'::text, 'invalidated'::text, 'exited'::text])))
);


--
-- Name: symbols; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.symbols (
    symbol character varying(20) NOT NULL,
    company_name text,
    sector character varying(100),
    industry character varying(150),
    exchange character varying(20),
    security_type character varying(20) DEFAULT 'equity'::character varying,
    is_active boolean DEFAULT true,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: table_registry; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.table_registry (
    table_name text NOT NULL,
    table_type text,
    description text,
    row_count bigint DEFAULT 0,
    last_written timestamp with time zone,
    created_at timestamp with time zone DEFAULT now()
);


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
-- Name: taskset_id_sequence; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.taskset_id_sequence
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: technical_indicators; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.technical_indicators (
    symbol text NOT NULL,
    date date NOT NULL,
    rsi_14 double precision,
    macd double precision,
    macd_signal double precision,
    macd_histogram double precision,
    bb_upper double precision,
    bb_middle double precision,
    bb_lower double precision,
    sma_20 double precision,
    sma_50 double precision,
    sma_200 double precision,
    ema_20 double precision,
    ema_50 double precision,
    ema_200 double precision,
    atr_14 double precision,
    stoch_k double precision,
    stoch_d double precision,
    calculated_at timestamp with time zone NOT NULL,
    sma_5 double precision
);


--
-- Name: COLUMN technical_indicators.sma_5; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.technical_indicators.sma_5 IS '5-day simple moving average (used for declining trend detection in AVOID signals)';


--
-- Name: thesis_versions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.thesis_versions (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    thesis_id uuid NOT NULL,
    version integer NOT NULL,
    snapshot jsonb NOT NULL,
    change_reason character varying(50),
    created_at timestamp with time zone DEFAULT now(),
    CONSTRAINT thesis_versions_change_reason_check CHECK (((change_reason)::text = ANY ((ARRAY['created'::character varying, 'updated'::character varying, 'invalidated'::character varying, 'superseded'::character varying])::text[])))
);


--
-- Name: TABLE thesis_versions; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.thesis_versions IS 'Append-only version history for thesis changes';


--
-- Name: user_article_feedback; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.user_article_feedback (
    id integer NOT NULL,
    user_id character varying(255) DEFAULT 'default'::character varying NOT NULL,
    article_url text NOT NULL,
    article_hash character varying(64) NOT NULL,
    vendor character varying(100) NOT NULL,
    is_useful boolean NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    sentiment_override double precision,
    CONSTRAINT user_article_feedback_sentiment_override_check CHECK (((sentiment_override >= ('-1.0'::numeric)::double precision) AND (sentiment_override <= (1.0)::double precision)))
);


--
-- Name: TABLE user_article_feedback; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.user_article_feedback IS 'User feedback (thumbs up/down) on news articles for quality training';


--
-- Name: COLUMN user_article_feedback.user_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.user_article_feedback.user_id IS 'User identifier (references user_preferences.id)';


--
-- Name: COLUMN user_article_feedback.article_url; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.user_article_feedback.article_url IS 'Full URL of the article';


--
-- Name: COLUMN user_article_feedback.article_hash; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.user_article_feedback.article_hash IS 'Content hash for deduplication (from news_cache.content_hash)';


--
-- Name: COLUMN user_article_feedback.vendor; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.user_article_feedback.vendor IS 'News vendor/source that provided the article';


--
-- Name: COLUMN user_article_feedback.is_useful; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.user_article_feedback.is_useful IS 'TRUE=thumbs up (useful), FALSE=thumbs down (not useful)';


--
-- Name: COLUMN user_article_feedback.created_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.user_article_feedback.created_at IS 'When feedback was submitted';


--
-- Name: COLUMN user_article_feedback.sentiment_override; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.user_article_feedback.sentiment_override IS 'User-corrected sentiment score (-1.0 to 1.0), overrides original sentiment when provided';


--
-- Name: user_article_feedback_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.user_article_feedback_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: user_article_feedback_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.user_article_feedback_id_seq OWNED BY public.user_article_feedback.id;


--
-- Name: user_preferences; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.user_preferences (
    id text NOT NULL,
    risk_tolerance integer NOT NULL,
    allow_long boolean DEFAULT true,
    allow_short boolean DEFAULT false,
    allow_options boolean DEFAULT false,
    allow_crypto boolean DEFAULT false,
    allow_futures boolean DEFAULT false,
    max_position_size_pct double precision DEFAULT 10.0,
    watchlist_refresh_minutes integer DEFAULT 5,
    watchlist_auto_expand boolean DEFAULT false,
    watchlist_price_weight double precision DEFAULT 50.0,
    watchlist_technical_weight double precision DEFAULT 50.0,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    display_timezone character varying DEFAULT 'America/New_York'::character varying,
    default_refresh_minutes integer DEFAULT 15,
    watchlist_refresh_override integer,
    portfolio_refresh_override integer,
    news_refresh_override integer,
    frontend_poll_interval integer DEFAULT 30,
    watchlist_risk_budget integer DEFAULT 500,
    watchlist_show_news boolean DEFAULT true,
    watchlist_score_weights jsonb DEFAULT '{"price": 33, "technical": 33, "fundamental": 34}'::jsonb,
    watchlist_avoid_threshold integer DEFAULT 2,
    watchlist_volume_surge_multiplier double precision DEFAULT 1.5,
    news_lookback_hours integer DEFAULT 6,
    news_max_articles integer DEFAULT 10,
    source_duplicate_weight double precision DEFAULT 0.30,
    source_diversity_weight double precision DEFAULT 0.25,
    source_confidence_weight double precision DEFAULT 0.20,
    source_freshness_weight double precision DEFAULT 0.15,
    source_feedback_weight double precision DEFAULT 0.10,
    filter_neutral_articles boolean DEFAULT false,
    news_profiling_interval_hours integer DEFAULT 12,
    CONSTRAINT check_avoid_threshold_range CHECK (((watchlist_avoid_threshold >= 1) AND (watchlist_avoid_threshold <= 4))),
    CONSTRAINT check_display_timezone CHECK (((display_timezone)::text = ANY ((ARRAY['America/New_York'::character varying, 'America/Chicago'::character varying, 'America/Denver'::character varying, 'America/Los_Angeles'::character varying, 'America/Anchorage'::character varying, 'Pacific/Honolulu'::character varying])::text[]))),
    CONSTRAINT check_volume_surge_multiplier_range CHECK (((watchlist_volume_surge_multiplier >= (1.0)::double precision) AND (watchlist_volume_surge_multiplier <= (3.0)::double precision))),
    CONSTRAINT user_preferences_news_profiling_interval_hours_check CHECK ((news_profiling_interval_hours > 0)),
    CONSTRAINT user_preferences_source_confidence_weight_check CHECK ((source_confidence_weight >= (0.0)::double precision)),
    CONSTRAINT user_preferences_source_diversity_weight_check CHECK ((source_diversity_weight >= (0.0)::double precision)),
    CONSTRAINT user_preferences_source_duplicate_weight_check CHECK ((source_duplicate_weight >= (0.0)::double precision)),
    CONSTRAINT user_preferences_source_feedback_weight_check CHECK ((source_feedback_weight >= (0.0)::double precision)),
    CONSTRAINT user_preferences_source_freshness_weight_check CHECK ((source_freshness_weight >= (0.0)::double precision))
);


--
-- Name: COLUMN user_preferences.watchlist_score_weights; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.user_preferences.watchlist_score_weights IS 'Top-level weights: price, technical, fundamental (must sum to 100)';


--
-- Name: COLUMN user_preferences.watchlist_avoid_threshold; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.user_preferences.watchlist_avoid_threshold IS 'Number of declining indicators needed to trigger AVOID signal (1-4, default 2)';


--
-- Name: COLUMN user_preferences.watchlist_volume_surge_multiplier; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.user_preferences.watchlist_volume_surge_multiplier IS 'Multiplier above average volume to consider it a surge (default 1.5 = 1.5x average)';


--
-- Name: COLUMN user_preferences.source_duplicate_weight; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.user_preferences.source_duplicate_weight IS 'Weight for duplicate penalty in quality score (0-1, normalized on use)';


--
-- Name: COLUMN user_preferences.source_diversity_weight; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.user_preferences.source_diversity_weight IS 'Weight for headline diversity in quality score (0-1, normalized on use)';


--
-- Name: COLUMN user_preferences.source_confidence_weight; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.user_preferences.source_confidence_weight IS 'Weight for sentiment confidence in quality score (0-1, normalized on use)';


--
-- Name: COLUMN user_preferences.source_freshness_weight; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.user_preferences.source_freshness_weight IS 'Weight for article freshness in quality score (0-1, normalized on use)';


--
-- Name: COLUMN user_preferences.source_feedback_weight; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.user_preferences.source_feedback_weight IS 'Weight for user feedback in quality score (0-1, normalized on use)';


--
-- Name: COLUMN user_preferences.filter_neutral_articles; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.user_preferences.filter_neutral_articles IS 'If TRUE, hide neutral articles (sentiment between ±0.2)';


--
-- Name: COLUMN user_preferences.news_profiling_interval_hours; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.user_preferences.news_profiling_interval_hours IS 'How often to run source quality profiling (in hours, default 12)';


--
-- Name: v_slippage_analysis; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.v_slippage_analysis AS
 SELECT symbol,
    transaction_type,
    count(*) AS trade_count,
    avg(slippage_bps) AS avg_slippage_bps,
    max(slippage_bps) AS max_slippage_bps,
    min(slippage_bps) AS min_slippage_bps,
    sum(slippage_amount) AS total_slippage_cost,
    avg(
        CASE
            WHEN (adv > (0)::double precision) THEN (((shares)::double precision / adv) * (100)::double precision)
            ELSE NULL::double precision
        END) AS avg_pct_of_adv
   FROM public.paper_trade_transactions
  WHERE (slippage_bps IS NOT NULL)
  GROUP BY symbol, transaction_type;


--
-- Name: v_slippage_by_source; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.v_slippage_by_source AS
 SELECT
        CASE
            WHEN (agent_run_id IS NOT NULL) THEN 'Agent'::text
            ELSE 'Manual'::text
        END AS trade_source,
    count(DISTINCT trade_id) AS trade_count,
    avg(slippage_bps) AS avg_slippage_bps,
    sum(slippage_amount) AS total_slippage_cost,
    sum(
        CASE
            WHEN (transaction_type = 'ENTRY'::text) THEN slippage_amount
            ELSE (0)::double precision
        END) AS entry_slippage_cost,
    sum(
        CASE
            WHEN (transaction_type = 'EXIT'::text) THEN slippage_amount
            ELSE (0)::double precision
        END) AS exit_slippage_cost
   FROM public.paper_trade_transactions ptt
  GROUP BY
        CASE
            WHEN (agent_run_id IS NOT NULL) THEN 'Agent'::text
            ELSE 'Manual'::text
        END;


--
-- Name: valuation_metrics; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.valuation_metrics (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    symbol character varying(20) NOT NULL,
    as_of_date timestamp with time zone DEFAULT now() NOT NULL,
    pe_ratio_trailing numeric(12,2),
    pe_ratio_forward numeric(12,2),
    ps_ratio numeric(12,2),
    pb_ratio numeric(12,2),
    peg_ratio numeric(12,2),
    dividend_yield numeric(8,4),
    payout_ratio numeric(8,4),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: TABLE valuation_metrics; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.valuation_metrics IS 'Normalized valuation ratios from reference_cache';


--
-- Name: vision_content; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.vision_content (
    id integer NOT NULL,
    content_type text NOT NULL,
    content_key text NOT NULL,
    title text,
    content text NOT NULL,
    order_num integer DEFAULT 0,
    metadata jsonb,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: TABLE vision_content; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.vision_content IS 'Stores narrative content from VISION.md: mission, vision, principles, success metrics, roadmap.';


--
-- Name: COLUMN vision_content.content_type; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.vision_content.content_type IS 'Type of content: mission, vision, principle, success_metric, roadmap_phase';


--
-- Name: COLUMN vision_content.content_key; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.vision_content.content_key IS 'Unique key within type: core, principle-1, phase-1, system, etc.';


--
-- Name: COLUMN vision_content.metadata; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.vision_content.metadata IS 'Additional structured data like bullet points, status, completion percentage';


--
-- Name: vision_content_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.vision_content_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: vision_content_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.vision_content_id_seq OWNED BY public.vision_content.id;


--
-- Name: vision_goal_details; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.vision_goal_details (
    id integer NOT NULL,
    goal_code text NOT NULL,
    detail_type text NOT NULL,
    content text NOT NULL,
    order_num integer DEFAULT 0,
    metadata jsonb,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: TABLE vision_goal_details; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.vision_goal_details IS 'Detailed content for vision goals: objectives, feature bullets, success criteria from VISION.md';


--
-- Name: COLUMN vision_goal_details.goal_code; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.vision_goal_details.goal_code IS 'FK to vision_goals.code (VG-INTEL, VG-AUTO, etc.)';


--
-- Name: COLUMN vision_goal_details.detail_type; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.vision_goal_details.detail_type IS 'Type: objective (1 per goal), feature (multiple), success_criterion (multiple)';


--
-- Name: COLUMN vision_goal_details.content; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.vision_goal_details.content IS 'The actual content text';


--
-- Name: COLUMN vision_goal_details.order_num; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.vision_goal_details.order_num IS 'Display order within goal/type';


--
-- Name: vision_goal_details_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.vision_goal_details_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: vision_goal_details_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.vision_goal_details_id_seq OWNED BY public.vision_goal_details.id;


--
-- Name: vision_goals; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.vision_goals (
    code text NOT NULL,
    name text NOT NULL,
    description text,
    category text,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: TABLE vision_goals; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.vision_goals IS 'Lookup table for VISION.md strategic goals. Linked from feature_capabilities.vision_goals array.';


--
-- Name: COLUMN vision_goals.code; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.vision_goals.code IS 'Unique code like VG-INTEL, VG-AUTO. Used in feature_capabilities.vision_goals array.';


--
-- Name: COLUMN vision_goals.name; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.vision_goals.name IS 'Human-readable name like "Market Intelligence", "Autonomous Operation".';


--
-- Name: COLUMN vision_goals.description; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.vision_goals.description IS 'Full description of what this goal means and why it matters.';


--
-- Name: COLUMN vision_goals.category; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.vision_goals.category IS 'Grouping category for organization: intelligence, automation, portfolio, validation, reliability, ux, quality.';


--
-- Name: watchlist_daily_reports; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.watchlist_daily_reports (
    id text DEFAULT (gen_random_uuid())::text NOT NULL,
    report_date date NOT NULL,
    symbols_added jsonb DEFAULT '[]'::jsonb NOT NULL,
    symbols_removed jsonb DEFAULT '[]'::jsonb NOT NULL,
    score_changes jsonb DEFAULT '[]'::jsonb NOT NULL,
    generated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: watchlist_items; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.watchlist_items (
    id text NOT NULL,
    symbol text NOT NULL,
    metadata jsonb,
    note text,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    source text DEFAULT 'manual'::text,
    added_by text DEFAULT 'user'::text NOT NULL,
    added_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT watchlist_items_source_check CHECK ((source = ANY (ARRAY['manual'::text, 'portfolio'::text])))
);


--
-- Name: watchlist_narrative; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.watchlist_narrative (
    snapshot_id uuid NOT NULL,
    narrative_headline text,
    narrative_why_bullets jsonb,
    narrative_company_health jsonb,
    narrative_technical jsonb,
    narrative_action_plan text,
    narrative_position_sizing text,
    narrative_special_notes text,
    entry_price double precision,
    stop_loss double precision,
    profit_target double precision,
    position_size_shares integer,
    recommended_style text,
    style_confidence integer,
    optimal_holding_period text,
    risk_level text,
    company_health text
);


--
-- Name: TABLE watchlist_narrative; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.watchlist_narrative IS 'AI-generated narratives linked to snapshots';


--
-- Name: watchlist_news_summary; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.watchlist_news_summary (
    snapshot_id uuid NOT NULL,
    news_sentiment_score double precision,
    recent_news_headlines jsonb,
    sector_score double precision,
    competitor_score double precision,
    earnings_date timestamp with time zone,
    earnings_days_away integer
);


--
-- Name: TABLE watchlist_news_summary; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.watchlist_news_summary IS 'News and earnings data linked to snapshots';


--
-- Name: watchlist_snapshots; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.watchlist_snapshots (
    item_id text NOT NULL,
    fetched_at timestamp with time zone NOT NULL,
    price double precision,
    change_pct double precision,
    beta double precision,
    volatility double precision,
    news_score double precision,
    technical_score double precision,
    fundamental_score double precision,
    ai_score double precision,
    ai_confidence double precision,
    sector_score double precision,
    competitor_score double precision,
    overall_score double precision,
    raw_metrics jsonb,
    is_stale boolean DEFAULT false NOT NULL,
    signal_type text,
    signal_strength integer,
    narrative_headline text,
    narrative_why_bullets jsonb,
    narrative_company_health jsonb,
    narrative_technical jsonb,
    narrative_action_plan text,
    narrative_position_sizing text,
    narrative_special_notes text,
    entry_price double precision,
    stop_loss double precision,
    profit_target double precision,
    position_size_shares integer,
    recommended_style text,
    style_confidence integer,
    optimal_holding_period text,
    risk_level text,
    company_health text,
    earnings_date date,
    earnings_days_away integer,
    news_sentiment_score double precision,
    recent_news_headlines jsonb,
    volume_relative double precision,
    timeframe_short_aligned boolean DEFAULT false,
    timeframe_long_aligned boolean DEFAULT false,
    percentile_rank_30d double precision,
    CONSTRAINT check_percentile_rank_30d_range CHECK (((percentile_rank_30d IS NULL) OR ((percentile_rank_30d >= (0)::double precision) AND (percentile_rank_30d <= (100)::double precision)))),
    CONSTRAINT watchlist_snapshots_company_health_check CHECK ((company_health = ANY (ARRAY['EXCELLENT'::text, 'GOOD'::text, 'WEAK'::text]))),
    CONSTRAINT watchlist_snapshots_news_sentiment_score_check CHECK (((news_sentiment_score >= ('-1.0'::numeric)::double precision) AND (news_sentiment_score <= (1.0)::double precision))),
    CONSTRAINT watchlist_snapshots_recommended_style_check CHECK ((recommended_style = ANY (ARRAY['Index'::text, 'Trend'::text, 'Value'::text, 'Swing'::text, 'Event'::text]))),
    CONSTRAINT watchlist_snapshots_risk_level_check CHECK ((risk_level = ANY (ARRAY['Low'::text, 'Medium-Low'::text, 'Medium'::text, 'High'::text]))),
    CONSTRAINT watchlist_snapshots_signal_strength_check CHECK (((signal_strength >= 0) AND (signal_strength <= 10))),
    CONSTRAINT watchlist_snapshots_signal_type_check CHECK ((signal_type = ANY (ARRAY['BUY'::text, 'HOLD'::text, 'AVOID'::text]))),
    CONSTRAINT watchlist_snapshots_style_confidence_check CHECK (((style_confidence >= 0) AND (style_confidence <= 10)))
);


--
-- Name: COLUMN watchlist_snapshots.volume_relative; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.watchlist_snapshots.volume_relative IS 'Current volume / 50-day average volume (e.g., 2.3 = 2.3x above average)';


--
-- Name: COLUMN watchlist_snapshots.timeframe_short_aligned; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.watchlist_snapshots.timeframe_short_aligned IS 'Short-term alignment: price > SMA_20 > SMA_50 (bullish short-term setup)';


--
-- Name: COLUMN watchlist_snapshots.timeframe_long_aligned; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.watchlist_snapshots.timeframe_long_aligned IS 'Long-term alignment: SMA_50 > SMA_200 (bullish long-term trend)';


--
-- Name: COLUMN watchlist_snapshots.percentile_rank_30d; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.watchlist_snapshots.percentile_rank_30d IS 'Overall score percentile rank vs 30-day history (0-100)';


--
-- Name: watchlist_snapshots_core; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.watchlist_snapshots_core (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    item_id text NOT NULL,
    fetched_at timestamp with time zone DEFAULT now() NOT NULL,
    price double precision,
    change_pct double precision,
    overall_score double precision,
    technical_score double precision,
    fundamental_score double precision,
    news_score double precision,
    ai_score double precision,
    ai_confidence double precision,
    is_stale boolean DEFAULT false,
    signal_type text,
    signal_strength integer,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: TABLE watchlist_snapshots_core; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.watchlist_snapshots_core IS 'Normalized core snapshot data (phase 1 of split)';


--
-- Name: watchlist_technical_metrics; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.watchlist_technical_metrics (
    snapshot_id uuid NOT NULL,
    raw_metrics jsonb,
    beta double precision,
    volatility double precision,
    volume_relative double precision,
    timeframe_short_aligned boolean DEFAULT false,
    timeframe_long_aligned boolean DEFAULT false,
    percentile_rank_30d double precision
);


--
-- Name: TABLE watchlist_technical_metrics; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.watchlist_technical_metrics IS 'Technical indicators linked to snapshots';


--
-- Name: watchlist_snapshots_v; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.watchlist_snapshots_v AS
 SELECT c.id,
    c.item_id,
    c.fetched_at,
    c.price,
    c.change_pct,
    c.overall_score,
    c.technical_score,
    c.fundamental_score,
    c.news_score,
    c.ai_score,
    c.ai_confidence,
    c.is_stale,
    c.signal_type,
    c.signal_strength,
    t.raw_metrics,
    t.beta,
    t.volatility,
    t.volume_relative,
    t.timeframe_short_aligned,
    t.timeframe_long_aligned,
    t.percentile_rank_30d,
    n.narrative_headline,
    n.narrative_why_bullets,
    n.narrative_company_health,
    n.narrative_technical,
    n.narrative_action_plan,
    n.narrative_position_sizing,
    n.narrative_special_notes,
    n.entry_price,
    n.stop_loss,
    n.profit_target,
    n.position_size_shares,
    n.recommended_style,
    n.style_confidence,
    n.optimal_holding_period,
    n.risk_level,
    n.company_health,
    ns.news_sentiment_score,
    ns.recent_news_headlines,
    ns.sector_score,
    ns.competitor_score,
    ns.earnings_date,
    ns.earnings_days_away
   FROM (((public.watchlist_snapshots_core c
     LEFT JOIN public.watchlist_technical_metrics t ON ((t.snapshot_id = c.id)))
     LEFT JOIN public.watchlist_narrative n ON ((n.snapshot_id = c.id)))
     LEFT JOIN public.watchlist_news_summary ns ON ((ns.snapshot_id = c.id)));


--
-- Name: VIEW watchlist_snapshots_v; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON VIEW public.watchlist_snapshots_v IS 'Backwards-compatible view joining all snapshot tables';


--
-- Name: watchlist_thesis; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.watchlist_thesis (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    symbol character varying(20) NOT NULL,
    version integer DEFAULT 1 NOT NULL,
    status character varying(20) DEFAULT 'active'::character varying NOT NULL,
    action character varying(10) NOT NULL,
    core_reasons jsonb NOT NULL,
    key_catalysts jsonb NOT NULL,
    risks jsonb NOT NULL,
    value_drivers jsonb,
    expected_return_pct numeric(5,2),
    expected_timeframe_days integer,
    claude_validation jsonb,
    gemini_validation jsonb,
    cross_validation_score numeric(3,2),
    invalidation_reason text,
    invalidated_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    CONSTRAINT watchlist_thesis_action_check CHECK (((action)::text = ANY ((ARRAY['BUY'::character varying, 'HOLD'::character varying, 'SELL'::character varying])::text[]))),
    CONSTRAINT watchlist_thesis_cross_validation_score_check CHECK (((cross_validation_score >= 0.0) AND (cross_validation_score <= 1.0))),
    CONSTRAINT watchlist_thesis_status_check CHECK (((status)::text = ANY ((ARRAY['active'::character varying, 'invalidated'::character varying, 'flagged_for_review'::character varying])::text[])))
);


--
-- Name: TABLE watchlist_thesis; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.watchlist_thesis IS 'Investment theses for watchlist symbols with dual AI validation';


--
-- Name: COLUMN watchlist_thesis.core_reasons; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.watchlist_thesis.core_reasons IS 'Array of {reason: str, confidence: float} - core investment rationale';


--
-- Name: COLUMN watchlist_thesis.key_catalysts; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.watchlist_thesis.key_catalysts IS 'Array of {catalyst: str, expected_date: str|null, impact: str} - catalysts that will drive value';


--
-- Name: COLUMN watchlist_thesis.risks; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.watchlist_thesis.risks IS 'Array of {risk: str, severity: high|medium|low, mitigation: str|null} - key risks and mitigations';


--
-- Name: COLUMN watchlist_thesis.value_drivers; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.watchlist_thesis.value_drivers IS 'JSON object describing market_size, company_position, upside_potential, competitive_moat';


--
-- Name: COLUMN watchlist_thesis.claude_validation; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.watchlist_thesis.claude_validation IS 'Claude AI validation result: {approved: bool, confidence: float, review_summary: str, issues: [str]}';


--
-- Name: COLUMN watchlist_thesis.gemini_validation; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.watchlist_thesis.gemini_validation IS 'Gemini AI validation result: {approved: bool, confidence: float, review_summary: str, issues: [str]}';


--
-- Name: COLUMN watchlist_thesis.cross_validation_score; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.watchlist_thesis.cross_validation_score IS 'Agreement score between Claude and Gemini validators (0.0-1.0)';


--
-- Name: yield_curve; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.yield_curve (
    id bigint NOT NULL,
    observation_date date NOT NULL,
    yield_3m double precision,
    yield_2y double precision,
    yield_5y double precision,
    yield_10y double precision,
    yield_30y double precision,
    spread_10y_2y double precision,
    spread_10y_3m double precision,
    is_inverted boolean GENERATED ALWAYS AS ((spread_10y_2y < (0)::double precision)) STORED,
    source character varying(50) DEFAULT 'fred'::character varying,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: yield_curve_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.yield_curve_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: yield_curve_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.yield_curve_id_seq OWNED BY public.yield_curve.id;


--
-- Name: analyst_revisions id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.analyst_revisions ALTER COLUMN id SET DEFAULT nextval('public.analyst_revisions_id_seq'::regclass);


--
-- Name: artifacts id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.artifacts ALTER COLUMN id SET DEFAULT nextval('public.artifacts_id_seq'::regclass);


--
-- Name: cash_flow_metrics id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cash_flow_metrics ALTER COLUMN id SET DEFAULT nextval('public.cash_flow_metrics_id_seq'::regclass);


--
-- Name: claude_progress_log id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.claude_progress_log ALTER COLUMN id SET DEFAULT nextval('public.claude_progress_log_id_seq'::regclass);


--
-- Name: corporate_actions id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.corporate_actions ALTER COLUMN id SET DEFAULT nextval('public.corporate_actions_id_seq'::regclass);


--
-- Name: criteria_verification_runs id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.criteria_verification_runs ALTER COLUMN id SET DEFAULT nextval('public.criteria_verification_runs_id_seq'::regclass);


--
-- Name: deletion_audit id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.deletion_audit ALTER COLUMN id SET DEFAULT nextval('public.deletion_audit_id_seq'::regclass);


--
-- Name: earnings_surprises id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.earnings_surprises ALTER COLUMN id SET DEFAULT nextval('public.earnings_surprises_id_seq'::regclass);


--
-- Name: file_audit id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.file_audit ALTER COLUMN id SET DEFAULT nextval('public.file_audit_id_seq'::regclass);


--
-- Name: gap_analysis_history analysis_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.gap_analysis_history ALTER COLUMN analysis_id SET DEFAULT nextval('public.gap_analysis_history_analysis_id_seq'::regclass);


--
-- Name: insider_transactions id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.insider_transactions ALTER COLUMN id SET DEFAULT nextval('public.insider_transactions_id_seq'::regclass);


--
-- Name: institutional_holdings id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.institutional_holdings ALTER COLUMN id SET DEFAULT nextval('public.institutional_holdings_id_seq'::regclass);


--
-- Name: institutional_ownership_summary id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.institutional_ownership_summary ALTER COLUMN id SET DEFAULT nextval('public.institutional_ownership_summary_id_seq'::regclass);


--
-- Name: macro_indicators id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.macro_indicators ALTER COLUMN id SET DEFAULT nextval('public.macro_indicators_id_seq'::regclass);


--
-- Name: maintenance_log id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.maintenance_log ALTER COLUMN id SET DEFAULT nextval('public.maintenance_log_id_seq'::regclass);


--
-- Name: maintenance_stats id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.maintenance_stats ALTER COLUMN id SET DEFAULT nextval('public.maintenance_stats_id_seq'::regclass);


--
-- Name: market_events id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.market_events ALTER COLUMN id SET DEFAULT nextval('public.market_events_id_seq'::regclass);


--
-- Name: ml_model_metrics id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ml_model_metrics ALTER COLUMN id SET DEFAULT nextval('public.ml_model_metrics_id_seq'::regclass);


--
-- Name: ml_training_progress id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ml_training_progress ALTER COLUMN id SET DEFAULT nextval('public.ml_training_progress_id_seq'::regclass);


--
-- Name: news_cache id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.news_cache ALTER COLUMN id SET DEFAULT nextval('public.news_cache_id_seq'::regclass);


--
-- Name: news_summary_log id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.news_summary_log ALTER COLUMN id SET DEFAULT nextval('public.news_summary_log_id_seq'::regclass);


--
-- Name: portfolio_snapshots id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.portfolio_snapshots ALTER COLUMN id SET DEFAULT nextval('public.portfolio_snapshots_id_seq'::regclass);


--
-- Name: qa_issues id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.qa_issues ALTER COLUMN id SET DEFAULT nextval('public.qa_issues_id_seq'::regclass);


--
-- Name: qa_snapshots id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.qa_snapshots ALTER COLUMN id SET DEFAULT nextval('public.qa_snapshots_id_seq'::regclass);


--
-- Name: rules_validation_reports id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rules_validation_reports ALTER COLUMN id SET DEFAULT nextval('public.rules_validation_reports_id_seq'::regclass);


--
-- Name: settings_profiles id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.settings_profiles ALTER COLUMN id SET DEFAULT nextval('public.settings_profiles_id_seq'::regclass);


--
-- Name: short_interest id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.short_interest ALTER COLUMN id SET DEFAULT nextval('public.short_interest_id_seq'::regclass);


--
-- Name: sitemap_entries id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sitemap_entries ALTER COLUMN id SET DEFAULT nextval('public.sitemap_entries_id_seq'::regclass);


--
-- Name: sitemap_health_history id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sitemap_health_history ALTER COLUMN id SET DEFAULT nextval('public.sitemap_health_history_id_seq'::regclass);


--
-- Name: source_metrics id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.source_metrics ALTER COLUMN id SET DEFAULT nextval('public.source_metrics_id_seq'::regclass);


--
-- Name: symbol_risk_metrics id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.symbol_risk_metrics ALTER COLUMN id SET DEFAULT nextval('public.symbol_risk_metrics_id_seq'::regclass);


--
-- Name: user_article_feedback id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_article_feedback ALTER COLUMN id SET DEFAULT nextval('public.user_article_feedback_id_seq'::regclass);


--
-- Name: vision_content id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vision_content ALTER COLUMN id SET DEFAULT nextval('public.vision_content_id_seq'::regclass);


--
-- Name: vision_goal_details id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vision_goal_details ALTER COLUMN id SET DEFAULT nextval('public.vision_goal_details_id_seq'::regclass);


--
-- Name: yield_curve id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.yield_curve ALTER COLUMN id SET DEFAULT nextval('public.yield_curve_id_seq'::regclass);


--
-- Name: agent_conversation_messages agent_conversation_messages_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_conversation_messages
    ADD CONSTRAINT agent_conversation_messages_pkey PRIMARY KEY (id);


--
-- Name: agent_messages agent_messages_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_messages
    ADD CONSTRAINT agent_messages_pkey PRIMARY KEY (id);


--
-- Name: agent_runs agent_runs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_runs
    ADD CONSTRAINT agent_runs_pkey PRIMARY KEY (id);


--
-- Name: agent_tool_calls agent_tool_calls_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_tool_calls
    ADD CONSTRAINT agent_tool_calls_pkey PRIMARY KEY (id);


--
-- Name: agent_workflows agent_workflows_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_workflows
    ADD CONSTRAINT agent_workflows_pkey PRIMARY KEY (id);


--
-- Name: alembic_version alembic_version_pkc; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alembic_version
    ADD CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num);


--
-- Name: analyst_revisions analyst_revisions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.analyst_revisions
    ADD CONSTRAINT analyst_revisions_pkey PRIMARY KEY (id);


--
-- Name: analyst_revisions analyst_revisions_symbol_metric_period_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.analyst_revisions
    ADD CONSTRAINT analyst_revisions_symbol_metric_period_key UNIQUE (symbol, metric, period);


--
-- Name: artifacts artifacts_artifact_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.artifacts
    ADD CONSTRAINT artifacts_artifact_id_key UNIQUE (artifact_id);


--
-- Name: artifacts artifacts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.artifacts
    ADD CONSTRAINT artifacts_pkey PRIMARY KEY (id);


--
-- Name: automation_preferences automation_preferences_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.automation_preferences
    ADD CONSTRAINT automation_preferences_pkey PRIMARY KEY (id);


--
-- Name: backtest_equity backtest_equity_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.backtest_equity
    ADD CONSTRAINT backtest_equity_pkey PRIMARY KEY (id);


--
-- Name: backtest_equity backtest_equity_run_date_unique; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.backtest_equity
    ADD CONSTRAINT backtest_equity_run_date_unique UNIQUE (run_id, date);


--
-- Name: backtest_runs backtest_runs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.backtest_runs
    ADD CONSTRAINT backtest_runs_pkey PRIMARY KEY (id);


--
-- Name: backtest_trades backtest_trades_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.backtest_trades
    ADD CONSTRAINT backtest_trades_pkey PRIMARY KEY (id);


--
-- Name: cash_flow_metrics cash_flow_metrics_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cash_flow_metrics
    ADD CONSTRAINT cash_flow_metrics_pkey PRIMARY KEY (id);


--
-- Name: cash_flow_metrics cash_flow_metrics_symbol_as_of_date_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cash_flow_metrics
    ADD CONSTRAINT cash_flow_metrics_symbol_as_of_date_key UNIQUE (symbol, as_of_date);


--
-- Name: claude_progress_log claude_progress_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.claude_progress_log
    ADD CONSTRAINT claude_progress_log_pkey PRIMARY KEY (id);


--
-- Name: corporate_actions corporate_actions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.corporate_actions
    ADD CONSTRAINT corporate_actions_pkey PRIMARY KEY (id);


--
-- Name: corporate_actions corporate_actions_symbol_action_type_action_date_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.corporate_actions
    ADD CONSTRAINT corporate_actions_symbol_action_type_action_date_key UNIQUE (symbol, action_type, action_date);


--
-- Name: criteria_verification_runs criteria_verification_runs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.criteria_verification_runs
    ADD CONSTRAINT criteria_verification_runs_pkey PRIMARY KEY (id);


--
-- Name: cross_validation_results cross_validation_results_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cross_validation_results
    ADD CONSTRAINT cross_validation_results_pkey PRIMARY KEY (id);


--
-- Name: day_bars day_bars_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.day_bars
    ADD CONSTRAINT day_bars_pkey PRIMARY KEY (symbol, date);


--
-- Name: deletion_audit deletion_audit_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.deletion_audit
    ADD CONSTRAINT deletion_audit_pkey PRIMARY KEY (id);


--
-- Name: earnings_surprises earnings_surprises_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.earnings_surprises
    ADD CONSTRAINT earnings_surprises_pkey PRIMARY KEY (id);


--
-- Name: earnings_surprises earnings_surprises_symbol_earnings_date_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.earnings_surprises
    ADD CONSTRAINT earnings_surprises_symbol_earnings_date_key UNIQUE (symbol, earnings_date);


--
-- Name: endpoint_catalog endpoint_catalog_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.endpoint_catalog
    ADD CONSTRAINT endpoint_catalog_pkey PRIMARY KEY (id);


--
-- Name: fear_greed_components fear_greed_components_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fear_greed_components
    ADD CONSTRAINT fear_greed_components_pkey PRIMARY KEY (as_of_date);


--
-- Name: fear_greed_daily fear_greed_daily_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fear_greed_daily
    ADD CONSTRAINT fear_greed_daily_pkey PRIMARY KEY (as_of_date);


--
-- Name: fear_greed_inputs fear_greed_inputs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fear_greed_inputs
    ADD CONSTRAINT fear_greed_inputs_pkey PRIMARY KEY (as_of_date);


--
-- Name: file_audit file_audit_path_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.file_audit
    ADD CONSTRAINT file_audit_path_key UNIQUE (path);


--
-- Name: file_audit file_audit_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.file_audit
    ADD CONSTRAINT file_audit_pkey PRIMARY KEY (id);


--
-- Name: financial_health_scores financial_health_scores_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.financial_health_scores
    ADD CONSTRAINT financial_health_scores_pkey PRIMARY KEY (id);


--
-- Name: gap_analysis_history gap_analysis_history_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.gap_analysis_history
    ADD CONSTRAINT gap_analysis_history_pkey PRIMARY KEY (analysis_id);


--
-- Name: household_confirmed_facts household_confirmed_facts_fact_key_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.household_confirmed_facts
    ADD CONSTRAINT household_confirmed_facts_fact_key_key UNIQUE (fact_key);


--
-- Name: household_confirmed_facts household_confirmed_facts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.household_confirmed_facts
    ADD CONSTRAINT household_confirmed_facts_pkey PRIMARY KEY (id);


--
-- Name: household_debt_obligations household_debt_obligations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.household_debt_obligations
    ADD CONSTRAINT household_debt_obligations_pkey PRIMARY KEY (id);


--
-- Name: household_document_requirements household_document_requirements_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.household_document_requirements
    ADD CONSTRAINT household_document_requirements_pkey PRIMARY KEY (id);


--
-- Name: household_document_reviews household_document_reviews_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.household_document_reviews
    ADD CONSTRAINT household_document_reviews_pkey PRIMARY KEY (id);


--
-- Name: household_document_signatures household_document_signatures_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.household_document_signatures
    ADD CONSTRAINT household_document_signatures_pkey PRIMARY KEY (id);


--
-- Name: household_documents household_documents_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.household_documents
    ADD CONSTRAINT household_documents_pkey PRIMARY KEY (id);


--
-- Name: household_housing_costs household_housing_costs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.household_housing_costs
    ADD CONSTRAINT household_housing_costs_pkey PRIMARY KEY (id);


--
-- Name: household_import_rows household_import_rows_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.household_import_rows
    ADD CONSTRAINT household_import_rows_pkey PRIMARY KEY (id);


--
-- Name: household_income_sources household_income_sources_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.household_income_sources
    ADD CONSTRAINT household_income_sources_pkey PRIMARY KEY (id);


--
-- Name: household_inferred_values household_inferred_values_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.household_inferred_values
    ADD CONSTRAINT household_inferred_values_pkey PRIMARY KEY (id);


--
-- Name: household_insurance_policies household_insurance_policies_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.household_insurance_policies
    ADD CONSTRAINT household_insurance_policies_pkey PRIMARY KEY (id);


--
-- Name: household_members household_members_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.household_members
    ADD CONSTRAINT household_members_pkey PRIMARY KEY (id);


--
-- Name: household_merchants household_merchants_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.household_merchants
    ADD CONSTRAINT household_merchants_pkey PRIMARY KEY (id);


--
-- Name: household_planned_expenses household_planned_expenses_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.household_planned_expenses
    ADD CONSTRAINT household_planned_expenses_pkey PRIMARY KEY (id);


--
-- Name: household_profiles household_profiles_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.household_profiles
    ADD CONSTRAINT household_profiles_pkey PRIMARY KEY (id);


--
-- Name: household_questions household_questions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.household_questions
    ADD CONSTRAINT household_questions_pkey PRIMARY KEY (id);


--
-- Name: household_retirement_income_sources household_retirement_income_sources_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.household_retirement_income_sources
    ADD CONSTRAINT household_retirement_income_sources_pkey PRIMARY KEY (id);


--
-- Name: household_transactions household_transactions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.household_transactions
    ADD CONSTRAINT household_transactions_pkey PRIMARY KEY (id);


--
-- Name: idea_outcomes idea_outcomes_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.idea_outcomes
    ADD CONSTRAINT idea_outcomes_pkey PRIMARY KEY (idea_id);


--
-- Name: insider_transactions insider_transactions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.insider_transactions
    ADD CONSTRAINT insider_transactions_pkey PRIMARY KEY (id);


--
-- Name: insider_transactions insider_transactions_symbol_insider_name_transaction_date_t_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.insider_transactions
    ADD CONSTRAINT insider_transactions_symbol_insider_name_transaction_date_t_key UNIQUE (symbol, insider_name, transaction_date, transaction_type, shares);


--
-- Name: institutional_holdings institutional_holdings_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.institutional_holdings
    ADD CONSTRAINT institutional_holdings_pkey PRIMARY KEY (id);


--
-- Name: institutional_holdings institutional_holdings_symbol_holder_name_report_date_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.institutional_holdings
    ADD CONSTRAINT institutional_holdings_symbol_holder_name_report_date_key UNIQUE (symbol, holder_name, report_date);


--
-- Name: institutional_ownership_summary institutional_ownership_summary_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.institutional_ownership_summary
    ADD CONSTRAINT institutional_ownership_summary_pkey PRIMARY KEY (id);


--
-- Name: institutional_ownership_summary institutional_ownership_summary_symbol_as_of_date_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.institutional_ownership_summary
    ADD CONSTRAINT institutional_ownership_summary_symbol_as_of_date_key UNIQUE (symbol, as_of_date);


--
-- Name: jenny_agent_evaluations jenny_agent_evaluations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.jenny_agent_evaluations
    ADD CONSTRAINT jenny_agent_evaluations_pkey PRIMARY KEY (id);


--
-- Name: jenny_agent_scorecards jenny_agent_scorecards_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.jenny_agent_scorecards
    ADD CONSTRAINT jenny_agent_scorecards_pkey PRIMARY KEY (agent_name);


--
-- Name: jenny_notifications jenny_notifications_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.jenny_notifications
    ADD CONSTRAINT jenny_notifications_pkey PRIMARY KEY (id);


--
-- Name: jenny_routines jenny_routines_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.jenny_routines
    ADD CONSTRAINT jenny_routines_pkey PRIMARY KEY (id);


--
-- Name: jenny_trade_reviews jenny_trade_reviews_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.jenny_trade_reviews
    ADD CONSTRAINT jenny_trade_reviews_pkey PRIMARY KEY (id);


--
-- Name: macro_indicators macro_indicators_indicator_name_observation_date_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.macro_indicators
    ADD CONSTRAINT macro_indicators_indicator_name_observation_date_key UNIQUE (indicator_name, observation_date);


--
-- Name: macro_indicators macro_indicators_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.macro_indicators
    ADD CONSTRAINT macro_indicators_pkey PRIMARY KEY (id);


--
-- Name: maintenance_log maintenance_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.maintenance_log
    ADD CONSTRAINT maintenance_log_pkey PRIMARY KEY (id);


--
-- Name: maintenance_stats maintenance_stats_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.maintenance_stats
    ADD CONSTRAINT maintenance_stats_pkey PRIMARY KEY (id);


--
-- Name: market_events market_events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.market_events
    ADD CONSTRAINT market_events_pkey PRIMARY KEY (id);


--
-- Name: ml_model_metrics ml_model_metrics_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ml_model_metrics
    ADD CONSTRAINT ml_model_metrics_pkey PRIMARY KEY (id);


--
-- Name: ml_training_progress ml_training_progress_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ml_training_progress
    ADD CONSTRAINT ml_training_progress_pkey PRIMARY KEY (id);


--
-- Name: ml_training_progress ml_training_progress_session_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ml_training_progress
    ADD CONSTRAINT ml_training_progress_session_id_key UNIQUE (session_id);


--
-- Name: news_cache news_cache_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.news_cache
    ADD CONSTRAINT news_cache_pkey PRIMARY KEY (id);


--
-- Name: news_summary_log news_summary_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.news_summary_log
    ADD CONSTRAINT news_summary_log_pkey PRIMARY KEY (id);


--
-- Name: options_market_metrics options_market_metrics_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.options_market_metrics
    ADD CONSTRAINT options_market_metrics_pkey PRIMARY KEY (as_of_date);


--
-- Name: paper_trade_transactions paper_trade_transactions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.paper_trade_transactions
    ADD CONSTRAINT paper_trade_transactions_pkey PRIMARY KEY (id);


--
-- Name: portfolio_accounts portfolio_accounts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.portfolio_accounts
    ADD CONSTRAINT portfolio_accounts_pkey PRIMARY KEY (id);


--
-- Name: portfolio_covariance portfolio_covariance_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.portfolio_covariance
    ADD CONSTRAINT portfolio_covariance_pkey PRIMARY KEY (symbol1, symbol2);


--
-- Name: portfolio_positions portfolio_positions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.portfolio_positions
    ADD CONSTRAINT portfolio_positions_pkey PRIMARY KEY (id);


--
-- Name: portfolio_snapshots portfolio_snapshots_account_date_unique; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.portfolio_snapshots
    ADD CONSTRAINT portfolio_snapshots_account_date_unique UNIQUE (account_id, snapshot_date);


--
-- Name: portfolio_snapshots portfolio_snapshots_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.portfolio_snapshots
    ADD CONSTRAINT portfolio_snapshots_pkey PRIMARY KEY (id);


--
-- Name: portfolio_volatility_cache portfolio_volatility_cache_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.portfolio_volatility_cache
    ADD CONSTRAINT portfolio_volatility_cache_pkey PRIMARY KEY (portfolio_id, weight_hash);


--
-- Name: price_cache price_cache_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.price_cache
    ADD CONSTRAINT price_cache_pkey PRIMARY KEY (symbol, cached_at);


--
-- Name: qa_issues qa_issues_issue_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.qa_issues
    ADD CONSTRAINT qa_issues_issue_id_key UNIQUE (issue_id);


--
-- Name: qa_issues qa_issues_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.qa_issues
    ADD CONSTRAINT qa_issues_pkey PRIMARY KEY (id);


--
-- Name: qa_snapshots qa_snapshots_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.qa_snapshots
    ADD CONSTRAINT qa_snapshots_pkey PRIMARY KEY (id);


--
-- Name: qa_snapshots qa_snapshots_snapshot_date_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.qa_snapshots
    ADD CONSTRAINT qa_snapshots_snapshot_date_key UNIQUE (snapshot_date);


--
-- Name: reference_cache reference_cache_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reference_cache
    ADD CONSTRAINT reference_cache_pkey PRIMARY KEY (symbol, as_of_date, source);


--
-- Name: rules_validation_reports rules_validation_reports_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rules_validation_reports
    ADD CONSTRAINT rules_validation_reports_pkey PRIMARY KEY (id);


--
-- Name: schema_migrations schema_migrations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.schema_migrations
    ADD CONSTRAINT schema_migrations_pkey PRIMARY KEY (version);


--
-- Name: sec_cik_cache sec_cik_cache_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sec_cik_cache
    ADD CONSTRAINT sec_cik_cache_pkey PRIMARY KEY (symbol);


--
-- Name: settings_profiles settings_profiles_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.settings_profiles
    ADD CONSTRAINT settings_profiles_pkey PRIMARY KEY (id);


--
-- Name: short_interest short_interest_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.short_interest
    ADD CONSTRAINT short_interest_pkey PRIMARY KEY (id);


--
-- Name: short_interest_summary short_interest_summary_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.short_interest_summary
    ADD CONSTRAINT short_interest_summary_pkey PRIMARY KEY (id);


--
-- Name: short_interest short_interest_symbol_as_of_date_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.short_interest
    ADD CONSTRAINT short_interest_symbol_as_of_date_key UNIQUE (symbol, as_of_date);


--
-- Name: sitemap_entries sitemap_entries_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sitemap_entries
    ADD CONSTRAINT sitemap_entries_pkey PRIMARY KEY (id);


--
-- Name: sitemap_entries sitemap_entries_unique; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sitemap_entries
    ADD CONSTRAINT sitemap_entries_unique UNIQUE (port, path, method);


--
-- Name: sitemap_health_history sitemap_health_history_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sitemap_health_history
    ADD CONSTRAINT sitemap_health_history_pkey PRIMARY KEY (id);


--
-- Name: source_credentials source_credentials_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.source_credentials
    ADD CONSTRAINT source_credentials_pkey PRIMARY KEY (source_id, field);


--
-- Name: source_metrics source_metrics_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.source_metrics
    ADD CONSTRAINT source_metrics_pkey PRIMARY KEY (id);


--
-- Name: source_performance source_performance_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.source_performance
    ADD CONSTRAINT source_performance_pkey PRIMARY KEY (source_name);


--
-- Name: source_registry source_registry_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.source_registry
    ADD CONSTRAINT source_registry_pkey PRIMARY KEY (source_id);


--
-- Name: strategy_definitions strategy_definitions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.strategy_definitions
    ADD CONSTRAINT strategy_definitions_pkey PRIMARY KEY (id);


--
-- Name: strategy_definitions strategy_definitions_symbol_name_version_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.strategy_definitions
    ADD CONSTRAINT strategy_definitions_symbol_name_version_key UNIQUE (symbol, name, version);


--
-- Name: strategy_lineage strategy_lineage_child_strategy_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.strategy_lineage
    ADD CONSTRAINT strategy_lineage_child_strategy_id_key UNIQUE (child_strategy_id);


--
-- Name: strategy_lineage strategy_lineage_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.strategy_lineage
    ADD CONSTRAINT strategy_lineage_pkey PRIMARY KEY (id);


--
-- Name: strategy_metrics strategy_metrics_metric_date_metric_type_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.strategy_metrics
    ADD CONSTRAINT strategy_metrics_metric_date_metric_type_key UNIQUE (metric_date, metric_type);


--
-- Name: strategy_metrics strategy_metrics_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.strategy_metrics
    ADD CONSTRAINT strategy_metrics_pkey PRIMARY KEY (id);


--
-- Name: strategy_performance strategy_performance_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.strategy_performance
    ADD CONSTRAINT strategy_performance_pkey PRIMARY KEY (id);


--
-- Name: strategy_performance strategy_performance_strategy_id_date_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.strategy_performance
    ADD CONSTRAINT strategy_performance_strategy_id_date_key UNIQUE (strategy_id, date);


--
-- Name: strategy_reviews strategy_reviews_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.strategy_reviews
    ADD CONSTRAINT strategy_reviews_pkey PRIMARY KEY (id);


--
-- Name: strategy_seeds strategy_seeds_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.strategy_seeds
    ADD CONSTRAINT strategy_seeds_pkey PRIMARY KEY (id);


--
-- Name: strategy_signals strategy_signals_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.strategy_signals
    ADD CONSTRAINT strategy_signals_pkey PRIMARY KEY (id);


--
-- Name: strategy_signals strategy_signals_strategy_id_signal_date_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.strategy_signals
    ADD CONSTRAINT strategy_signals_strategy_id_signal_date_key UNIQUE (strategy_id, signal_date);


--
-- Name: symbol_risk_metrics symbol_risk_metrics_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.symbol_risk_metrics
    ADD CONSTRAINT symbol_risk_metrics_pkey PRIMARY KEY (id);


--
-- Name: symbol_risk_metrics symbol_risk_metrics_symbol_as_of_date_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.symbol_risk_metrics
    ADD CONSTRAINT symbol_risk_metrics_symbol_as_of_date_key UNIQUE (symbol, as_of_date);


--
-- Name: symbol_workflow_events symbol_workflow_events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.symbol_workflow_events
    ADD CONSTRAINT symbol_workflow_events_pkey PRIMARY KEY (id);


--
-- Name: symbol_workflows symbol_workflows_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.symbol_workflows
    ADD CONSTRAINT symbol_workflows_pkey PRIMARY KEY (symbol);


--
-- Name: symbols symbols_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.symbols
    ADD CONSTRAINT symbols_pkey PRIMARY KEY (symbol);


--
-- Name: table_registry table_registry_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.table_registry
    ADD CONSTRAINT table_registry_pkey PRIMARY KEY (table_name);


--
-- Name: technical_indicators technical_indicators_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.technical_indicators
    ADD CONSTRAINT technical_indicators_pkey PRIMARY KEY (symbol, date);


--
-- Name: thesis_versions thesis_versions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.thesis_versions
    ADD CONSTRAINT thesis_versions_pkey PRIMARY KEY (id);


--
-- Name: market_events unique_event_date_type; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.market_events
    ADD CONSTRAINT unique_event_date_type UNIQUE (event_type, event_date);


--
-- Name: settings_profiles unique_profile_name_per_user; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.settings_profiles
    ADD CONSTRAINT unique_profile_name_per_user UNIQUE (user_id, name);


--
-- Name: user_article_feedback unique_user_article; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_article_feedback
    ADD CONSTRAINT unique_user_article UNIQUE (user_id, article_hash);


--
-- Name: source_metrics unique_vendor_calculated_at; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.source_metrics
    ADD CONSTRAINT unique_vendor_calculated_at UNIQUE (vendor, calculated_at);


--
-- Name: agent_conversation_messages uq_agent_conversation_messages_run_seq; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_conversation_messages
    ADD CONSTRAINT uq_agent_conversation_messages_run_seq UNIQUE (agent_run_id, sequence_num);


--
-- Name: household_document_requirements uq_household_document_requirements_requirement_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.household_document_requirements
    ADD CONSTRAINT uq_household_document_requirements_requirement_key UNIQUE (requirement_key);


--
-- Name: household_document_signatures uq_household_document_signatures_signature_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.household_document_signatures
    ADD CONSTRAINT uq_household_document_signatures_signature_key UNIQUE (signature_key);


--
-- Name: household_import_rows uq_household_import_rows_row_hash; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.household_import_rows
    ADD CONSTRAINT uq_household_import_rows_row_hash UNIQUE (row_hash);


--
-- Name: household_merchants uq_household_merchants_normalized_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.household_merchants
    ADD CONSTRAINT uq_household_merchants_normalized_key UNIQUE (normalized_key);


--
-- Name: household_transactions uq_household_transactions_row_hash; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.household_transactions
    ADD CONSTRAINT uq_household_transactions_row_hash UNIQUE (row_hash);


--
-- Name: thesis_versions uq_thesis_versions_thesis_version; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.thesis_versions
    ADD CONSTRAINT uq_thesis_versions_thesis_version UNIQUE (thesis_id, version);


--
-- Name: user_article_feedback user_article_feedback_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_article_feedback
    ADD CONSTRAINT user_article_feedback_pkey PRIMARY KEY (id);


--
-- Name: user_preferences user_preferences_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_preferences
    ADD CONSTRAINT user_preferences_pkey PRIMARY KEY (id);


--
-- Name: rules_validation_reports validation_time_idx; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rules_validation_reports
    ADD CONSTRAINT validation_time_idx UNIQUE (validation_time);


--
-- Name: valuation_metrics valuation_metrics_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.valuation_metrics
    ADD CONSTRAINT valuation_metrics_pkey PRIMARY KEY (id);


--
-- Name: vision_content vision_content_content_type_content_key_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vision_content
    ADD CONSTRAINT vision_content_content_type_content_key_key UNIQUE (content_type, content_key);


--
-- Name: vision_content vision_content_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vision_content
    ADD CONSTRAINT vision_content_pkey PRIMARY KEY (id);


--
-- Name: vision_goal_details vision_goal_details_goal_code_detail_type_order_num_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vision_goal_details
    ADD CONSTRAINT vision_goal_details_goal_code_detail_type_order_num_key UNIQUE (goal_code, detail_type, order_num);


--
-- Name: vision_goal_details vision_goal_details_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vision_goal_details
    ADD CONSTRAINT vision_goal_details_pkey PRIMARY KEY (id);


--
-- Name: vision_goals vision_goals_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vision_goals
    ADD CONSTRAINT vision_goals_pkey PRIMARY KEY (code);


--
-- Name: watchlist_daily_reports watchlist_daily_reports_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.watchlist_daily_reports
    ADD CONSTRAINT watchlist_daily_reports_pkey PRIMARY KEY (id);


--
-- Name: watchlist_daily_reports watchlist_daily_reports_report_date_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.watchlist_daily_reports
    ADD CONSTRAINT watchlist_daily_reports_report_date_key UNIQUE (report_date);


--
-- Name: watchlist_items watchlist_items_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.watchlist_items
    ADD CONSTRAINT watchlist_items_pkey PRIMARY KEY (id);


--
-- Name: watchlist_items watchlist_items_symbol_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.watchlist_items
    ADD CONSTRAINT watchlist_items_symbol_key UNIQUE (symbol);


--
-- Name: watchlist_narrative watchlist_narrative_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.watchlist_narrative
    ADD CONSTRAINT watchlist_narrative_pkey PRIMARY KEY (snapshot_id);


--
-- Name: watchlist_news_summary watchlist_news_summary_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.watchlist_news_summary
    ADD CONSTRAINT watchlist_news_summary_pkey PRIMARY KEY (snapshot_id);


--
-- Name: watchlist_snapshots_core watchlist_snapshots_core_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.watchlist_snapshots_core
    ADD CONSTRAINT watchlist_snapshots_core_pkey PRIMARY KEY (id);


--
-- Name: watchlist_snapshots watchlist_snapshots_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.watchlist_snapshots
    ADD CONSTRAINT watchlist_snapshots_pkey PRIMARY KEY (item_id, fetched_at);


--
-- Name: watchlist_technical_metrics watchlist_technical_metrics_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.watchlist_technical_metrics
    ADD CONSTRAINT watchlist_technical_metrics_pkey PRIMARY KEY (snapshot_id);


--
-- Name: watchlist_thesis watchlist_thesis_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.watchlist_thesis
    ADD CONSTRAINT watchlist_thesis_pkey PRIMARY KEY (id);


--
-- Name: watchlist_thesis watchlist_thesis_symbol_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.watchlist_thesis
    ADD CONSTRAINT watchlist_thesis_symbol_key UNIQUE (symbol);


--
-- Name: yield_curve yield_curve_observation_date_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.yield_curve
    ADD CONSTRAINT yield_curve_observation_date_key UNIQUE (observation_date);


--
-- Name: yield_curve yield_curve_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.yield_curve
    ADD CONSTRAINT yield_curve_pkey PRIMARY KEY (id);


--
-- Name: idx_agent_conversation_messages_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_agent_conversation_messages_created_at ON public.agent_conversation_messages USING btree (created_at);


--
-- Name: idx_agent_conversation_messages_run_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_agent_conversation_messages_run_id ON public.agent_conversation_messages USING btree (agent_run_id);


--
-- Name: idx_agent_messages_from_run_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_agent_messages_from_run_id ON public.agent_messages USING btree (from_agent_run_id);


--
-- Name: idx_agent_messages_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_agent_messages_status ON public.agent_messages USING btree (status, created_at DESC);


--
-- Name: idx_agent_messages_to_agent_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_agent_messages_to_agent_type ON public.agent_messages USING btree (to_agent_type, status);


--
-- Name: idx_agent_messages_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_agent_messages_type ON public.agent_messages USING btree (message_type);


--
-- Name: idx_agent_runs_model; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_agent_runs_model ON public.agent_runs USING btree (model);


--
-- Name: idx_agent_runs_parent_run_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_agent_runs_parent_run_id ON public.agent_runs USING btree (parent_run_id);


--
-- Name: idx_agent_runs_provider; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_agent_runs_provider ON public.agent_runs USING btree (provider);


--
-- Name: idx_agent_runs_run_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_agent_runs_run_type ON public.agent_runs USING btree (run_type);


--
-- Name: idx_agent_runs_started_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_agent_runs_started_at ON public.agent_runs USING btree (started_at);


--
-- Name: idx_agent_runs_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_agent_runs_user_id ON public.agent_runs USING btree (user_id);


--
-- Name: idx_agent_runs_workflow_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_agent_runs_workflow_id ON public.agent_runs USING btree (workflow_id);


--
-- Name: idx_agent_tool_calls_agent_run_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_agent_tool_calls_agent_run_id ON public.agent_tool_calls USING btree (agent_run_id);


--
-- Name: idx_agent_workflows_agents_involved; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_agent_workflows_agents_involved ON public.agent_workflows USING gin (agents_involved);


--
-- Name: idx_agent_workflows_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_agent_workflows_created_at ON public.agent_workflows USING btree (created_at DESC);


--
-- Name: idx_agent_workflows_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_agent_workflows_status ON public.agent_workflows USING btree (status, created_at DESC);


--
-- Name: idx_agent_workflows_triggered_by; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_agent_workflows_triggered_by ON public.agent_workflows USING btree (triggered_by);


--
-- Name: idx_agent_workflows_type_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_agent_workflows_type_status ON public.agent_workflows USING btree (workflow_type, status);


--
-- Name: idx_analyst_revisions_direction; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_analyst_revisions_direction ON public.analyst_revisions USING btree (revision_direction);


--
-- Name: idx_analyst_revisions_fetched; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_analyst_revisions_fetched ON public.analyst_revisions USING btree (fetched_at);


--
-- Name: idx_analyst_revisions_symbol; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_analyst_revisions_symbol ON public.analyst_revisions USING btree (symbol);


--
-- Name: idx_artifacts_criterion_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_artifacts_criterion_id ON public.artifacts USING btree (criterion_id);


--
-- Name: idx_artifacts_expires_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_artifacts_expires_at ON public.artifacts USING btree (expires_at) WHERE (expires_at IS NOT NULL);


--
-- Name: idx_artifacts_feature_criterion; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_artifacts_feature_criterion ON public.artifacts USING btree (feature_id, criterion_id);


--
-- Name: idx_artifacts_feature_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_artifacts_feature_id ON public.artifacts USING btree (feature_id);


--
-- Name: idx_artifacts_is_current; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_artifacts_is_current ON public.artifacts USING btree (is_current) WHERE (is_current = true);


--
-- Name: idx_artifacts_needs_review; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_artifacts_needs_review ON public.artifacts USING btree (quality_status) WHERE ((quality_status)::text = 'needs_review'::text);


--
-- Name: idx_artifacts_quality_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_artifacts_quality_status ON public.artifacts USING btree (quality_status);


--
-- Name: idx_artifacts_user_notes; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_artifacts_user_notes ON public.artifacts USING btree (id) WHERE (user_notes IS NOT NULL);


--
-- Name: idx_backtest_equity_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_backtest_equity_date ON public.backtest_equity USING btree (date);


--
-- Name: idx_backtest_equity_run_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_backtest_equity_run_id ON public.backtest_equity USING btree (run_id);


--
-- Name: idx_backtest_runs_beats_buy_hold; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_backtest_runs_beats_buy_hold ON public.backtest_runs USING btree (beats_buy_hold);


--
-- Name: idx_backtest_runs_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_backtest_runs_created_at ON public.backtest_runs USING btree (created_at DESC);


--
-- Name: idx_backtest_runs_excess_return; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_backtest_runs_excess_return ON public.backtest_runs USING btree (excess_return);


--
-- Name: idx_backtest_runs_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_backtest_runs_status ON public.backtest_runs USING btree (status);


--
-- Name: idx_backtest_runs_strategy; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_backtest_runs_strategy ON public.backtest_runs USING btree (strategy_name);


--
-- Name: idx_backtest_runs_strategy_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_backtest_runs_strategy_id ON public.backtest_runs USING btree (strategy_definition_id);


--
-- Name: idx_backtest_runs_symbol; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_backtest_runs_symbol ON public.backtest_runs USING btree (symbol);


--
-- Name: idx_backtest_trades_entry_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_backtest_trades_entry_date ON public.backtest_trades USING btree (entry_date);


--
-- Name: idx_backtest_trades_run_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_backtest_trades_run_id ON public.backtest_trades USING btree (run_id);


--
-- Name: idx_backtest_trades_symbol; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_backtest_trades_symbol ON public.backtest_trades USING btree (symbol);


--
-- Name: idx_cash_flow_metrics_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cash_flow_metrics_date ON public.cash_flow_metrics USING btree (as_of_date);


--
-- Name: idx_cash_flow_metrics_symbol; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cash_flow_metrics_symbol ON public.cash_flow_metrics USING btree (symbol);


--
-- Name: idx_claude_progress_action_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_claude_progress_action_type ON public.claude_progress_log USING btree (action_type);


--
-- Name: idx_claude_progress_feature; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_claude_progress_feature ON public.claude_progress_log USING btree (feature_id);


--
-- Name: idx_claude_progress_logged_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_claude_progress_logged_at ON public.claude_progress_log USING btree (logged_at DESC);


--
-- Name: idx_claude_progress_session; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_claude_progress_session ON public.claude_progress_log USING btree (session_id);


--
-- Name: idx_corporate_actions_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_corporate_actions_date ON public.corporate_actions USING btree (action_date DESC);


--
-- Name: idx_corporate_actions_symbol; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_corporate_actions_symbol ON public.corporate_actions USING btree (symbol);


--
-- Name: idx_corporate_actions_type_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_corporate_actions_type_date ON public.corporate_actions USING btree (action_type, action_date DESC);


--
-- Name: idx_cross_validation_results_generator_run_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cross_validation_results_generator_run_id ON public.cross_validation_results USING btree (generator_run_id);


--
-- Name: idx_cross_validation_results_validator_run_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cross_validation_results_validator_run_id ON public.cross_validation_results USING btree (validator_run_id);


--
-- Name: idx_day_bars_symbol; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_day_bars_symbol ON public.day_bars USING btree (symbol);


--
-- Name: idx_deletion_audit_deleted_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_deletion_audit_deleted_at ON public.deletion_audit USING btree (deleted_at DESC);


--
-- Name: idx_deletion_audit_deleted_by; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_deletion_audit_deleted_by ON public.deletion_audit USING btree (deleted_by);


--
-- Name: idx_deletion_audit_record_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_deletion_audit_record_id ON public.deletion_audit USING btree (table_name, record_id);


--
-- Name: idx_deletion_audit_table_name; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_deletion_audit_table_name ON public.deletion_audit USING btree (table_name);


--
-- Name: idx_earnings_surprises_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_earnings_surprises_date ON public.earnings_surprises USING btree (earnings_date DESC);


--
-- Name: idx_earnings_surprises_ticker; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_earnings_surprises_ticker ON public.earnings_surprises USING btree (symbol);


--
-- Name: idx_endpoint_source; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_endpoint_source ON public.endpoint_catalog USING btree (source_id);


--
-- Name: idx_endpoint_target; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_endpoint_target ON public.endpoint_catalog USING btree (target_table);


--
-- Name: idx_file_audit_bloat; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_file_audit_bloat ON public.file_audit USING btree (bloat_level) WHERE (bloat_level IS NOT NULL);


--
-- Name: idx_file_audit_extension; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_file_audit_extension ON public.file_audit USING btree (extension) WHERE (extension IS NOT NULL);


--
-- Name: idx_file_audit_is_directory; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_file_audit_is_directory ON public.file_audit USING btree (is_directory) WHERE (is_directory = true);


--
-- Name: idx_file_audit_last_commit_days; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_file_audit_last_commit_days ON public.file_audit USING btree (last_commit_days) WHERE (last_commit_days IS NOT NULL);


--
-- Name: idx_file_audit_stale_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_file_audit_stale_status ON public.file_audit USING btree (stale_status) WHERE (stale_status IS NOT NULL);


--
-- Name: idx_financial_health_symbol; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_financial_health_symbol ON public.financial_health_scores USING btree (symbol);


--
-- Name: idx_financial_health_symbol_date; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX idx_financial_health_symbol_date ON public.financial_health_scores USING btree (symbol, as_of_date);


--
-- Name: idx_fng_daily_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_fng_daily_date ON public.fear_greed_daily USING btree (as_of_date DESC);


--
-- Name: idx_fng_inputs_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_fng_inputs_date ON public.fear_greed_inputs USING btree (as_of_date DESC);


--
-- Name: idx_gap_analysis_history_timestamp; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_gap_analysis_history_timestamp ON public.gap_analysis_history USING btree (analysis_timestamp DESC);


--
-- Name: idx_health_history_checked; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_health_history_checked ON public.sitemap_health_history USING btree (checked_at);


--
-- Name: idx_health_history_entry; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_health_history_entry ON public.sitemap_health_history USING btree (sitemap_entry_id);


--
-- Name: idx_household_debt_obligations_source_document_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_household_debt_obligations_source_document_id ON public.household_debt_obligations USING btree (source_document_id);


--
-- Name: idx_household_debt_obligations_updated_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_household_debt_obligations_updated_at ON public.household_debt_obligations USING btree (updated_at);


--
-- Name: idx_household_document_requirements_priority; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_household_document_requirements_priority ON public.household_document_requirements USING btree (priority);


--
-- Name: idx_household_document_requirements_satisfied_by_document_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_household_document_requirements_satisfied_by_document_id ON public.household_document_requirements USING btree (satisfied_by_document_id);


--
-- Name: idx_household_document_requirements_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_household_document_requirements_status ON public.household_document_requirements USING btree (status);


--
-- Name: idx_household_document_reviews_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_household_document_reviews_created_at ON public.household_document_reviews USING btree (created_at);


--
-- Name: idx_household_document_reviews_document_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_household_document_reviews_document_id ON public.household_document_reviews USING btree (document_id);


--
-- Name: idx_household_document_signatures_sample_document_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_household_document_signatures_sample_document_id ON public.household_document_signatures USING btree (sample_document_id);


--
-- Name: idx_household_document_signatures_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_household_document_signatures_type ON public.household_document_signatures USING btree (signature_type);


--
-- Name: idx_household_documents_review_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_household_documents_review_status ON public.household_documents USING btree (review_status);


--
-- Name: idx_household_documents_source_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_household_documents_source_type ON public.household_documents USING btree (source_type);


--
-- Name: idx_household_documents_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_household_documents_status ON public.household_documents USING btree (status);


--
-- Name: idx_household_documents_uploaded_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_household_documents_uploaded_at ON public.household_documents USING btree (uploaded_at);


--
-- Name: idx_household_housing_costs_source_document_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_household_housing_costs_source_document_id ON public.household_housing_costs USING btree (source_document_id);


--
-- Name: idx_household_housing_costs_updated_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_household_housing_costs_updated_at ON public.household_housing_costs USING btree (updated_at);


--
-- Name: idx_household_import_rows_dataset_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_household_import_rows_dataset_type ON public.household_import_rows USING btree (dataset_type);


--
-- Name: idx_household_import_rows_document_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_household_import_rows_document_id ON public.household_import_rows USING btree (document_id);


--
-- Name: idx_household_import_rows_external_row_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_household_import_rows_external_row_id ON public.household_import_rows USING btree (external_row_id);


--
-- Name: idx_household_income_sources_source_document_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_household_income_sources_source_document_id ON public.household_income_sources USING btree (source_document_id);


--
-- Name: idx_household_income_sources_updated_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_household_income_sources_updated_at ON public.household_income_sources USING btree (updated_at);


--
-- Name: idx_household_inferred_values_field_name; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_household_inferred_values_field_name ON public.household_inferred_values USING btree (field_name);


--
-- Name: idx_household_inferred_values_source_document_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_household_inferred_values_source_document_id ON public.household_inferred_values USING btree (source_document_id);


--
-- Name: idx_household_inferred_values_updated_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_household_inferred_values_updated_at ON public.household_inferred_values USING btree (updated_at);


--
-- Name: idx_household_insurance_policies_source_document_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_household_insurance_policies_source_document_id ON public.household_insurance_policies USING btree (source_document_id);


--
-- Name: idx_household_insurance_policies_updated_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_household_insurance_policies_updated_at ON public.household_insurance_policies USING btree (updated_at);


--
-- Name: idx_household_members_source_document_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_household_members_source_document_id ON public.household_members USING btree (source_document_id);


--
-- Name: idx_household_members_updated_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_household_members_updated_at ON public.household_members USING btree (updated_at);


--
-- Name: idx_household_merchants_primary_category; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_household_merchants_primary_category ON public.household_merchants USING btree (primary_category);


--
-- Name: idx_household_planned_expenses_source_document_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_household_planned_expenses_source_document_id ON public.household_planned_expenses USING btree (source_document_id);


--
-- Name: idx_household_planned_expenses_updated_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_household_planned_expenses_updated_at ON public.household_planned_expenses USING btree (updated_at);


--
-- Name: idx_household_profiles_updated_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_household_profiles_updated_at ON public.household_profiles USING btree (updated_at);


--
-- Name: idx_household_questions_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_household_questions_created_at ON public.household_questions USING btree (created_at);


--
-- Name: idx_household_questions_field_name; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_household_questions_field_name ON public.household_questions USING btree (field_name);


--
-- Name: idx_household_questions_source_document_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_household_questions_source_document_id ON public.household_questions USING btree (source_document_id);


--
-- Name: idx_household_questions_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_household_questions_status ON public.household_questions USING btree (status);


--
-- Name: idx_household_retirement_income_sources_source_document_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_household_retirement_income_sources_source_document_id ON public.household_retirement_income_sources USING btree (source_document_id);


--
-- Name: idx_household_retirement_income_sources_updated_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_household_retirement_income_sources_updated_at ON public.household_retirement_income_sources USING btree (updated_at);


--
-- Name: idx_household_transactions_document_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_household_transactions_document_id ON public.household_transactions USING btree (document_id);


--
-- Name: idx_household_transactions_flow_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_household_transactions_flow_type ON public.household_transactions USING btree (flow_type);


--
-- Name: idx_household_transactions_merchant_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_household_transactions_merchant_id ON public.household_transactions USING btree (merchant_id);


--
-- Name: idx_household_transactions_transaction_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_household_transactions_transaction_date ON public.household_transactions USING btree (transaction_date);


--
-- Name: idx_idea_outcomes_backtest_run_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_idea_outcomes_backtest_run_id ON public.idea_outcomes USING btree (backtest_run_id);


--
-- Name: idx_idea_outcomes_strategy_backtest; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_idea_outcomes_strategy_backtest ON public.idea_outcomes USING btree (strategy_id, backtest_run_id);


--
-- Name: idx_idea_outcomes_strategy_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_idea_outcomes_strategy_date ON public.idea_outcomes USING btree (strategy_id, created_at DESC);


--
-- Name: idx_idea_outcomes_strategy_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_idea_outcomes_strategy_id ON public.idea_outcomes USING btree (strategy_id);


--
-- Name: idx_idea_outcomes_symbol; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_idea_outcomes_symbol ON public.idea_outcomes USING btree (symbol);


--
-- Name: idx_insider_transactions_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_insider_transactions_date ON public.insider_transactions USING btree (transaction_date DESC);


--
-- Name: idx_insider_transactions_symbol; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_insider_transactions_symbol ON public.insider_transactions USING btree (symbol);


--
-- Name: idx_insider_transactions_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_insider_transactions_type ON public.insider_transactions USING btree (transaction_type);


--
-- Name: idx_institutional_holdings_holder; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_institutional_holdings_holder ON public.institutional_holdings USING btree (holder_name);


--
-- Name: idx_institutional_holdings_symbol; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_institutional_holdings_symbol ON public.institutional_holdings USING btree (symbol);


--
-- Name: idx_institutional_summary_symbol; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_institutional_summary_symbol ON public.institutional_ownership_summary USING btree (symbol);


--
-- Name: idx_jenny_evals_agent_name; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_jenny_evals_agent_name ON public.jenny_agent_evaluations USING btree (agent_name);


--
-- Name: idx_jenny_evals_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_jenny_evals_created_at ON public.jenny_agent_evaluations USING btree (created_at);


--
-- Name: idx_jenny_evals_routine_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_jenny_evals_routine_id ON public.jenny_agent_evaluations USING btree (routine_id);


--
-- Name: idx_jenny_evals_symbol; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_jenny_evals_symbol ON public.jenny_agent_evaluations USING btree (symbol);


--
-- Name: idx_jenny_notifications_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_jenny_notifications_created_at ON public.jenny_notifications USING btree (created_at);


--
-- Name: idx_jenny_notifications_severity; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_jenny_notifications_severity ON public.jenny_notifications USING btree (severity);


--
-- Name: idx_jenny_notifications_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_jenny_notifications_status ON public.jenny_notifications USING btree (status);


--
-- Name: idx_jenny_notifications_symbol; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_jenny_notifications_symbol ON public.jenny_notifications USING btree (symbol);


--
-- Name: idx_jenny_routines_started_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_jenny_routines_started_at ON public.jenny_routines USING btree (started_at);


--
-- Name: idx_jenny_routines_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_jenny_routines_status ON public.jenny_routines USING btree (status);


--
-- Name: idx_jenny_routines_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_jenny_routines_type ON public.jenny_routines USING btree (routine_type);


--
-- Name: idx_jenny_trade_reviews_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_jenny_trade_reviews_created_at ON public.jenny_trade_reviews USING btree (created_at);


--
-- Name: idx_jenny_trade_reviews_idea_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_jenny_trade_reviews_idea_id ON public.jenny_trade_reviews USING btree (idea_id);


--
-- Name: idx_jenny_trade_reviews_symbol; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_jenny_trade_reviews_symbol ON public.jenny_trade_reviews USING btree (symbol);


--
-- Name: idx_lineage_child; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_lineage_child ON public.strategy_lineage USING btree (child_strategy_id);


--
-- Name: idx_lineage_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_lineage_created ON public.strategy_lineage USING btree (created_at DESC);


--
-- Name: idx_lineage_parent; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_lineage_parent ON public.strategy_lineage USING btree (parent_strategy_id);


--
-- Name: idx_macro_indicators_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_macro_indicators_date ON public.macro_indicators USING btree (observation_date DESC);


--
-- Name: idx_macro_indicators_name; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_macro_indicators_name ON public.macro_indicators USING btree (indicator_name);


--
-- Name: idx_maintenance_log_started_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_maintenance_log_started_at ON public.maintenance_log USING btree (started_at DESC);


--
-- Name: idx_maintenance_log_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_maintenance_log_status ON public.maintenance_log USING btree (status);


--
-- Name: idx_maintenance_log_task_name; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_maintenance_log_task_name ON public.maintenance_log USING btree (task_name);


--
-- Name: idx_maintenance_log_task_started; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_maintenance_log_task_started ON public.maintenance_log USING btree (task_name, started_at DESC);


--
-- Name: idx_maintenance_stats_metric_name; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_maintenance_stats_metric_name ON public.maintenance_stats USING btree (metric_name);


--
-- Name: idx_maintenance_stats_metric_recorded; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_maintenance_stats_metric_recorded ON public.maintenance_stats USING btree (metric_name, recorded_at DESC);


--
-- Name: idx_maintenance_stats_recorded_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_maintenance_stats_recorded_at ON public.maintenance_stats USING btree (recorded_at DESC);


--
-- Name: idx_market_events_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_market_events_date ON public.market_events USING btree (event_date DESC);


--
-- Name: idx_market_events_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_market_events_type ON public.market_events USING btree (event_type);


--
-- Name: idx_ml_model_metrics_name_version; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_ml_model_metrics_name_version ON public.ml_model_metrics USING btree (model_name, model_version DESC);


--
-- Name: idx_ml_model_metrics_trained_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_ml_model_metrics_trained_at ON public.ml_model_metrics USING btree (trained_at DESC);


--
-- Name: idx_ml_training_progress_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_ml_training_progress_status ON public.ml_training_progress USING btree (status);


--
-- Name: idx_news_cache_fetched_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_news_cache_fetched_at ON public.news_cache USING btree (fetched_at);


--
-- Name: idx_news_cache_quality; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_news_cache_quality ON public.news_cache USING btree (quality_prediction, quality_confidence) WHERE (quality_prediction IS NOT NULL);


--
-- Name: idx_news_cache_symbol; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_news_cache_symbol ON public.news_cache USING btree (symbol);


--
-- Name: idx_news_cache_ticker_published; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_news_cache_ticker_published ON public.news_cache USING btree (symbol, published_at DESC);


--
-- Name: idx_news_cache_vendor_fetched_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_news_cache_vendor_fetched_at ON public.news_cache USING btree ((((raw_payload -> 'raw'::text) ->> 'vendor'::text)), fetched_at DESC);


--
-- Name: idx_news_filing_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_news_filing_type ON public.news_cache USING btree (filing_type) WHERE (filing_type IS NOT NULL);


--
-- Name: idx_news_material_events; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_news_material_events ON public.news_cache USING btree (is_material_event) WHERE (is_material_event = true);


--
-- Name: idx_news_primary_articles; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_news_primary_articles ON public.news_cache USING btree (symbol, is_primary_article, published_at DESC) WHERE (is_primary_article = true);


--
-- Name: idx_news_story_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_news_story_id ON public.news_cache USING btree (story_id) WHERE (story_id IS NOT NULL);


--
-- Name: idx_news_summary_log_symbol; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_news_summary_log_symbol ON public.news_summary_log USING btree (symbol);


--
-- Name: idx_news_summary_log_ticker_time; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_news_summary_log_ticker_time ON public.news_summary_log USING btree (symbol, window_end DESC);


--
-- Name: idx_options_metrics_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_options_metrics_date ON public.options_market_metrics USING btree (as_of_date DESC);


--
-- Name: idx_options_metrics_timestamp; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_options_metrics_timestamp ON public.options_market_metrics USING btree (source_timestamp DESC);


--
-- Name: idx_outcomes_entry_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_outcomes_entry_date ON public.idea_outcomes USING btree (entry_date DESC);


--
-- Name: idx_outcomes_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_outcomes_status ON public.idea_outcomes USING btree (status);


--
-- Name: idx_outcomes_status_entry_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_outcomes_status_entry_date ON public.idea_outcomes USING btree (status, entry_date DESC);


--
-- Name: idx_paper_trade_transactions_agent_run; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_paper_trade_transactions_agent_run ON public.paper_trade_transactions USING btree (agent_run_id);


--
-- Name: idx_paper_trade_transactions_symbol; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_paper_trade_transactions_symbol ON public.paper_trade_transactions USING btree (symbol);


--
-- Name: idx_paper_trade_transactions_timestamp; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_paper_trade_transactions_timestamp ON public.paper_trade_transactions USING btree ("timestamp" DESC);


--
-- Name: idx_paper_trade_transactions_trade_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_paper_trade_transactions_trade_id ON public.paper_trade_transactions USING btree (trade_id);


--
-- Name: idx_paper_trade_transactions_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_paper_trade_transactions_type ON public.paper_trade_transactions USING btree (transaction_type);


--
-- Name: idx_performance_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_performance_date ON public.strategy_performance USING btree (date DESC);


--
-- Name: idx_performance_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_performance_status ON public.strategy_performance USING btree (status, date DESC);


--
-- Name: idx_performance_strategy; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_performance_strategy ON public.strategy_performance USING btree (strategy_id, date DESC);


--
-- Name: idx_portfolio_accounts_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_portfolio_accounts_type ON public.portfolio_accounts USING btree (account_type);


--
-- Name: idx_portfolio_covariance_calculated_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_portfolio_covariance_calculated_at ON public.portfolio_covariance USING btree (calculated_at);


--
-- Name: idx_portfolio_covariance_ticker1; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_portfolio_covariance_ticker1 ON public.portfolio_covariance USING btree (symbol1);


--
-- Name: idx_portfolio_covariance_ticker2; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_portfolio_covariance_ticker2 ON public.portfolio_covariance USING btree (symbol2);


--
-- Name: idx_portfolio_positions_account_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_portfolio_positions_account_id ON public.portfolio_positions USING btree (account_id);


--
-- Name: idx_portfolio_positions_strategy_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_portfolio_positions_strategy_id ON public.portfolio_positions USING btree (strategy_id);


--
-- Name: idx_portfolio_snapshots_drawdown; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_portfolio_snapshots_drawdown ON public.portfolio_snapshots USING btree (account_id, drawdown_pct DESC) WHERE (drawdown_pct > (0)::numeric);


--
-- Name: idx_portfolio_snapshots_equity; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_portfolio_snapshots_equity ON public.portfolio_snapshots USING btree (account_id, equity DESC);


--
-- Name: idx_portfolio_volatility_cache_calculated_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_portfolio_volatility_cache_calculated_at ON public.portfolio_volatility_cache USING btree (calculated_at);


--
-- Name: idx_qa_issues_category; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_qa_issues_category ON public.qa_issues USING btree (category);


--
-- Name: idx_qa_issues_detection_source; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_qa_issues_detection_source ON public.qa_issues USING btree (detection_source);


--
-- Name: idx_qa_issues_false_positive; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_qa_issues_false_positive ON public.qa_issues USING btree (false_positive) WHERE (false_positive = false);


--
-- Name: idx_qa_issues_file_path; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_qa_issues_file_path ON public.qa_issues USING btree (file_path);


--
-- Name: idx_qa_issues_resolved; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_qa_issues_resolved ON public.qa_issues USING btree (resolved_at);


--
-- Name: idx_qa_issues_severity; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_qa_issues_severity ON public.qa_issues USING btree (severity);


--
-- Name: idx_qa_issues_unresolved; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_qa_issues_unresolved ON public.qa_issues USING btree (resolved_at) WHERE (resolved_at IS NULL);


--
-- Name: idx_qa_snapshots_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_qa_snapshots_created_at ON public.qa_snapshots USING btree (created_at);


--
-- Name: idx_qa_snapshots_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_qa_snapshots_date ON public.qa_snapshots USING btree (snapshot_date);


--
-- Name: idx_reference_cache_dividend_yield; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_reference_cache_dividend_yield ON public.reference_cache USING btree (dividend_yield) WHERE (dividend_yield IS NOT NULL);


--
-- Name: idx_reference_cache_f_score; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_reference_cache_f_score ON public.reference_cache USING btree (f_score) WHERE (f_score IS NOT NULL);


--
-- Name: idx_reference_cache_pb; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_reference_cache_pb ON public.reference_cache USING btree (pb_ratio) WHERE (pb_ratio IS NOT NULL);


--
-- Name: idx_reference_cache_pe_trailing; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_reference_cache_pe_trailing ON public.reference_cache USING btree (pe_ratio_trailing) WHERE (pe_ratio_trailing IS NOT NULL);


--
-- Name: idx_reference_cache_ps; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_reference_cache_ps ON public.reference_cache USING btree (ps_ratio) WHERE (ps_ratio IS NOT NULL);


--
-- Name: idx_reference_cache_symbol; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_reference_cache_symbol ON public.reference_cache USING btree (symbol);


--
-- Name: idx_reference_cache_ticker; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_reference_cache_ticker ON public.reference_cache USING btree (symbol, as_of_date);


--
-- Name: idx_reference_cache_z_score_zone; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_reference_cache_z_score_zone ON public.reference_cache USING btree (z_score_zone) WHERE (z_score_zone IS NOT NULL);


--
-- Name: idx_sec_cik_cache_cik; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_sec_cik_cache_cik ON public.sec_cik_cache USING btree (cik);


--
-- Name: idx_sec_cik_cache_updated; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_sec_cik_cache_updated ON public.sec_cik_cache USING btree (last_updated DESC);


--
-- Name: idx_seed_confidence; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_seed_confidence ON public.strategy_seeds USING btree (confidence DESC) WHERE ((status)::text = 'pending'::text);


--
-- Name: idx_seed_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_seed_status ON public.strategy_seeds USING btree (status, created_at DESC);


--
-- Name: idx_seed_symbol; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_seed_symbol ON public.strategy_seeds USING btree (symbol);


--
-- Name: idx_settings_profiles_active; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_settings_profiles_active ON public.settings_profiles USING btree (user_id, is_active) WHERE (is_active = true);


--
-- Name: idx_settings_profiles_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_settings_profiles_user_id ON public.settings_profiles USING btree (user_id);


--
-- Name: idx_short_interest_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_short_interest_date ON public.short_interest USING btree (as_of_date DESC);


--
-- Name: idx_short_interest_ratio; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_short_interest_ratio ON public.short_interest USING btree (short_ratio) WHERE (short_ratio IS NOT NULL);


--
-- Name: idx_short_interest_symbol; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_short_interest_symbol ON public.short_interest USING btree (symbol);


--
-- Name: idx_short_interest_symbol_date; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX idx_short_interest_symbol_date ON public.short_interest_summary USING btree (symbol, as_of_date);


--
-- Name: idx_sitemap_artifact; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_sitemap_artifact ON public.sitemap_entries USING btree (artifact_id) WHERE (artifact_id IS NOT NULL);


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
-- Name: idx_sitemap_parent; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_sitemap_parent ON public.sitemap_entries USING btree (parent_path);


--
-- Name: idx_sitemap_port; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_sitemap_port ON public.sitemap_entries USING btree (port);


--
-- Name: idx_snapshots_core_item_fetched; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX idx_snapshots_core_item_fetched ON public.watchlist_snapshots_core USING btree (item_id, fetched_at);


--
-- Name: idx_source_metrics_calculated_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_source_metrics_calculated_at ON public.source_metrics USING btree (calculated_at DESC);


--
-- Name: idx_source_metrics_quality_score; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_source_metrics_quality_score ON public.source_metrics USING btree (quality_score DESC);


--
-- Name: idx_source_metrics_vendor; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_source_metrics_vendor ON public.source_metrics USING btree (vendor);


--
-- Name: idx_source_priority; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_source_priority ON public.source_registry USING btree (priority, enabled);


--
-- Name: idx_strategy_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_strategy_created ON public.strategy_definitions USING btree (created_at DESC);


--
-- Name: idx_strategy_metrics_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_strategy_metrics_date ON public.strategy_metrics USING btree (metric_date DESC);


--
-- Name: idx_strategy_metrics_drift; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_strategy_metrics_drift ON public.strategy_metrics USING btree (score_stdev DESC);


--
-- Name: idx_strategy_metrics_provider_disagreement; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_strategy_metrics_provider_disagreement ON public.strategy_metrics USING btree (provider_disagreement_rate_pct DESC) WHERE (provider_disagreement_rate_pct > (20)::numeric);


--
-- Name: idx_strategy_metrics_winrate; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_strategy_metrics_winrate ON public.strategy_metrics USING btree (win_rate_pct DESC);


--
-- Name: idx_strategy_reviews_agent_run_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_strategy_reviews_agent_run_id ON public.strategy_reviews USING btree (agent_run_id);


--
-- Name: idx_strategy_reviews_disagreement; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_strategy_reviews_disagreement ON public.strategy_reviews USING btree (disagreement) WHERE (disagreement = true);


--
-- Name: idx_strategy_reviews_item; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_strategy_reviews_item ON public.strategy_reviews USING btree (watchlist_item_id);


--
-- Name: idx_strategy_reviews_pair; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_strategy_reviews_pair ON public.strategy_reviews USING btree (review_pair_id) WHERE (review_pair_id IS NOT NULL);


--
-- Name: idx_strategy_reviews_provider; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_strategy_reviews_provider ON public.strategy_reviews USING btree (provider);


--
-- Name: idx_strategy_reviews_provider_disagreement; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_strategy_reviews_provider_disagreement ON public.strategy_reviews USING btree (provider_disagreement) WHERE (provider_disagreement = true);


--
-- Name: idx_strategy_reviews_severity; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_strategy_reviews_severity ON public.strategy_reviews USING btree (disagreement_severity) WHERE (disagreement_severity = ANY (ARRAY['minor'::text, 'major'::text]));


--
-- Name: idx_strategy_reviews_symbol; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_strategy_reviews_symbol ON public.strategy_reviews USING btree (symbol);


--
-- Name: idx_strategy_seed_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_strategy_seed_id ON public.strategy_definitions USING btree (seed_id) WHERE (seed_id IS NOT NULL);


--
-- Name: idx_strategy_signals_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_strategy_signals_date ON public.strategy_signals USING btree (signal_date DESC);


--
-- Name: idx_strategy_signals_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_strategy_signals_type ON public.strategy_signals USING btree (signal_type, signal_date DESC);


--
-- Name: idx_strategy_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_strategy_status ON public.strategy_definitions USING btree (status, symbol);


--
-- Name: idx_strategy_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_strategy_type ON public.strategy_definitions USING btree (strategy_type, status);


--
-- Name: idx_symbol_risk_metrics_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_symbol_risk_metrics_date ON public.symbol_risk_metrics USING btree (as_of_date);


--
-- Name: idx_symbol_risk_metrics_symbol; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_symbol_risk_metrics_symbol ON public.symbol_risk_metrics USING btree (symbol);


--
-- Name: idx_symbol_workflow_events_symbol_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_symbol_workflow_events_symbol_created ON public.symbol_workflow_events USING btree (symbol, created_at);


--
-- Name: idx_symbol_workflows_stage_transition; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_symbol_workflows_stage_transition ON public.symbol_workflows USING btree (current_stage, last_transition_at);


--
-- Name: idx_symbols_exchange; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_symbols_exchange ON public.symbols USING btree (exchange);


--
-- Name: idx_symbols_is_active; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_symbols_is_active ON public.symbols USING btree (is_active);


--
-- Name: idx_symbols_sector; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_symbols_sector ON public.symbols USING btree (sector);


--
-- Name: idx_symbols_security_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_symbols_security_type ON public.symbols USING btree (security_type);


--
-- Name: idx_technical_indicators_symbol; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_technical_indicators_symbol ON public.technical_indicators USING btree (symbol);


--
-- Name: idx_thesis_versions_change_reason; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_thesis_versions_change_reason ON public.thesis_versions USING btree (change_reason);


--
-- Name: idx_thesis_versions_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_thesis_versions_created_at ON public.thesis_versions USING btree (created_at DESC);


--
-- Name: idx_user_article_feedback_article_hash; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_user_article_feedback_article_hash ON public.user_article_feedback USING btree (article_hash);


--
-- Name: idx_user_article_feedback_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_user_article_feedback_created_at ON public.user_article_feedback USING btree (created_at DESC);


--
-- Name: idx_user_article_feedback_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_user_article_feedback_user_id ON public.user_article_feedback USING btree (user_id);


--
-- Name: idx_user_article_feedback_vendor; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_user_article_feedback_vendor ON public.user_article_feedback USING btree (vendor);


--
-- Name: idx_validation_reports_critical; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_validation_reports_critical ON public.rules_validation_reports USING btree (validation_time DESC) WHERE ((overall_status)::text = 'critical'::text);


--
-- Name: idx_validation_reports_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_validation_reports_status ON public.rules_validation_reports USING btree (overall_status);


--
-- Name: idx_validation_reports_time; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_validation_reports_time ON public.rules_validation_reports USING btree (validation_time DESC);


--
-- Name: idx_valuation_metrics_symbol; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_valuation_metrics_symbol ON public.valuation_metrics USING btree (symbol);


--
-- Name: idx_valuation_metrics_symbol_date; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX idx_valuation_metrics_symbol_date ON public.valuation_metrics USING btree (symbol, as_of_date);


--
-- Name: idx_vision_content_order; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_vision_content_order ON public.vision_content USING btree (content_type, order_num);


--
-- Name: idx_vision_content_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_vision_content_type ON public.vision_content USING btree (content_type);


--
-- Name: idx_vision_goal_details_code; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_vision_goal_details_code ON public.vision_goal_details USING btree (goal_code);


--
-- Name: idx_vision_goal_details_code_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_vision_goal_details_code_type ON public.vision_goal_details USING btree (goal_code, detail_type);


--
-- Name: idx_vision_goal_details_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_vision_goal_details_type ON public.vision_goal_details USING btree (detail_type);


--
-- Name: idx_vision_goals_category; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_vision_goals_category ON public.vision_goals USING btree (category);


--
-- Name: idx_watchlist_daily_reports_generated_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_watchlist_daily_reports_generated_at ON public.watchlist_daily_reports USING btree (generated_at DESC);


--
-- Name: idx_watchlist_daily_reports_report_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_watchlist_daily_reports_report_date ON public.watchlist_daily_reports USING btree (report_date DESC);


--
-- Name: idx_watchlist_items_added_by; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_watchlist_items_added_by ON public.watchlist_items USING btree (added_by);


--
-- Name: idx_watchlist_items_source; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_watchlist_items_source ON public.watchlist_items USING btree (source);


--
-- Name: idx_watchlist_snapshots_company_health; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_watchlist_snapshots_company_health ON public.watchlist_snapshots USING btree (item_id, company_health, fetched_at DESC) WHERE (company_health IS NOT NULL);


--
-- Name: idx_watchlist_snapshots_earnings; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_watchlist_snapshots_earnings ON public.watchlist_snapshots USING btree (item_id, earnings_date) WHERE (earnings_date IS NOT NULL);


--
-- Name: idx_watchlist_snapshots_signal; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_watchlist_snapshots_signal ON public.watchlist_snapshots USING btree (item_id, signal_type, fetched_at DESC);


--
-- Name: idx_watchlist_snapshots_style; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_watchlist_snapshots_style ON public.watchlist_snapshots USING btree (item_id, recommended_style, fetched_at DESC);


--
-- Name: idx_watchlist_thesis_action; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_watchlist_thesis_action ON public.watchlist_thesis USING btree (action);


--
-- Name: idx_watchlist_thesis_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_watchlist_thesis_created_at ON public.watchlist_thesis USING btree (created_at DESC);


--
-- Name: idx_watchlist_thesis_cross_validation; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_watchlist_thesis_cross_validation ON public.watchlist_thesis USING btree (cross_validation_score) WHERE (cross_validation_score IS NOT NULL);


--
-- Name: idx_watchlist_thesis_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_watchlist_thesis_status ON public.watchlist_thesis USING btree (status);


--
-- Name: idx_xval_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_xval_created_at ON public.cross_validation_results USING btree (created_at DESC);


--
-- Name: idx_xval_disagreement; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_xval_disagreement ON public.cross_validation_results USING btree (has_disagreement) WHERE (has_disagreement = true);


--
-- Name: idx_xval_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_xval_status ON public.cross_validation_results USING btree (status);


--
-- Name: idx_xval_symbol; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_xval_symbol ON public.cross_validation_results USING btree (context_symbol) WHERE (context_symbol IS NOT NULL);


--
-- Name: idx_yield_curve_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_yield_curve_date ON public.yield_curve USING btree (observation_date DESC);


--
-- Name: idx_yield_curve_inverted; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_yield_curve_inverted ON public.yield_curve USING btree (is_inverted) WHERE (is_inverted = true);


--
-- Name: news_cache_symbol_hash; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX news_cache_symbol_hash ON public.news_cache USING btree (symbol, content_hash);


--
-- Name: corporate_actions corporate_actions_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER corporate_actions_updated_at BEFORE UPDATE ON public.corporate_actions FOR EACH ROW EXECUTE FUNCTION public.update_corporate_actions_timestamp();


--
-- Name: market_events market_events_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER market_events_updated_at BEFORE UPDATE ON public.market_events FOR EACH ROW EXECUTE FUNCTION public.update_market_events_updated_at();


--
-- Name: symbols symbols_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER symbols_updated_at BEFORE UPDATE ON public.symbols FOR EACH ROW EXECUTE FUNCTION public.update_symbols_updated_at();


--
-- Name: watchlist_thesis thesis_versioning; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER thesis_versioning AFTER INSERT OR UPDATE ON public.watchlist_thesis FOR EACH ROW EXECUTE FUNCTION public.create_thesis_version();


--
-- Name: artifacts trigger_artifacts_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trigger_artifacts_updated_at BEFORE UPDATE ON public.artifacts FOR EACH ROW EXECUTE FUNCTION public.update_artifacts_updated_at();


--
-- Name: portfolio_positions trigger_audit_portfolio_positions_deletion; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trigger_audit_portfolio_positions_deletion BEFORE DELETE ON public.portfolio_positions FOR EACH ROW EXECUTE FUNCTION public.log_deletion();


--
-- Name: watchlist_items trigger_audit_watchlist_items_deletion; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trigger_audit_watchlist_items_deletion BEFORE DELETE ON public.watchlist_items FOR EACH ROW EXECUTE FUNCTION public.log_deletion();


--
-- Name: watchlist_snapshots trigger_audit_watchlist_snapshots_deletion; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trigger_audit_watchlist_snapshots_deletion BEFORE DELETE ON public.watchlist_snapshots FOR EACH ROW EXECUTE FUNCTION public.log_deletion();


--
-- Name: settings_profiles trigger_ensure_single_active_profile; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trigger_ensure_single_active_profile BEFORE INSERT OR UPDATE ON public.settings_profiles FOR EACH ROW WHEN ((new.is_active = true)) EXECUTE FUNCTION public.ensure_single_active_profile();


--
-- Name: qa_issues trigger_qa_issues_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trigger_qa_issues_updated_at BEFORE UPDATE ON public.qa_issues FOR EACH ROW EXECUTE FUNCTION public.update_qa_issues_updated_at();


--
-- Name: sitemap_entries trigger_sitemap_entries_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trigger_sitemap_entries_updated_at BEFORE UPDATE ON public.sitemap_entries FOR EACH ROW EXECUTE FUNCTION public.update_sitemap_entries_updated_at();


--
-- Name: settings_profiles update_settings_profiles_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER update_settings_profiles_updated_at BEFORE UPDATE ON public.settings_profiles FOR EACH ROW EXECUTE FUNCTION public.update_settings_profiles_updated_at();


--
-- Name: watchlist_thesis watchlist_thesis_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER watchlist_thesis_updated_at BEFORE UPDATE ON public.watchlist_thesis FOR EACH ROW EXECUTE FUNCTION public.update_watchlist_thesis_updated_at();


--
-- Name: agent_conversation_messages agent_conversation_messages_agent_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_conversation_messages
    ADD CONSTRAINT agent_conversation_messages_agent_run_id_fkey FOREIGN KEY (agent_run_id) REFERENCES public.agent_runs(id) ON DELETE CASCADE;


--
-- Name: agent_runs agent_runs_parent_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_runs
    ADD CONSTRAINT agent_runs_parent_run_id_fkey FOREIGN KEY (parent_run_id) REFERENCES public.agent_runs(id) ON DELETE SET NULL;


--
-- Name: agent_runs agent_runs_workflow_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_runs
    ADD CONSTRAINT agent_runs_workflow_id_fkey FOREIGN KEY (workflow_id) REFERENCES public.agent_workflows(id) ON DELETE SET NULL;


--
-- Name: agent_tool_calls agent_tool_calls_agent_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_tool_calls
    ADD CONSTRAINT agent_tool_calls_agent_run_id_fkey FOREIGN KEY (agent_run_id) REFERENCES public.agent_runs(id) ON DELETE CASCADE;


--
-- Name: analyst_revisions analyst_revisions_symbol_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.analyst_revisions
    ADD CONSTRAINT analyst_revisions_symbol_fkey FOREIGN KEY (symbol) REFERENCES public.symbols(symbol);


--
-- Name: backtest_equity backtest_equity_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.backtest_equity
    ADD CONSTRAINT backtest_equity_run_id_fkey FOREIGN KEY (run_id) REFERENCES public.backtest_runs(id) ON DELETE CASCADE;


--
-- Name: backtest_trades backtest_trades_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.backtest_trades
    ADD CONSTRAINT backtest_trades_run_id_fkey FOREIGN KEY (run_id) REFERENCES public.backtest_runs(id) ON DELETE CASCADE;


--
-- Name: corporate_actions corporate_actions_symbol_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.corporate_actions
    ADD CONSTRAINT corporate_actions_symbol_fkey FOREIGN KEY (symbol) REFERENCES public.symbols(symbol) ON DELETE CASCADE;


--
-- Name: cross_validation_results cross_validation_results_generator_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cross_validation_results
    ADD CONSTRAINT cross_validation_results_generator_run_id_fkey FOREIGN KEY (generator_run_id) REFERENCES public.agent_runs(id) ON DELETE SET NULL;


--
-- Name: cross_validation_results cross_validation_results_validator_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cross_validation_results
    ADD CONSTRAINT cross_validation_results_validator_run_id_fkey FOREIGN KEY (validator_run_id) REFERENCES public.agent_runs(id) ON DELETE SET NULL;


--
-- Name: endpoint_catalog endpoint_catalog_source_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.endpoint_catalog
    ADD CONSTRAINT endpoint_catalog_source_id_fkey FOREIGN KEY (source_id) REFERENCES public.source_registry(source_id) ON DELETE CASCADE;


--
-- Name: agent_messages fk_agent_messages_from_run; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_messages
    ADD CONSTRAINT fk_agent_messages_from_run FOREIGN KEY (from_agent_run_id) REFERENCES public.agent_runs(id) ON DELETE SET NULL DEFERRABLE INITIALLY DEFERRED;


--
-- Name: backtest_runs fk_backtest_runs_strategy; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.backtest_runs
    ADD CONSTRAINT fk_backtest_runs_strategy FOREIGN KEY (strategy_definition_id) REFERENCES public.strategy_definitions(id) ON DELETE SET NULL;


--
-- Name: backtest_runs fk_backtest_runs_symbol; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.backtest_runs
    ADD CONSTRAINT fk_backtest_runs_symbol FOREIGN KEY (symbol) REFERENCES public.symbols(symbol) ON UPDATE CASCADE ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED;


--
-- Name: backtest_trades fk_backtest_trades_symbol; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.backtest_trades
    ADD CONSTRAINT fk_backtest_trades_symbol FOREIGN KEY (symbol) REFERENCES public.symbols(symbol) ON UPDATE CASCADE ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED;


--
-- Name: cash_flow_metrics fk_cash_flow_metrics_symbol; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cash_flow_metrics
    ADD CONSTRAINT fk_cash_flow_metrics_symbol FOREIGN KEY (symbol) REFERENCES public.symbols(symbol) ON UPDATE CASCADE ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED;


--
-- Name: day_bars fk_day_bars_symbol; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.day_bars
    ADD CONSTRAINT fk_day_bars_symbol FOREIGN KEY (symbol) REFERENCES public.symbols(symbol) ON UPDATE CASCADE ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED;


--
-- Name: earnings_surprises fk_earnings_surprises_symbol; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.earnings_surprises
    ADD CONSTRAINT fk_earnings_surprises_symbol FOREIGN KEY (symbol) REFERENCES public.symbols(symbol) ON UPDATE CASCADE ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED;


--
-- Name: financial_health_scores fk_financial_health_scores_symbol; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.financial_health_scores
    ADD CONSTRAINT fk_financial_health_scores_symbol FOREIGN KEY (symbol) REFERENCES public.symbols(symbol) ON DELETE CASCADE;


--
-- Name: idea_outcomes fk_idea_outcomes_backtest_run; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.idea_outcomes
    ADD CONSTRAINT fk_idea_outcomes_backtest_run FOREIGN KEY (backtest_run_id) REFERENCES public.backtest_runs(id) ON DELETE SET NULL;


--
-- Name: idea_outcomes fk_idea_outcomes_strategy; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.idea_outcomes
    ADD CONSTRAINT fk_idea_outcomes_strategy FOREIGN KEY (strategy_id) REFERENCES public.strategy_definitions(id) ON DELETE SET NULL;


--
-- Name: idea_outcomes fk_idea_outcomes_symbol; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.idea_outcomes
    ADD CONSTRAINT fk_idea_outcomes_symbol FOREIGN KEY (symbol) REFERENCES public.symbols(symbol) ON UPDATE CASCADE ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED;


--
-- Name: insider_transactions fk_insider_transactions_symbol; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.insider_transactions
    ADD CONSTRAINT fk_insider_transactions_symbol FOREIGN KEY (symbol) REFERENCES public.symbols(symbol) ON UPDATE CASCADE ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED;


--
-- Name: institutional_holdings fk_institutional_holdings_symbol; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.institutional_holdings
    ADD CONSTRAINT fk_institutional_holdings_symbol FOREIGN KEY (symbol) REFERENCES public.symbols(symbol) ON UPDATE CASCADE ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED;


--
-- Name: institutional_ownership_summary fk_institutional_ownership_summary_symbol; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.institutional_ownership_summary
    ADD CONSTRAINT fk_institutional_ownership_summary_symbol FOREIGN KEY (symbol) REFERENCES public.symbols(symbol) ON UPDATE CASCADE ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED;


--
-- Name: news_cache fk_news_cache_symbol; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.news_cache
    ADD CONSTRAINT fk_news_cache_symbol FOREIGN KEY (symbol) REFERENCES public.symbols(symbol) ON UPDATE CASCADE ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED;


--
-- Name: news_summary_log fk_news_summary_log_symbol; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.news_summary_log
    ADD CONSTRAINT fk_news_summary_log_symbol FOREIGN KEY (symbol) REFERENCES public.symbols(symbol) ON UPDATE CASCADE ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED;


--
-- Name: paper_trade_transactions fk_paper_trade_transactions_symbol; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.paper_trade_transactions
    ADD CONSTRAINT fk_paper_trade_transactions_symbol FOREIGN KEY (symbol) REFERENCES public.symbols(symbol) ON UPDATE CASCADE ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED;


--
-- Name: portfolio_positions fk_portfolio_positions_strategy; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.portfolio_positions
    ADD CONSTRAINT fk_portfolio_positions_strategy FOREIGN KEY (strategy_id) REFERENCES public.strategy_definitions(id) ON DELETE SET NULL;


--
-- Name: portfolio_positions fk_portfolio_positions_symbol; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.portfolio_positions
    ADD CONSTRAINT fk_portfolio_positions_symbol FOREIGN KEY (symbol) REFERENCES public.symbols(symbol) ON UPDATE CASCADE ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED;


--
-- Name: price_cache fk_price_cache_symbol; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.price_cache
    ADD CONSTRAINT fk_price_cache_symbol FOREIGN KEY (symbol) REFERENCES public.symbols(symbol) ON UPDATE CASCADE ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED;


--
-- Name: reference_cache fk_reference_cache_symbol; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reference_cache
    ADD CONSTRAINT fk_reference_cache_symbol FOREIGN KEY (symbol) REFERENCES public.symbols(symbol) ON UPDATE CASCADE ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED;


--
-- Name: short_interest_summary fk_short_interest_summary_symbol; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.short_interest_summary
    ADD CONSTRAINT fk_short_interest_summary_symbol FOREIGN KEY (symbol) REFERENCES public.symbols(symbol) ON DELETE CASCADE;


--
-- Name: short_interest fk_short_interest_symbol; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.short_interest
    ADD CONSTRAINT fk_short_interest_symbol FOREIGN KEY (symbol) REFERENCES public.symbols(symbol) ON UPDATE CASCADE ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED;


--
-- Name: strategy_definitions fk_strategy_definitions_symbol; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.strategy_definitions
    ADD CONSTRAINT fk_strategy_definitions_symbol FOREIGN KEY (symbol) REFERENCES public.symbols(symbol) ON UPDATE CASCADE ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED;


--
-- Name: strategy_reviews fk_strategy_reviews_symbol; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.strategy_reviews
    ADD CONSTRAINT fk_strategy_reviews_symbol FOREIGN KEY (symbol) REFERENCES public.symbols(symbol) ON UPDATE CASCADE ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED;


--
-- Name: strategy_definitions fk_strategy_seed; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.strategy_definitions
    ADD CONSTRAINT fk_strategy_seed FOREIGN KEY (seed_id) REFERENCES public.strategy_seeds(id) ON DELETE SET NULL;


--
-- Name: strategy_signals fk_strategy_signals_symbol; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.strategy_signals
    ADD CONSTRAINT fk_strategy_signals_symbol FOREIGN KEY (symbol) REFERENCES public.symbols(symbol) ON UPDATE CASCADE ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED;


--
-- Name: symbol_risk_metrics fk_symbol_risk_metrics_symbol; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.symbol_risk_metrics
    ADD CONSTRAINT fk_symbol_risk_metrics_symbol FOREIGN KEY (symbol) REFERENCES public.symbols(symbol) ON UPDATE CASCADE ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED;


--
-- Name: technical_indicators fk_technical_indicators_symbol; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.technical_indicators
    ADD CONSTRAINT fk_technical_indicators_symbol FOREIGN KEY (symbol) REFERENCES public.symbols(symbol) ON UPDATE CASCADE ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED;


--
-- Name: thesis_versions fk_thesis_versions_thesis_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.thesis_versions
    ADD CONSTRAINT fk_thesis_versions_thesis_id FOREIGN KEY (thesis_id) REFERENCES public.watchlist_thesis(id) ON DELETE CASCADE;


--
-- Name: user_article_feedback fk_user_article_feedback_user; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_article_feedback
    ADD CONSTRAINT fk_user_article_feedback_user FOREIGN KEY (user_id) REFERENCES public.user_preferences(id) ON DELETE CASCADE;


--
-- Name: valuation_metrics fk_valuation_metrics_symbol; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.valuation_metrics
    ADD CONSTRAINT fk_valuation_metrics_symbol FOREIGN KEY (symbol) REFERENCES public.symbols(symbol) ON DELETE CASCADE;


--
-- Name: watchlist_items fk_watchlist_items_symbol; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.watchlist_items
    ADD CONSTRAINT fk_watchlist_items_symbol FOREIGN KEY (symbol) REFERENCES public.symbols(symbol) ON UPDATE CASCADE ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED;


--
-- Name: watchlist_thesis fk_watchlist_thesis_symbol; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.watchlist_thesis
    ADD CONSTRAINT fk_watchlist_thesis_symbol FOREIGN KEY (symbol) REFERENCES public.watchlist_items(symbol) ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: household_debt_obligations household_debt_obligations_source_document_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.household_debt_obligations
    ADD CONSTRAINT household_debt_obligations_source_document_id_fkey FOREIGN KEY (source_document_id) REFERENCES public.household_documents(id) ON UPDATE CASCADE ON DELETE SET NULL;


--
-- Name: household_document_requirements household_document_requirements_satisfied_by_document_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.household_document_requirements
    ADD CONSTRAINT household_document_requirements_satisfied_by_document_id_fkey FOREIGN KEY (satisfied_by_document_id) REFERENCES public.household_documents(id) ON UPDATE CASCADE ON DELETE SET NULL;


--
-- Name: household_document_reviews household_document_reviews_document_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.household_document_reviews
    ADD CONSTRAINT household_document_reviews_document_id_fkey FOREIGN KEY (document_id) REFERENCES public.household_documents(id) ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: household_document_signatures household_document_signatures_sample_document_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.household_document_signatures
    ADD CONSTRAINT household_document_signatures_sample_document_id_fkey FOREIGN KEY (sample_document_id) REFERENCES public.household_documents(id) ON DELETE SET NULL;


--
-- Name: household_housing_costs household_housing_costs_source_document_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.household_housing_costs
    ADD CONSTRAINT household_housing_costs_source_document_id_fkey FOREIGN KEY (source_document_id) REFERENCES public.household_documents(id) ON UPDATE CASCADE ON DELETE SET NULL;


--
-- Name: household_import_rows household_import_rows_document_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.household_import_rows
    ADD CONSTRAINT household_import_rows_document_id_fkey FOREIGN KEY (document_id) REFERENCES public.household_documents(id) ON DELETE CASCADE;


--
-- Name: household_income_sources household_income_sources_source_document_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.household_income_sources
    ADD CONSTRAINT household_income_sources_source_document_id_fkey FOREIGN KEY (source_document_id) REFERENCES public.household_documents(id) ON UPDATE CASCADE ON DELETE SET NULL;


--
-- Name: household_inferred_values household_inferred_values_source_document_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.household_inferred_values
    ADD CONSTRAINT household_inferred_values_source_document_id_fkey FOREIGN KEY (source_document_id) REFERENCES public.household_documents(id) ON UPDATE CASCADE ON DELETE SET NULL;


--
-- Name: household_insurance_policies household_insurance_policies_source_document_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.household_insurance_policies
    ADD CONSTRAINT household_insurance_policies_source_document_id_fkey FOREIGN KEY (source_document_id) REFERENCES public.household_documents(id) ON UPDATE CASCADE ON DELETE SET NULL;


--
-- Name: household_members household_members_source_document_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.household_members
    ADD CONSTRAINT household_members_source_document_id_fkey FOREIGN KEY (source_document_id) REFERENCES public.household_documents(id) ON UPDATE CASCADE ON DELETE SET NULL;


--
-- Name: household_planned_expenses household_planned_expenses_source_document_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.household_planned_expenses
    ADD CONSTRAINT household_planned_expenses_source_document_id_fkey FOREIGN KEY (source_document_id) REFERENCES public.household_documents(id) ON UPDATE CASCADE ON DELETE SET NULL;


--
-- Name: household_questions household_questions_source_document_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.household_questions
    ADD CONSTRAINT household_questions_source_document_id_fkey FOREIGN KEY (source_document_id) REFERENCES public.household_documents(id) ON UPDATE CASCADE ON DELETE SET NULL;


--
-- Name: household_retirement_income_sources household_retirement_income_sources_source_document_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.household_retirement_income_sources
    ADD CONSTRAINT household_retirement_income_sources_source_document_id_fkey FOREIGN KEY (source_document_id) REFERENCES public.household_documents(id) ON UPDATE CASCADE ON DELETE SET NULL;


--
-- Name: household_transactions household_transactions_document_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.household_transactions
    ADD CONSTRAINT household_transactions_document_id_fkey FOREIGN KEY (document_id) REFERENCES public.household_documents(id) ON DELETE CASCADE;


--
-- Name: household_transactions household_transactions_merchant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.household_transactions
    ADD CONSTRAINT household_transactions_merchant_id_fkey FOREIGN KEY (merchant_id) REFERENCES public.household_merchants(id) ON DELETE SET NULL;


--
-- Name: jenny_agent_evaluations jenny_agent_evaluations_agent_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.jenny_agent_evaluations
    ADD CONSTRAINT jenny_agent_evaluations_agent_run_id_fkey FOREIGN KEY (agent_run_id) REFERENCES public.agent_runs(id) ON DELETE SET NULL;


--
-- Name: jenny_agent_evaluations jenny_agent_evaluations_routine_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.jenny_agent_evaluations
    ADD CONSTRAINT jenny_agent_evaluations_routine_id_fkey FOREIGN KEY (routine_id) REFERENCES public.jenny_routines(id) ON DELETE CASCADE;


--
-- Name: jenny_agent_evaluations jenny_agent_evaluations_symbol_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.jenny_agent_evaluations
    ADD CONSTRAINT jenny_agent_evaluations_symbol_fkey FOREIGN KEY (symbol) REFERENCES public.symbols(symbol) ON DELETE CASCADE;


--
-- Name: jenny_agent_evaluations jenny_agent_evaluations_thesis_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.jenny_agent_evaluations
    ADD CONSTRAINT jenny_agent_evaluations_thesis_id_fkey FOREIGN KEY (thesis_id) REFERENCES public.watchlist_thesis(id) ON DELETE SET NULL;


--
-- Name: jenny_notifications jenny_notifications_routine_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.jenny_notifications
    ADD CONSTRAINT jenny_notifications_routine_id_fkey FOREIGN KEY (routine_id) REFERENCES public.jenny_routines(id) ON DELETE SET NULL;


--
-- Name: jenny_notifications jenny_notifications_symbol_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.jenny_notifications
    ADD CONSTRAINT jenny_notifications_symbol_fkey FOREIGN KEY (symbol) REFERENCES public.symbols(symbol) ON DELETE SET NULL;


--
-- Name: jenny_trade_reviews jenny_trade_reviews_idea_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.jenny_trade_reviews
    ADD CONSTRAINT jenny_trade_reviews_idea_id_fkey FOREIGN KEY (idea_id) REFERENCES public.idea_outcomes(idea_id) ON DELETE SET NULL;


--
-- Name: jenny_trade_reviews jenny_trade_reviews_symbol_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.jenny_trade_reviews
    ADD CONSTRAINT jenny_trade_reviews_symbol_fkey FOREIGN KEY (symbol) REFERENCES public.symbols(symbol) ON DELETE CASCADE;


--
-- Name: jenny_trade_reviews jenny_trade_reviews_thesis_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.jenny_trade_reviews
    ADD CONSTRAINT jenny_trade_reviews_thesis_id_fkey FOREIGN KEY (thesis_id) REFERENCES public.watchlist_thesis(id) ON DELETE SET NULL;


--
-- Name: paper_trade_transactions paper_trade_transactions_agent_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.paper_trade_transactions
    ADD CONSTRAINT paper_trade_transactions_agent_run_id_fkey FOREIGN KEY (agent_run_id) REFERENCES public.agent_runs(id) ON DELETE SET NULL;


--
-- Name: paper_trade_transactions paper_trade_transactions_trade_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.paper_trade_transactions
    ADD CONSTRAINT paper_trade_transactions_trade_id_fkey FOREIGN KEY (trade_id) REFERENCES public.idea_outcomes(idea_id) ON DELETE CASCADE;


--
-- Name: portfolio_positions portfolio_positions_account_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.portfolio_positions
    ADD CONSTRAINT portfolio_positions_account_id_fkey FOREIGN KEY (account_id) REFERENCES public.portfolio_accounts(id) ON DELETE CASCADE;


--
-- Name: portfolio_snapshots portfolio_snapshots_account_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.portfolio_snapshots
    ADD CONSTRAINT portfolio_snapshots_account_id_fkey FOREIGN KEY (account_id) REFERENCES public.portfolio_accounts(id) ON DELETE CASCADE;


--
-- Name: portfolio_volatility_cache portfolio_volatility_cache_portfolio_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.portfolio_volatility_cache
    ADD CONSTRAINT portfolio_volatility_cache_portfolio_id_fkey FOREIGN KEY (portfolio_id) REFERENCES public.portfolio_accounts(id) ON DELETE CASCADE;


--
-- Name: sitemap_entries sitemap_entries_artifact_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sitemap_entries
    ADD CONSTRAINT sitemap_entries_artifact_id_fkey FOREIGN KEY (artifact_id) REFERENCES public.artifacts(id) ON DELETE SET NULL;


--
-- Name: sitemap_health_history sitemap_health_history_sitemap_entry_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sitemap_health_history
    ADD CONSTRAINT sitemap_health_history_sitemap_entry_id_fkey FOREIGN KEY (sitemap_entry_id) REFERENCES public.sitemap_entries(id) ON DELETE CASCADE;


--
-- Name: source_credentials source_credentials_source_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.source_credentials
    ADD CONSTRAINT source_credentials_source_id_fkey FOREIGN KEY (source_id) REFERENCES public.source_registry(source_id) ON DELETE CASCADE;


--
-- Name: strategy_lineage strategy_lineage_child_strategy_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.strategy_lineage
    ADD CONSTRAINT strategy_lineage_child_strategy_id_fkey FOREIGN KEY (child_strategy_id) REFERENCES public.strategy_definitions(id) ON DELETE CASCADE;


--
-- Name: strategy_lineage strategy_lineage_parent_strategy_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.strategy_lineage
    ADD CONSTRAINT strategy_lineage_parent_strategy_id_fkey FOREIGN KEY (parent_strategy_id) REFERENCES public.strategy_definitions(id) ON DELETE SET NULL;


--
-- Name: strategy_performance strategy_performance_strategy_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.strategy_performance
    ADD CONSTRAINT strategy_performance_strategy_id_fkey FOREIGN KEY (strategy_id) REFERENCES public.strategy_definitions(id) ON DELETE CASCADE;


--
-- Name: strategy_reviews strategy_reviews_agent_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.strategy_reviews
    ADD CONSTRAINT strategy_reviews_agent_run_id_fkey FOREIGN KEY (agent_run_id) REFERENCES public.agent_runs(id) ON DELETE SET NULL;


--
-- Name: strategy_seeds strategy_seeds_strategy_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.strategy_seeds
    ADD CONSTRAINT strategy_seeds_strategy_id_fkey FOREIGN KEY (strategy_id) REFERENCES public.strategy_definitions(id);


--
-- Name: strategy_seeds strategy_seeds_symbol_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.strategy_seeds
    ADD CONSTRAINT strategy_seeds_symbol_fkey FOREIGN KEY (symbol) REFERENCES public.symbols(symbol) ON DELETE RESTRICT;


--
-- Name: strategy_signals strategy_signals_strategy_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.strategy_signals
    ADD CONSTRAINT strategy_signals_strategy_id_fkey FOREIGN KEY (strategy_id) REFERENCES public.strategy_definitions(id) ON DELETE CASCADE;


--
-- Name: symbol_workflow_events symbol_workflow_events_symbol_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.symbol_workflow_events
    ADD CONSTRAINT symbol_workflow_events_symbol_fkey FOREIGN KEY (symbol) REFERENCES public.symbol_workflows(symbol) ON DELETE CASCADE;


--
-- Name: symbol_workflows symbol_workflows_symbol_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.symbol_workflows
    ADD CONSTRAINT symbol_workflows_symbol_fkey FOREIGN KEY (symbol) REFERENCES public.symbols(symbol) ON DELETE CASCADE;


--
-- Name: vision_goal_details vision_goal_details_goal_code_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vision_goal_details
    ADD CONSTRAINT vision_goal_details_goal_code_fkey FOREIGN KEY (goal_code) REFERENCES public.vision_goals(code) ON DELETE CASCADE;


--
-- Name: watchlist_narrative watchlist_narrative_snapshot_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.watchlist_narrative
    ADD CONSTRAINT watchlist_narrative_snapshot_id_fkey FOREIGN KEY (snapshot_id) REFERENCES public.watchlist_snapshots_core(id) ON DELETE CASCADE;


--
-- Name: watchlist_news_summary watchlist_news_summary_snapshot_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.watchlist_news_summary
    ADD CONSTRAINT watchlist_news_summary_snapshot_id_fkey FOREIGN KEY (snapshot_id) REFERENCES public.watchlist_snapshots_core(id) ON DELETE CASCADE;


--
-- Name: watchlist_snapshots_core watchlist_snapshots_core_item_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.watchlist_snapshots_core
    ADD CONSTRAINT watchlist_snapshots_core_item_id_fkey FOREIGN KEY (item_id) REFERENCES public.watchlist_items(id) ON DELETE CASCADE;


--
-- Name: watchlist_snapshots watchlist_snapshots_item_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.watchlist_snapshots
    ADD CONSTRAINT watchlist_snapshots_item_id_fkey FOREIGN KEY (item_id) REFERENCES public.watchlist_items(id) ON DELETE CASCADE;


--
-- Name: watchlist_technical_metrics watchlist_technical_metrics_snapshot_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.watchlist_technical_metrics
    ADD CONSTRAINT watchlist_technical_metrics_snapshot_id_fkey FOREIGN KEY (snapshot_id) REFERENCES public.watchlist_snapshots_core(id) ON DELETE CASCADE;


--
-- PostgreSQL database dump complete
--

\unrestrict vkRqVkwyYCmVowZW2ufUzKpekNWJXTQWEO9gJhoIOnqaZgyp4PioeKk2flFDqaM

