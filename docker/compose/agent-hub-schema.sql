--
-- PostgreSQL database dump
--

\restrict vDbgLE1H1T4i660of1VpcSbuVAkJkW7cRGzQVdX4HhHLY5iSjmOqh1kk60UnTkS

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
-- Name: branch_status_enum; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.branch_status_enum AS ENUM (
    'active',
    'promoted',
    'discarded'
);


--
-- Name: client_status_enum; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.client_status_enum AS ENUM (
    'active',
    'suspended',
    'blocked'
);


--
-- Name: client_type_enum; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.client_type_enum AS ENUM (
    'internal',
    'external',
    'service'
);


--
-- Name: feedback_type; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.feedback_type AS ENUM (
    'positive',
    'negative'
);


--
-- Name: manual_outcome_enum; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.manual_outcome_enum AS ENUM (
    'selected',
    'discarded'
);


--
-- Name: rejection_reason_enum; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.rejection_reason_enum AS ENUM (
    'missing_required_headers',
    'authentication_failed',
    'client_suspended',
    'client_blocked',
    'rate_limited',
    'client_not_found'
);


--
-- Name: roundtable_mode; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.roundtable_mode AS ENUM (
    'quick',
    'deliberation'
);


--
-- Name: roundtable_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.roundtable_status AS ENUM (
    'active',
    'completed',
    'failed'
);


--
-- Name: roundtable_tool_mode; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.roundtable_tool_mode AS ENUM (
    'read_only',
    'yolo'
);


--
-- Name: session_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.session_status AS ENUM (
    'active',
    'completed',
    'failed'
);


--
-- Name: session_type_enum; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.session_type_enum AS ENUM (
    'completion',
    'chat',
    'roundtable',
    'image_generation',
    'agent',
    'claude_code'
);


--
-- Name: task_outcome_enum; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.task_outcome_enum AS ENUM (
    'passed',
    'failed'
);


--
-- Name: tone_type; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.tone_type AS ENUM (
    'professional',
    'friendly',
    'technical'
);


--
-- Name: tool_type_enum; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.tool_type_enum AS ENUM (
    'api',
    'cli',
    'sdk'
);


--
-- Name: usage_metric_type; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.usage_metric_type AS ENUM (
    'loaded',
    'referenced',
    'success',
    'helpful',
    'harmful'
);


--
-- Name: verbosity_level; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.verbosity_level AS ENUM (
    'concise',
    'normal',
    'detailed'
);


--
-- Name: workstream_status_enum; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.workstream_status_enum AS ENUM (
    'authoritative',
    'superseded',
    'retired'
);


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: agent_benchmark_attempts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agent_benchmark_attempts (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    benchmark_run_id uuid NOT NULL,
    agent_slug character varying(100) NOT NULL,
    model_id character varying(200) NOT NULL,
    effective_model character varying(200),
    requested_model character varying(200),
    case_id character varying(100) NOT NULL,
    run_number integer NOT NULL,
    session_id character varying(100),
    provider character varying(100),
    latency_ms integer DEFAULT 0 NOT NULL,
    input_tokens integer DEFAULT 0 NOT NULL,
    output_tokens integer DEFAULT 0 NOT NULL,
    total_tokens integer DEFAULT 0 NOT NULL,
    turns integer DEFAULT 0 NOT NULL,
    tool_calls_count integer DEFAULT 0 NOT NULL,
    used_tool_names jsonb DEFAULT '[]'::jsonb NOT NULL,
    schema_valid boolean DEFAULT false NOT NULL,
    tool_requirement_met boolean DEFAULT true NOT NULL,
    correctness_score double precision DEFAULT '0'::double precision NOT NULL,
    composite_score double precision DEFAULT '0'::double precision NOT NULL,
    passed boolean DEFAULT false NOT NULL,
    infra_failure boolean DEFAULT false NOT NULL,
    failure_kind character varying(20),
    failure_detail text,
    fallback_used boolean DEFAULT false NOT NULL,
    primary_action character varying(32),
    should_dispatch boolean,
    should_close boolean,
    confidence character varying(16),
    summary text,
    raw_content text DEFAULT ''::text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: agent_benchmark_experiments; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agent_benchmark_experiments (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    experiment_key character varying(120) NOT NULL,
    agent_slug character varying(100) NOT NULL,
    project_id character varying(100) NOT NULL,
    suite_id character varying(100) NOT NULL,
    name character varying(160) NOT NULL,
    hypothesis text,
    status character varying(20) DEFAULT 'open'::character varying NOT NULL,
    decision character varying(20) DEFAULT 'hold'::character varying NOT NULL,
    decision_reason text,
    baseline_label character varying(60) DEFAULT 'baseline'::character varying NOT NULL,
    candidate_label character varying(60) DEFAULT 'candidate'::character varying NOT NULL,
    min_runs_per_cohort integer DEFAULT 3 NOT NULL,
    evidence jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: agent_benchmark_runs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agent_benchmark_runs (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    benchmark_id character varying(100) NOT NULL,
    agent_slug character varying(100) NOT NULL,
    project_id character varying(100) NOT NULL,
    suite_id character varying(100) NOT NULL,
    run_kind character varying(32) NOT NULL,
    status character varying(20) DEFAULT 'completed'::character varying NOT NULL,
    models jsonb DEFAULT '[]'::jsonb NOT NULL,
    case_ids jsonb DEFAULT '[]'::jsonb NOT NULL,
    runs_per_case integer DEFAULT 1 NOT NULL,
    use_memory boolean DEFAULT false NOT NULL,
    seed integer,
    avg_score double precision,
    pass_rate double precision,
    attempt_count integer DEFAULT 0 NOT NULL,
    passed_attempt_count integer DEFAULT 0 NOT NULL,
    infra_failure_count integer DEFAULT 0 NOT NULL,
    config_snapshot jsonb DEFAULT '{}'::jsonb NOT NULL,
    metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    started_at timestamp with time zone NOT NULL,
    completed_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    experiment_id uuid,
    experiment_cohort character varying(20)
);


--
-- Name: agent_performance_logs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agent_performance_logs (
    id integer NOT NULL,
    agent_slug character varying(100) NOT NULL,
    model_id character varying(200) NOT NULL,
    task_type character varying(50),
    project_id character varying(100),
    outcome character varying(20) NOT NULL,
    feedback_type character varying(20) NOT NULL,
    duration_ms integer,
    input_tokens integer,
    output_tokens integer,
    tool_calls_count integer,
    turns integer,
    content text NOT NULL,
    session_id character varying(100),
    logged_by character varying(20) DEFAULT 'persona'::character varying NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: agent_performance_logs_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.agent_performance_logs_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: agent_performance_logs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.agent_performance_logs_id_seq OWNED BY public.agent_performance_logs.id;


--
-- Name: agent_prompts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agent_prompts (
    id integer NOT NULL,
    agent_id integer NOT NULL,
    prompt_id integer NOT NULL,
    role character varying(100) NOT NULL,
    priority integer DEFAULT 0 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: agent_prompts_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.agent_prompts_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: agent_prompts_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.agent_prompts_id_seq OWNED BY public.agent_prompts.id;


--
-- Name: agent_regression_clusters; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agent_regression_clusters (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    agent_slug character varying(100) NOT NULL,
    suite_id character varying(100) NOT NULL,
    regression_key character varying(255) NOT NULL,
    case_id character varying(100) NOT NULL,
    failure_detail text NOT NULL,
    status character varying(20) DEFAULT 'open'::character varying NOT NULL,
    first_seen_run_id uuid,
    last_seen_run_id uuid,
    occurrence_count integer DEFAULT 0 NOT NULL,
    latest_avg_score double precision,
    affected_models jsonb DEFAULT '[]'::jsonb NOT NULL,
    metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    opened_at timestamp with time zone DEFAULT now() NOT NULL,
    last_seen_at timestamp with time zone DEFAULT now() NOT NULL,
    resolved_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: agent_versions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agent_versions (
    id integer NOT NULL,
    agent_id integer NOT NULL,
    version integer NOT NULL,
    config_snapshot json NOT NULL,
    changed_by character varying(100),
    change_reason text,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: agent_versions_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.agent_versions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: agent_versions_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.agent_versions_id_seq OWNED BY public.agent_versions.id;


--
-- Name: agents; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agents (
    id integer NOT NULL,
    slug character varying(50) NOT NULL,
    name character varying(100) NOT NULL,
    description text,
    system_prompt text NOT NULL,
    primary_model_id character varying(100) NOT NULL,
    fallback_models json DEFAULT '[]'::json NOT NULL,
    escalation_model_id character varying(100),
    strategies json DEFAULT '{}'::json NOT NULL,
    temperature double precision DEFAULT '0.7'::double precision NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    version integer DEFAULT 1 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    is_coding_agent boolean DEFAULT false NOT NULL,
    tool_permissions json,
    thinking_level character varying(20),
    memory_config json,
    max_concurrency integer,
    max_subagent_concurrency integer,
    daily_token_budget integer,
    hourly_request_limit integer,
    timeout_seconds double precision,
    verbosity_level character varying(10)
);


--
-- Name: agents_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.agents_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: agents_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.agents_id_seq OWNED BY public.agents.id;


--
-- Name: alembic_version; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.alembic_version (
    version_num character varying(32) NOT NULL
);


--
-- Name: api_keys; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.api_keys (
    id integer NOT NULL,
    key_hash character varying(64) NOT NULL,
    key_prefix character varying(20) NOT NULL,
    name character varying(100),
    project_id character varying(100) NOT NULL,
    rate_limit_rpm integer NOT NULL,
    rate_limit_tpm integer NOT NULL,
    is_active integer NOT NULL,
    last_used_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    expires_at timestamp with time zone
);


--
-- Name: api_keys_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.api_keys_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: api_keys_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.api_keys_id_seq OWNED BY public.api_keys.id;


--
-- Name: client_controls; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.client_controls (
    id integer NOT NULL,
    client_name character varying(100) NOT NULL,
    enabled boolean DEFAULT true NOT NULL,
    disabled_at timestamp with time zone,
    disabled_by character varying(100),
    reason text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: client_controls_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.client_controls_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: client_controls_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.client_controls_id_seq OWNED BY public.client_controls.id;


--
-- Name: clients; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.clients (
    id character varying(36) NOT NULL,
    display_name character varying(100) NOT NULL,
    client_type public.client_type_enum NOT NULL,
    status public.client_status_enum NOT NULL,
    rate_limit_rpm integer NOT NULL,
    rate_limit_tpm integer NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    last_used_at timestamp with time zone,
    suspended_at timestamp with time zone,
    suspended_by character varying(100),
    suspension_reason text,
    allowed_projects text
);


--
-- Name: cost_logs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.cost_logs (
    id integer NOT NULL,
    session_id character varying(36) NOT NULL,
    model character varying(100) NOT NULL,
    input_tokens integer NOT NULL,
    output_tokens integer NOT NULL,
    cost_usd double precision NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: cost_logs_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.cost_logs_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: cost_logs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.cost_logs_id_seq OWNED BY public.cost_logs.id;


--
-- Name: credentials; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.credentials (
    id integer NOT NULL,
    provider character varying(100) NOT NULL,
    credential_type character varying(50) NOT NULL,
    value_encrypted bytea NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: credentials_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.credentials_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: credentials_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.credentials_id_seq OWNED BY public.credentials.id;


--
-- Name: feedback_items; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.feedback_items (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    component_id character varying(50) NOT NULL,
    feedback_type character varying(20) NOT NULL,
    title character varying(200) NOT NULL,
    description text,
    severity character varying(10),
    status character varying(20) DEFAULT 'open'::character varying NOT NULL,
    project_id character varying(50) NOT NULL,
    created_by_session_id character varying(36),
    agent_slug character varying(100),
    model_used character varying(50),
    session_type character varying(50),
    resolved_at timestamp with time zone,
    resolution_note text,
    vote_count integer DEFAULT 1 NOT NULL,
    linked_task_id character varying(50),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    search_vector tsvector GENERATED ALWAYS AS (to_tsvector('english'::regconfig, (((COALESCE(title, ''::character varying))::text || ' '::text) || COALESCE(description, ''::text)))) STORED,
    CONSTRAINT ck_feedback_items_ck_feedback_items_status CHECK (((status)::text = ANY ((ARRAY['open'::character varying, 'acknowledged'::character varying, 'resolved'::character varying, 'wont_fix'::character varying, 'archived'::character varying])::text[]))),
    CONSTRAINT ck_feedback_items_ck_feedback_items_type CHECK (((feedback_type)::text = ANY ((ARRAY['friction'::character varying, 'idea'::character varying, 'improvement'::character varying, 'praise'::character varying])::text[])))
);


--
-- Name: feedback_votes; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.feedback_votes (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    feedback_item_id uuid NOT NULL,
    session_id character varying(36) NOT NULL,
    comment text,
    agent_slug character varying(100),
    model_used character varying(50),
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: memories; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.memories (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    content text NOT NULL,
    name character varying(500),
    summary text,
    embedding public.vector(768),
    memory_type character varying(20) NOT NULL,
    scope character varying(100) DEFAULT 'global'::character varying NOT NULL,
    scope_id character varying(100),
    group_id character varying(100),
    source character varying(100),
    source_description text,
    tags text[],
    tier smallint DEFAULT 3 NOT NULL,
    pinned boolean DEFAULT false NOT NULL,
    auto_inject boolean DEFAULT false NOT NULL,
    display_order integer DEFAULT 50,
    trigger_task_types text[],
    trigger_phases text[],
    loaded_count integer DEFAULT 0 NOT NULL,
    referenced_count integer DEFAULT 0 NOT NULL,
    helpful_count integer DEFAULT 0 NOT NULL,
    harmful_count integer DEFAULT 0 NOT NULL,
    status character varying(20) DEFAULT 'active'::character varying NOT NULL,
    token_count integer,
    demoted_at timestamp with time zone,
    demotion_reason character varying(200),
    metadata jsonb DEFAULT '{}'::jsonb,
    valid_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    last_accessed_at timestamp with time zone,
    lifecycle_score double precision,
    lifecycle_score_updated_at timestamp with time zone,
    retired_at timestamp with time zone,
    superseded_by uuid,
    version integer DEFAULT 1 NOT NULL
);


--
-- Name: memory_injection_metrics; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.memory_injection_metrics (
    id integer NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    session_id character varying(36),
    external_id character varying(100),
    project_id character varying(100),
    injection_latency_ms integer,
    mandates_count integer NOT NULL,
    guardrails_count integer NOT NULL,
    reference_count integer NOT NULL,
    total_tokens integer NOT NULL,
    query text,
    variant character varying(20) NOT NULL,
    task_succeeded boolean,
    retries integer,
    memories_cited json,
    memories_loaded json,
    reference_selected_count integer DEFAULT 0 NOT NULL,
    reference_index_count integer DEFAULT 0 NOT NULL,
    reference_cited_count integer DEFAULT 0 NOT NULL,
    reference_selected_uuids json,
    reference_index_uuids json
);


--
-- Name: memory_injection_metrics_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.memory_injection_metrics_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: memory_injection_metrics_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.memory_injection_metrics_id_seq OWNED BY public.memory_injection_metrics.id;


--
-- Name: memory_revisions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.memory_revisions (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    memory_id uuid,
    memory_uuid character varying(36) NOT NULL,
    version integer NOT NULL,
    action character varying(20) NOT NULL,
    content text NOT NULL,
    name character varying(500),
    summary text,
    memory_type character varying(20) NOT NULL,
    scope character varying(100) NOT NULL,
    scope_id character varying(100),
    group_id character varying(100),
    source character varying(100),
    source_description text,
    tags character varying[] DEFAULT '{}'::character varying[] NOT NULL,
    tier smallint NOT NULL,
    pinned boolean DEFAULT false NOT NULL,
    auto_inject boolean DEFAULT false NOT NULL,
    display_order integer DEFAULT 50 NOT NULL,
    trigger_task_types character varying[] DEFAULT '{}'::character varying[] NOT NULL,
    trigger_phases character varying[] DEFAULT '{}'::character varying[] NOT NULL,
    token_count integer,
    status character varying(20) NOT NULL,
    metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    valid_at timestamp with time zone,
    content_hash character varying(64) NOT NULL,
    changed_by character varying(100),
    change_reason text,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: memory_settings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.memory_settings (
    id integer NOT NULL,
    enabled boolean DEFAULT true NOT NULL,
    total_budget integer DEFAULT 2000 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    budget_enabled boolean DEFAULT true NOT NULL,
    max_mandates integer DEFAULT 0 NOT NULL,
    max_guardrails integer DEFAULT 0 NOT NULL,
    reference_index_enabled boolean DEFAULT true NOT NULL,
    continuity_enabled boolean DEFAULT true NOT NULL,
    continuity_max_sessions integer DEFAULT 5 NOT NULL
);


--
-- Name: memory_settings_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.memory_settings_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: memory_settings_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.memory_settings_id_seq OWNED BY public.memory_settings.id;


--
-- Name: model_enrichments; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.model_enrichments (
    id integer NOT NULL,
    model_id character varying(200) NOT NULL,
    ext_coding integer,
    ext_reasoning integer,
    ext_speed_tier character varying(20),
    ext_input_per_m double precision,
    ext_output_per_m double precision,
    raw_benchmark_data jsonb,
    source character varying(100) DEFAULT 'models.dev'::character varying NOT NULL,
    synced_at timestamp with time zone DEFAULT now() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    ext_tool_use integer,
    ext_planning integer,
    ext_instruction integer
);


--
-- Name: model_enrichments_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.model_enrichments_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: model_enrichments_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.model_enrichments_id_seq OWNED BY public.model_enrichments.id;


--
-- Name: persona; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.persona (
    id integer NOT NULL,
    agent_id integer NOT NULL,
    name character varying(100) DEFAULT 'Johnny'::character varying NOT NULL,
    personality text,
    voice_id character varying(200) DEFAULT 'en-US-AriaNeural'::character varying,
    voice_enabled boolean DEFAULT false,
    heartbeat_interval_minutes integer DEFAULT 60,
    avatar_url character varying(500),
    greeting text,
    version integer DEFAULT 1,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    user_context text,
    onboarding_complete boolean DEFAULT false NOT NULL,
    onboarding_phase character varying(20) DEFAULT 'not_started'::character varying NOT NULL,
    session_reset_mode character varying(10) DEFAULT 'off'::character varying NOT NULL,
    session_reset_hour integer DEFAULT 9 NOT NULL,
    session_reset_idle_minutes integer DEFAULT 120 NOT NULL,
    limits jsonb,
    onboarding_attempts integer DEFAULT 0 NOT NULL,
    user_context_previous text,
    personality_previous text,
    execution_state character varying(16) DEFAULT 'active'::character varying NOT NULL,
    user_profile jsonb
);


--
-- Name: persona_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.persona_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: persona_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.persona_id_seq OWNED BY public.persona.id;


--
-- Name: persona_scheduled_jobs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.persona_scheduled_jobs (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    persona_id integer NOT NULL,
    name character varying(200) NOT NULL,
    schedule_type character varying(20) NOT NULL,
    schedule_value character varying(100) NOT NULL,
    schedule_timezone character varying(50) DEFAULT 'UTC'::character varying,
    payload_type character varying(20) DEFAULT 'agent_turn'::character varying,
    payload_message text NOT NULL,
    payload_title character varying(200),
    delivery character varying(20) DEFAULT 'none'::character varying,
    enabled boolean DEFAULT true,
    last_run_at timestamp with time zone,
    next_run_at timestamp with time zone,
    run_count integer DEFAULT 0,
    max_runs integer,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: project_permissions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.project_permissions (
    id integer NOT NULL,
    project_id character varying(100) NOT NULL,
    permission_tier character varying(10) DEFAULT 'read'::character varying NOT NULL,
    auto_exec_enabled boolean DEFAULT false NOT NULL,
    execution_start_hour integer DEFAULT 0 NOT NULL,
    execution_end_hour integer DEFAULT 24 NOT NULL,
    root_path character varying(500),
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    daily_cost_budget_usd double precision,
    monthly_cost_budget_usd double precision,
    budget_alert_threshold double precision DEFAULT '0.8'::double precision NOT NULL
);


--
-- Name: project_permissions_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.project_permissions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: project_permissions_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.project_permissions_id_seq OWNED BY public.project_permissions.id;


--
-- Name: prompt_revisions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.prompt_revisions (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    prompt_id integer,
    prompt_slug character varying(100) NOT NULL,
    prompt_name character varying(200) NOT NULL,
    action character varying(20) NOT NULL,
    content text NOT NULL,
    description text,
    is_global boolean DEFAULT false NOT NULL,
    enabled boolean DEFAULT true NOT NULL,
    exclude_agents json DEFAULT '[]'::json NOT NULL,
    content_hash character varying(64) NOT NULL,
    changed_by character varying(100),
    change_reason text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    owner_agent_id integer,
    prompt_type character varying(50) DEFAULT 'standard'::character varying NOT NULL,
    deletion_locked boolean DEFAULT false NOT NULL
);


--
-- Name: prompts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.prompts (
    id integer NOT NULL,
    slug character varying(100) NOT NULL,
    name character varying(200) NOT NULL,
    content text NOT NULL,
    description text,
    is_global boolean DEFAULT false NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    exclude_agents json DEFAULT '[]'::json NOT NULL,
    enabled boolean DEFAULT true NOT NULL,
    owner_agent_id integer,
    prompt_type character varying(50) DEFAULT 'standard'::character varying NOT NULL,
    deletion_locked boolean DEFAULT false NOT NULL
);


--
-- Name: prompts_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.prompts_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: prompts_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.prompts_id_seq OWNED BY public.prompts.id;


--
-- Name: push_subscriptions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.push_subscriptions (
    id character varying(8) NOT NULL,
    endpoint text NOT NULL,
    p256dh_key text NOT NULL,
    auth_key text NOT NULL,
    user_email character varying(255),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    last_used_at timestamp with time zone
);


--
-- Name: request_logs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.request_logs (
    id integer NOT NULL,
    client_id character varying(36),
    request_source character varying(100),
    endpoint character varying(200) NOT NULL,
    method character varying(10) NOT NULL,
    status_code integer NOT NULL,
    rejection_reason public.rejection_reason_enum,
    tokens_in integer,
    tokens_out integer,
    latency_ms integer,
    model character varying(100),
    session_id character varying(36),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    agent_slug character varying(50),
    tool_type public.tool_type_enum DEFAULT 'api'::public.tool_type_enum NOT NULL,
    tool_name character varying(100),
    source_path character varying(500),
    timed_out boolean DEFAULT false NOT NULL,
    used_fallback boolean DEFAULT false NOT NULL,
    fallback_model character varying(100)
);


--
-- Name: request_logs_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.request_logs_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: request_logs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.request_logs_id_seq OWNED BY public.request_logs.id;


--
-- Name: session_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.session_events (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    session_id character varying(36) NOT NULL,
    turn integer NOT NULL,
    sequence integer NOT NULL,
    event_type character varying(50) NOT NULL,
    role character varying(20),
    content text,
    tool_name character varying(255),
    tool_input jsonb,
    tool_output jsonb,
    tokens integer,
    duration_ms integer,
    model_used character varying(100),
    agent_id character varying(100),
    agent_name character varying(100),
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: session_summary_segments; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.session_summary_segments (
    id bigint NOT NULL,
    session_id character varying(36) NOT NULL,
    summary_oneliner text NOT NULL,
    summary_outcome character varying(20),
    summary_git_digest text,
    summary_branch character varying(200),
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: session_summary_segments_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.session_summary_segments_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: session_summary_segments_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.session_summary_segments_id_seq OWNED BY public.session_summary_segments.id;


--
-- Name: sessions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sessions (
    id character varying(36) NOT NULL,
    project_id character varying(100) NOT NULL,
    provider character varying(20) NOT NULL,
    model character varying(100) NOT NULL,
    status public.session_status NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    provider_metadata json,
    session_type public.session_type_enum DEFAULT 'completion'::public.session_type_enum NOT NULL,
    external_id character varying(100),
    client_id character varying(36),
    request_source character varying(100),
    models_used json,
    providers_used json,
    agent_slug character varying(50),
    parent_session_id character varying(36),
    fork_point_turn integer,
    pending_patches json,
    branch_status public.branch_status_enum,
    manual_outcome public.manual_outcome_enum,
    summary_oneliner text,
    summary_outcome character varying(20),
    summary_files_touched json,
    summary_branch character varying(200),
    summary_generated_at timestamp with time zone,
    summary_git_digest text,
    current_branch character varying(200),
    workstream_status public.workstream_status_enum,
    workstream_note text,
    workstream_updated_at timestamp with time zone,
    declared_scope_paths json,
    observed_read_paths json,
    observed_write_paths json,
    scope_confidence character varying(32),
    last_heartbeat_at timestamp with time zone,
    last_activity_at timestamp with time zone,
    health_detail character varying(100)
);


--
-- Name: tier_change_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.tier_change_log (
    id integer NOT NULL,
    episode_uuid character varying(36) NOT NULL,
    old_tier character varying(20) NOT NULL,
    new_tier character varying(20) NOT NULL,
    reason text NOT NULL,
    change_type character varying(20) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    lifecycle_score_before double precision,
    lifecycle_score_after double precision,
    metadata jsonb DEFAULT '{}'::jsonb
);


--
-- Name: tier_change_log_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.tier_change_log_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: tier_change_log_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.tier_change_log_id_seq OWNED BY public.tier_change_log.id;


--
-- Name: truncation_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.truncation_events (
    id integer NOT NULL,
    session_id character varying(36),
    model character varying(100) NOT NULL,
    endpoint character varying(50) NOT NULL,
    max_tokens_requested integer NOT NULL,
    output_tokens integer NOT NULL,
    model_limit integer NOT NULL,
    was_capped integer NOT NULL,
    project_id character varying(100),
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: truncation_events_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.truncation_events_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: truncation_events_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.truncation_events_id_seq OWNED BY public.truncation_events.id;


--
-- Name: usage_stats; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.usage_stats (
    id integer NOT NULL,
    episode_uuid character varying(36) NOT NULL,
    metric_type public.usage_metric_type NOT NULL,
    value integer NOT NULL,
    "timestamp" timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: usage_stats_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.usage_stats_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: usage_stats_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.usage_stats_id_seq OWNED BY public.usage_stats.id;


--
-- Name: user_preferences; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.user_preferences (
    id integer NOT NULL,
    key character varying(100) NOT NULL,
    value character varying(500) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: user_preferences_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.user_preferences_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: user_preferences_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.user_preferences_id_seq OWNED BY public.user_preferences.id;


--
-- Name: webhook_subscriptions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.webhook_subscriptions (
    id integer NOT NULL,
    url character varying(2048) NOT NULL,
    secret character varying(64) NOT NULL,
    event_types json NOT NULL,
    project_id character varying(100),
    is_active integer NOT NULL,
    description character varying(255),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    failure_count integer NOT NULL
);


--
-- Name: webhook_subscriptions_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.webhook_subscriptions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: webhook_subscriptions_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.webhook_subscriptions_id_seq OWNED BY public.webhook_subscriptions.id;


--
-- Name: agent_performance_logs id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_performance_logs ALTER COLUMN id SET DEFAULT nextval('public.agent_performance_logs_id_seq'::regclass);


--
-- Name: agent_prompts id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_prompts ALTER COLUMN id SET DEFAULT nextval('public.agent_prompts_id_seq'::regclass);


--
-- Name: agent_versions id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_versions ALTER COLUMN id SET DEFAULT nextval('public.agent_versions_id_seq'::regclass);


--
-- Name: agents id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agents ALTER COLUMN id SET DEFAULT nextval('public.agents_id_seq'::regclass);


--
-- Name: api_keys id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.api_keys ALTER COLUMN id SET DEFAULT nextval('public.api_keys_id_seq'::regclass);


--
-- Name: client_controls id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.client_controls ALTER COLUMN id SET DEFAULT nextval('public.client_controls_id_seq'::regclass);


--
-- Name: cost_logs id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cost_logs ALTER COLUMN id SET DEFAULT nextval('public.cost_logs_id_seq'::regclass);


--
-- Name: credentials id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.credentials ALTER COLUMN id SET DEFAULT nextval('public.credentials_id_seq'::regclass);


--
-- Name: memory_injection_metrics id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.memory_injection_metrics ALTER COLUMN id SET DEFAULT nextval('public.memory_injection_metrics_id_seq'::regclass);


--
-- Name: memory_settings id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.memory_settings ALTER COLUMN id SET DEFAULT nextval('public.memory_settings_id_seq'::regclass);


--
-- Name: model_enrichments id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.model_enrichments ALTER COLUMN id SET DEFAULT nextval('public.model_enrichments_id_seq'::regclass);


--
-- Name: persona id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.persona ALTER COLUMN id SET DEFAULT nextval('public.persona_id_seq'::regclass);


--
-- Name: project_permissions id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.project_permissions ALTER COLUMN id SET DEFAULT nextval('public.project_permissions_id_seq'::regclass);


--
-- Name: prompts id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.prompts ALTER COLUMN id SET DEFAULT nextval('public.prompts_id_seq'::regclass);


--
-- Name: request_logs id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.request_logs ALTER COLUMN id SET DEFAULT nextval('public.request_logs_id_seq'::regclass);


--
-- Name: session_summary_segments id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.session_summary_segments ALTER COLUMN id SET DEFAULT nextval('public.session_summary_segments_id_seq'::regclass);


--
-- Name: tier_change_log id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tier_change_log ALTER COLUMN id SET DEFAULT nextval('public.tier_change_log_id_seq'::regclass);


--
-- Name: truncation_events id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.truncation_events ALTER COLUMN id SET DEFAULT nextval('public.truncation_events_id_seq'::regclass);


--
-- Name: usage_stats id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.usage_stats ALTER COLUMN id SET DEFAULT nextval('public.usage_stats_id_seq'::regclass);


--
-- Name: user_preferences id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_preferences ALTER COLUMN id SET DEFAULT nextval('public.user_preferences_id_seq'::regclass);


--
-- Name: webhook_subscriptions id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.webhook_subscriptions ALTER COLUMN id SET DEFAULT nextval('public.webhook_subscriptions_id_seq'::regclass);


--
-- Name: agent_benchmark_experiments agent_benchmark_experiments_experiment_key_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_benchmark_experiments
    ADD CONSTRAINT agent_benchmark_experiments_experiment_key_key UNIQUE (experiment_key);


--
-- Name: agent_benchmark_runs agent_benchmark_runs_benchmark_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_benchmark_runs
    ADD CONSTRAINT agent_benchmark_runs_benchmark_id_key UNIQUE (benchmark_id);


--
-- Name: agent_versions agent_versions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_versions
    ADD CONSTRAINT agent_versions_pkey PRIMARY KEY (id);


--
-- Name: agents agents_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agents
    ADD CONSTRAINT agents_pkey PRIMARY KEY (id);


--
-- Name: alembic_version alembic_version_pkc; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alembic_version
    ADD CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num);


--
-- Name: api_keys api_keys_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.api_keys
    ADD CONSTRAINT api_keys_pkey PRIMARY KEY (id);


--
-- Name: client_controls client_controls_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.client_controls
    ADD CONSTRAINT client_controls_pkey PRIMARY KEY (id);


--
-- Name: clients clients_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.clients
    ADD CONSTRAINT clients_pkey PRIMARY KEY (id);


--
-- Name: cost_logs cost_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cost_logs
    ADD CONSTRAINT cost_logs_pkey PRIMARY KEY (id);


--
-- Name: credentials credentials_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.credentials
    ADD CONSTRAINT credentials_pkey PRIMARY KEY (id);


--
-- Name: memories memories_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.memories
    ADD CONSTRAINT memories_pkey PRIMARY KEY (id);


--
-- Name: memory_injection_metrics memory_injection_metrics_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.memory_injection_metrics
    ADD CONSTRAINT memory_injection_metrics_pkey PRIMARY KEY (id);


--
-- Name: memory_settings memory_settings_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.memory_settings
    ADD CONSTRAINT memory_settings_pkey PRIMARY KEY (id);


--
-- Name: agent_benchmark_attempts pk_agent_benchmark_attempts; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_benchmark_attempts
    ADD CONSTRAINT pk_agent_benchmark_attempts PRIMARY KEY (id);


--
-- Name: agent_benchmark_experiments pk_agent_benchmark_experiments; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_benchmark_experiments
    ADD CONSTRAINT pk_agent_benchmark_experiments PRIMARY KEY (id);


--
-- Name: agent_benchmark_runs pk_agent_benchmark_runs; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_benchmark_runs
    ADD CONSTRAINT pk_agent_benchmark_runs PRIMARY KEY (id);


--
-- Name: agent_performance_logs pk_agent_performance_logs; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_performance_logs
    ADD CONSTRAINT pk_agent_performance_logs PRIMARY KEY (id);


--
-- Name: agent_prompts pk_agent_prompts; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_prompts
    ADD CONSTRAINT pk_agent_prompts PRIMARY KEY (id);


--
-- Name: agent_regression_clusters pk_agent_regression_clusters; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_regression_clusters
    ADD CONSTRAINT pk_agent_regression_clusters PRIMARY KEY (id);


--
-- Name: feedback_items pk_feedback_items; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.feedback_items
    ADD CONSTRAINT pk_feedback_items PRIMARY KEY (id);


--
-- Name: feedback_votes pk_feedback_votes; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.feedback_votes
    ADD CONSTRAINT pk_feedback_votes PRIMARY KEY (id);


--
-- Name: memory_revisions pk_memory_revisions; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.memory_revisions
    ADD CONSTRAINT pk_memory_revisions PRIMARY KEY (id);


--
-- Name: model_enrichments pk_model_enrichments; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.model_enrichments
    ADD CONSTRAINT pk_model_enrichments PRIMARY KEY (id);


--
-- Name: persona pk_persona; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.persona
    ADD CONSTRAINT pk_persona PRIMARY KEY (id);


--
-- Name: persona_scheduled_jobs pk_persona_scheduled_jobs; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.persona_scheduled_jobs
    ADD CONSTRAINT pk_persona_scheduled_jobs PRIMARY KEY (id);


--
-- Name: project_permissions pk_project_permissions; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.project_permissions
    ADD CONSTRAINT pk_project_permissions PRIMARY KEY (id);


--
-- Name: prompt_revisions pk_prompt_revisions; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.prompt_revisions
    ADD CONSTRAINT pk_prompt_revisions PRIMARY KEY (id);


--
-- Name: prompts pk_prompts; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.prompts
    ADD CONSTRAINT pk_prompts PRIMARY KEY (id);


--
-- Name: push_subscriptions pk_push_subscriptions; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.push_subscriptions
    ADD CONSTRAINT pk_push_subscriptions PRIMARY KEY (id);


--
-- Name: session_summary_segments pk_session_summary_segments; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.session_summary_segments
    ADD CONSTRAINT pk_session_summary_segments PRIMARY KEY (id);


--
-- Name: user_preferences pk_user_preferences; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_preferences
    ADD CONSTRAINT pk_user_preferences PRIMARY KEY (id);


--
-- Name: request_logs request_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.request_logs
    ADD CONSTRAINT request_logs_pkey PRIMARY KEY (id);


--
-- Name: session_events session_events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.session_events
    ADD CONSTRAINT session_events_pkey PRIMARY KEY (id);


--
-- Name: sessions sessions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sessions
    ADD CONSTRAINT sessions_pkey PRIMARY KEY (id);


--
-- Name: tier_change_log tier_change_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tier_change_log
    ADD CONSTRAINT tier_change_log_pkey PRIMARY KEY (id);


--
-- Name: truncation_events truncation_events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.truncation_events
    ADD CONSTRAINT truncation_events_pkey PRIMARY KEY (id);


--
-- Name: agent_prompts uq_agent_prompts_agent_id_prompt_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_prompts
    ADD CONSTRAINT uq_agent_prompts_agent_id_prompt_id UNIQUE (agent_id, prompt_id);


--
-- Name: agent_regression_clusters uq_agent_regression_clusters_agent_suite_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_regression_clusters
    ADD CONSTRAINT uq_agent_regression_clusters_agent_suite_key UNIQUE (agent_slug, suite_id, regression_key);


--
-- Name: feedback_votes uq_feedback_votes_item_session; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.feedback_votes
    ADD CONSTRAINT uq_feedback_votes_item_session UNIQUE (feedback_item_id, session_id);


--
-- Name: model_enrichments uq_model_enrichments_model_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.model_enrichments
    ADD CONSTRAINT uq_model_enrichments_model_id UNIQUE (model_id);


--
-- Name: project_permissions uq_project_permissions_project_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.project_permissions
    ADD CONSTRAINT uq_project_permissions_project_id UNIQUE (project_id);


--
-- Name: prompts uq_prompts_slug; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.prompts
    ADD CONSTRAINT uq_prompts_slug UNIQUE (slug);


--
-- Name: push_subscriptions uq_push_subscriptions_endpoint; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.push_subscriptions
    ADD CONSTRAINT uq_push_subscriptions_endpoint UNIQUE (endpoint);


--
-- Name: session_events uq_session_turn_sequence; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.session_events
    ADD CONSTRAINT uq_session_turn_sequence UNIQUE (session_id, turn, sequence);


--
-- Name: usage_stats usage_stats_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.usage_stats
    ADD CONSTRAINT usage_stats_pkey PRIMARY KEY (id);


--
-- Name: webhook_subscriptions webhook_subscriptions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.webhook_subscriptions
    ADD CONSTRAINT webhook_subscriptions_pkey PRIMARY KEY (id);


--
-- Name: idx_feedback_items_component; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_feedback_items_component ON public.feedback_items USING btree (component_id);


--
-- Name: idx_feedback_items_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_feedback_items_created ON public.feedback_items USING btree (created_at);


--
-- Name: idx_feedback_items_project; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_feedback_items_project ON public.feedback_items USING btree (project_id);


--
-- Name: idx_feedback_items_search; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_feedback_items_search ON public.feedback_items USING gin (search_vector);


--
-- Name: idx_feedback_items_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_feedback_items_status ON public.feedback_items USING btree (status);


--
-- Name: idx_feedback_items_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_feedback_items_type ON public.feedback_items USING btree (feedback_type);


--
-- Name: idx_feedback_items_votes; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_feedback_items_votes ON public.feedback_items USING btree (vote_count DESC);


--
-- Name: idx_feedback_votes_item; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_feedback_votes_item ON public.feedback_votes USING btree (feedback_item_id);


--
-- Name: idx_feedback_votes_session; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_feedback_votes_session ON public.feedback_votes USING btree (session_id);


--
-- Name: idx_memories_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_memories_created_at ON public.memories USING btree (created_at);


--
-- Name: idx_memories_embedding; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_memories_embedding ON public.memories USING hnsw (embedding public.vector_cosine_ops) WITH (m='16', ef_construction='64');


--
-- Name: idx_memories_group_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_memories_group_id ON public.memories USING btree (group_id) WHERE (group_id IS NOT NULL);


--
-- Name: idx_memories_metadata; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_memories_metadata ON public.memories USING gin (metadata);


--
-- Name: idx_memories_scope_tier; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_memories_scope_tier ON public.memories USING btree (scope, tier, status) WHERE ((status)::text = 'active'::text);


--
-- Name: idx_memories_type_scope; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_memories_type_scope ON public.memories USING btree (memory_type, scope) WHERE ((status)::text = 'active'::text);


--
-- Name: idx_segments_session_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_segments_session_created ON public.session_summary_segments USING btree (session_id, created_at);


--
-- Name: ix_agent_benchmark_attempts_agent_model_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_benchmark_attempts_agent_model_created ON public.agent_benchmark_attempts USING btree (agent_slug, model_id, created_at);


--
-- Name: ix_agent_benchmark_attempts_agent_slug; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_benchmark_attempts_agent_slug ON public.agent_benchmark_attempts USING btree (agent_slug);


--
-- Name: ix_agent_benchmark_attempts_case_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_benchmark_attempts_case_id ON public.agent_benchmark_attempts USING btree (case_id);


--
-- Name: ix_agent_benchmark_attempts_model_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_benchmark_attempts_model_id ON public.agent_benchmark_attempts USING btree (model_id);


--
-- Name: ix_agent_benchmark_attempts_run_case; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_benchmark_attempts_run_case ON public.agent_benchmark_attempts USING btree (benchmark_run_id, case_id);


--
-- Name: ix_agent_benchmark_experiments_agent_slug; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_benchmark_experiments_agent_slug ON public.agent_benchmark_experiments USING btree (agent_slug);


--
-- Name: ix_agent_benchmark_experiments_agent_suite_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_benchmark_experiments_agent_suite_created ON public.agent_benchmark_experiments USING btree (agent_slug, suite_id, created_at);


--
-- Name: ix_agent_benchmark_experiments_experiment_key; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_benchmark_experiments_experiment_key ON public.agent_benchmark_experiments USING btree (experiment_key);


--
-- Name: ix_agent_benchmark_experiments_project_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_benchmark_experiments_project_id ON public.agent_benchmark_experiments USING btree (project_id);


--
-- Name: ix_agent_benchmark_experiments_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_benchmark_experiments_status ON public.agent_benchmark_experiments USING btree (status);


--
-- Name: ix_agent_benchmark_experiments_suite_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_benchmark_experiments_suite_id ON public.agent_benchmark_experiments USING btree (suite_id);


--
-- Name: ix_agent_benchmark_runs_agent_slug; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_benchmark_runs_agent_slug ON public.agent_benchmark_runs USING btree (agent_slug);


--
-- Name: ix_agent_benchmark_runs_agent_suite_completed; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_benchmark_runs_agent_suite_completed ON public.agent_benchmark_runs USING btree (agent_slug, suite_id, completed_at);


--
-- Name: ix_agent_benchmark_runs_benchmark_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_benchmark_runs_benchmark_id ON public.agent_benchmark_runs USING btree (benchmark_id);


--
-- Name: ix_agent_benchmark_runs_experiment_cohort; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_benchmark_runs_experiment_cohort ON public.agent_benchmark_runs USING btree (experiment_cohort);


--
-- Name: ix_agent_benchmark_runs_experiment_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_benchmark_runs_experiment_id ON public.agent_benchmark_runs USING btree (experiment_id);


--
-- Name: ix_agent_benchmark_runs_project_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_benchmark_runs_project_id ON public.agent_benchmark_runs USING btree (project_id);


--
-- Name: ix_agent_benchmark_runs_run_kind; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_benchmark_runs_run_kind ON public.agent_benchmark_runs USING btree (run_kind);


--
-- Name: ix_agent_benchmark_runs_suite_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_benchmark_runs_suite_id ON public.agent_benchmark_runs USING btree (suite_id);


--
-- Name: ix_agent_perf_agent_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_perf_agent_created ON public.agent_performance_logs USING btree (agent_slug, created_at);


--
-- Name: ix_agent_perf_agent_model_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_perf_agent_model_type ON public.agent_performance_logs USING btree (agent_slug, model_id, task_type);


--
-- Name: ix_agent_perf_feedback_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_perf_feedback_type ON public.agent_performance_logs USING btree (feedback_type);


--
-- Name: ix_agent_perf_model_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_perf_model_created ON public.agent_performance_logs USING btree (model_id, created_at);


--
-- Name: ix_agent_prompts_agent_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_prompts_agent_id ON public.agent_prompts USING btree (agent_id);


--
-- Name: ix_agent_prompts_role; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_prompts_role ON public.agent_prompts USING btree (role);


--
-- Name: ix_agent_regression_clusters_agent_slug; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_regression_clusters_agent_slug ON public.agent_regression_clusters USING btree (agent_slug);


--
-- Name: ix_agent_regression_clusters_agent_suite_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_regression_clusters_agent_suite_status ON public.agent_regression_clusters USING btree (agent_slug, suite_id, status);


--
-- Name: ix_agent_regression_clusters_case_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_regression_clusters_case_id ON public.agent_regression_clusters USING btree (case_id);


--
-- Name: ix_agent_regression_clusters_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_regression_clusters_status ON public.agent_regression_clusters USING btree (status);


--
-- Name: ix_agent_regression_clusters_suite_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_regression_clusters_suite_id ON public.agent_regression_clusters USING btree (suite_id);


--
-- Name: ix_agent_versions_agent_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_versions_agent_id ON public.agent_versions USING btree (agent_id);


--
-- Name: ix_agent_versions_agent_version; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_versions_agent_version ON public.agent_versions USING btree (agent_id, version);


--
-- Name: ix_agents_active; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agents_active ON public.agents USING btree (is_active);


--
-- Name: ix_agents_slug; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_agents_slug ON public.agents USING btree (slug);


--
-- Name: ix_api_keys_key_hash; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_api_keys_key_hash ON public.api_keys USING btree (key_hash);


--
-- Name: ix_api_keys_project; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_api_keys_project ON public.api_keys USING btree (project_id);


--
-- Name: ix_api_keys_project_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_api_keys_project_id ON public.api_keys USING btree (project_id);


--
-- Name: ix_client_controls_client_name; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_client_controls_client_name ON public.client_controls USING btree (client_name);


--
-- Name: ix_clients_display_name; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_clients_display_name ON public.clients USING btree (display_name);


--
-- Name: ix_clients_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_clients_status ON public.clients USING btree (status);


--
-- Name: ix_cost_logs_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_cost_logs_created ON public.cost_logs USING btree (created_at);


--
-- Name: ix_cost_logs_session; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_cost_logs_session ON public.cost_logs USING btree (session_id);


--
-- Name: ix_credentials_provider; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_credentials_provider ON public.credentials USING btree (provider);


--
-- Name: ix_credentials_provider_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_credentials_provider_type ON public.credentials USING btree (provider, credential_type);


--
-- Name: ix_memories_lifecycle_score; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_memories_lifecycle_score ON public.memories USING btree (lifecycle_score) WHERE ((status)::text = 'active'::text);


--
-- Name: ix_memory_injection_metrics_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_memory_injection_metrics_created_at ON public.memory_injection_metrics USING btree (created_at);


--
-- Name: ix_memory_injection_metrics_external_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_memory_injection_metrics_external_id ON public.memory_injection_metrics USING btree (external_id);


--
-- Name: ix_memory_injection_metrics_project_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_memory_injection_metrics_project_id ON public.memory_injection_metrics USING btree (project_id);


--
-- Name: ix_memory_injection_metrics_variant; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_memory_injection_metrics_variant ON public.memory_injection_metrics USING btree (variant);


--
-- Name: ix_memory_revisions_action; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_memory_revisions_action ON public.memory_revisions USING btree (action);


--
-- Name: ix_memory_revisions_memory_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_memory_revisions_memory_id ON public.memory_revisions USING btree (memory_id);


--
-- Name: ix_memory_revisions_memory_uuid; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_memory_revisions_memory_uuid ON public.memory_revisions USING btree (memory_uuid);


--
-- Name: ix_memory_revisions_memory_uuid_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_memory_revisions_memory_uuid_created ON public.memory_revisions USING btree (memory_uuid, created_at);


--
-- Name: ix_model_enrichments_model_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_model_enrichments_model_id ON public.model_enrichments USING btree (model_id);


--
-- Name: ix_model_enrichments_synced_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_model_enrichments_synced_at ON public.model_enrichments USING btree (synced_at);


--
-- Name: ix_persona_agent_id; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_persona_agent_id ON public.persona USING btree (agent_id);


--
-- Name: ix_persona_scheduled_jobs_next_run; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_persona_scheduled_jobs_next_run ON public.persona_scheduled_jobs USING btree (enabled, next_run_at);


--
-- Name: ix_project_permissions_project_id; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_project_permissions_project_id ON public.project_permissions USING btree (project_id);


--
-- Name: ix_prompt_revisions_action; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_prompt_revisions_action ON public.prompt_revisions USING btree (action);


--
-- Name: ix_prompt_revisions_prompt_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_prompt_revisions_prompt_id ON public.prompt_revisions USING btree (prompt_id);


--
-- Name: ix_prompt_revisions_prompt_slug; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_prompt_revisions_prompt_slug ON public.prompt_revisions USING btree (prompt_slug);


--
-- Name: ix_prompt_revisions_prompt_slug_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_prompt_revisions_prompt_slug_created ON public.prompt_revisions USING btree (prompt_slug, created_at);


--
-- Name: ix_prompts_is_global; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_prompts_is_global ON public.prompts USING btree (is_global) WHERE (is_global = true);


--
-- Name: ix_prompts_owner_agent_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_prompts_owner_agent_id ON public.prompts USING btree (owner_agent_id);


--
-- Name: ix_prompts_prompt_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_prompts_prompt_type ON public.prompts USING btree (prompt_type);


--
-- Name: ix_prompts_slug; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_prompts_slug ON public.prompts USING btree (slug);


--
-- Name: ix_request_logs_agent_slug; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_request_logs_agent_slug ON public.request_logs USING btree (agent_slug);


--
-- Name: ix_request_logs_client_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_request_logs_client_created ON public.request_logs USING btree (client_id, created_at);


--
-- Name: ix_request_logs_client_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_request_logs_client_id ON public.request_logs USING btree (client_id);


--
-- Name: ix_request_logs_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_request_logs_created_at ON public.request_logs USING btree (created_at);


--
-- Name: ix_request_logs_status_code; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_request_logs_status_code ON public.request_logs USING btree (status_code);


--
-- Name: ix_request_logs_tool_name; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_request_logs_tool_name ON public.request_logs USING btree (tool_name);


--
-- Name: ix_session_events_session_turn; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_session_events_session_turn ON public.session_events USING btree (session_id, turn, sequence);


--
-- Name: ix_session_events_tool; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_session_events_tool ON public.session_events USING btree (tool_name);


--
-- Name: ix_session_events_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_session_events_type ON public.session_events USING btree (event_type);


--
-- Name: ix_sessions_agent_slug; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_sessions_agent_slug ON public.sessions USING btree (agent_slug);


--
-- Name: ix_sessions_external_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_sessions_external_id ON public.sessions USING btree (external_id);


--
-- Name: ix_sessions_parent; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_sessions_parent ON public.sessions USING btree (parent_session_id);


--
-- Name: ix_sessions_parent_session_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_sessions_parent_session_id ON public.sessions USING btree (parent_session_id);


--
-- Name: ix_sessions_project_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_sessions_project_created ON public.sessions USING btree (project_id, created_at);


--
-- Name: ix_sessions_project_heartbeat; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_sessions_project_heartbeat ON public.sessions USING btree (project_id, last_heartbeat_at);


--
-- Name: ix_sessions_project_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_sessions_project_id ON public.sessions USING btree (project_id);


--
-- Name: ix_sessions_status_last_activity; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_sessions_status_last_activity ON public.sessions USING btree (status, last_activity_at);


--
-- Name: ix_sessions_summary_lookup; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_sessions_summary_lookup ON public.sessions USING btree (project_id, summary_branch, summary_generated_at) WHERE (summary_oneliner IS NOT NULL);


--
-- Name: ix_tier_change_log_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_tier_change_log_created_at ON public.tier_change_log USING btree (created_at);


--
-- Name: ix_tier_change_log_episode_uuid; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_tier_change_log_episode_uuid ON public.tier_change_log USING btree (episode_uuid);


--
-- Name: ix_truncation_events_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_truncation_events_created ON public.truncation_events USING btree (created_at);


--
-- Name: ix_truncation_events_model; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_truncation_events_model ON public.truncation_events USING btree (model);


--
-- Name: ix_truncation_events_model_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_truncation_events_model_created ON public.truncation_events USING btree (model, created_at);


--
-- Name: ix_truncation_events_project_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_truncation_events_project_id ON public.truncation_events USING btree (project_id);


--
-- Name: ix_usage_stats_episode_metric; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_usage_stats_episode_metric ON public.usage_stats USING btree (episode_uuid, metric_type);


--
-- Name: ix_usage_stats_episode_uuid; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_usage_stats_episode_uuid ON public.usage_stats USING btree (episode_uuid);


--
-- Name: ix_usage_stats_timestamp; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_usage_stats_timestamp ON public.usage_stats USING btree ("timestamp");


--
-- Name: ix_user_preferences_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_user_preferences_key ON public.user_preferences USING btree (key);


--
-- Name: ix_webhook_subscriptions_project; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_webhook_subscriptions_project ON public.webhook_subscriptions USING btree (project_id);


--
-- Name: ix_webhook_subscriptions_project_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_webhook_subscriptions_project_id ON public.webhook_subscriptions USING btree (project_id);


--
-- Name: agent_versions agent_versions_agent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_versions
    ADD CONSTRAINT agent_versions_agent_id_fkey FOREIGN KEY (agent_id) REFERENCES public.agents(id) ON DELETE CASCADE;


--
-- Name: cost_logs cost_logs_session_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cost_logs
    ADD CONSTRAINT cost_logs_session_id_fkey FOREIGN KEY (session_id) REFERENCES public.sessions(id) ON DELETE CASCADE;


--
-- Name: agent_benchmark_attempts fk_agent_benchmark_attempts_agent_benchmark_runs_benchm_6ecd; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_benchmark_attempts
    ADD CONSTRAINT fk_agent_benchmark_attempts_agent_benchmark_runs_benchm_6ecd FOREIGN KEY (benchmark_run_id) REFERENCES public.agent_benchmark_runs(id) ON DELETE CASCADE;


--
-- Name: agent_benchmark_runs fk_agent_benchmark_runs_agent_benchmark_experiments_exp_af13; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_benchmark_runs
    ADD CONSTRAINT fk_agent_benchmark_runs_agent_benchmark_experiments_exp_af13 FOREIGN KEY (experiment_id) REFERENCES public.agent_benchmark_experiments(id) ON DELETE SET NULL;


--
-- Name: agent_prompts fk_agent_prompts_agents_agent_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_prompts
    ADD CONSTRAINT fk_agent_prompts_agents_agent_id FOREIGN KEY (agent_id) REFERENCES public.agents(id) ON DELETE CASCADE;


--
-- Name: agent_prompts fk_agent_prompts_prompts_prompt_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_prompts
    ADD CONSTRAINT fk_agent_prompts_prompts_prompt_id FOREIGN KEY (prompt_id) REFERENCES public.prompts(id) ON DELETE CASCADE;


--
-- Name: agent_regression_clusters fk_agent_regression_clusters_agent_benchmark_runs_first_720e; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_regression_clusters
    ADD CONSTRAINT fk_agent_regression_clusters_agent_benchmark_runs_first_720e FOREIGN KEY (first_seen_run_id) REFERENCES public.agent_benchmark_runs(id) ON DELETE SET NULL;


--
-- Name: agent_regression_clusters fk_agent_regression_clusters_agent_benchmark_runs_last__0e44; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_regression_clusters
    ADD CONSTRAINT fk_agent_regression_clusters_agent_benchmark_runs_last__0e44 FOREIGN KEY (last_seen_run_id) REFERENCES public.agent_benchmark_runs(id) ON DELETE SET NULL;


--
-- Name: feedback_items fk_feedback_items_sessions_created_by_session_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.feedback_items
    ADD CONSTRAINT fk_feedback_items_sessions_created_by_session_id FOREIGN KEY (created_by_session_id) REFERENCES public.sessions(id) ON DELETE SET NULL;


--
-- Name: feedback_votes fk_feedback_votes_feedback_items_feedback_item_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.feedback_votes
    ADD CONSTRAINT fk_feedback_votes_feedback_items_feedback_item_id FOREIGN KEY (feedback_item_id) REFERENCES public.feedback_items(id) ON DELETE CASCADE;


--
-- Name: feedback_votes fk_feedback_votes_sessions_session_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.feedback_votes
    ADD CONSTRAINT fk_feedback_votes_sessions_session_id FOREIGN KEY (session_id) REFERENCES public.sessions(id) ON DELETE CASCADE;


--
-- Name: memories fk_memories_superseded_by; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.memories
    ADD CONSTRAINT fk_memories_superseded_by FOREIGN KEY (superseded_by) REFERENCES public.memories(id) ON DELETE SET NULL;


--
-- Name: memory_revisions fk_memory_revisions_memories_memory_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.memory_revisions
    ADD CONSTRAINT fk_memory_revisions_memories_memory_id FOREIGN KEY (memory_id) REFERENCES public.memories(id) ON DELETE SET NULL;


--
-- Name: persona fk_persona_agents_agent_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.persona
    ADD CONSTRAINT fk_persona_agents_agent_id FOREIGN KEY (agent_id) REFERENCES public.agents(id) ON DELETE CASCADE;


--
-- Name: persona_scheduled_jobs fk_persona_scheduled_jobs_persona_persona_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.persona_scheduled_jobs
    ADD CONSTRAINT fk_persona_scheduled_jobs_persona_persona_id FOREIGN KEY (persona_id) REFERENCES public.persona(id) ON DELETE CASCADE;


--
-- Name: prompt_revisions fk_prompt_revisions_prompts_prompt_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.prompt_revisions
    ADD CONSTRAINT fk_prompt_revisions_prompts_prompt_id FOREIGN KEY (prompt_id) REFERENCES public.prompts(id) ON DELETE SET NULL;


--
-- Name: prompts fk_prompts_owner_agent_id_agents; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.prompts
    ADD CONSTRAINT fk_prompts_owner_agent_id_agents FOREIGN KEY (owner_agent_id) REFERENCES public.agents(id) ON DELETE CASCADE;


--
-- Name: session_events fk_session_events_session_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.session_events
    ADD CONSTRAINT fk_session_events_session_id FOREIGN KEY (session_id) REFERENCES public.sessions(id) ON DELETE CASCADE;


--
-- Name: session_summary_segments fk_session_summary_segments_sessions_session_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.session_summary_segments
    ADD CONSTRAINT fk_session_summary_segments_sessions_session_id FOREIGN KEY (session_id) REFERENCES public.sessions(id) ON DELETE CASCADE;


--
-- Name: sessions fk_sessions_parent_session; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sessions
    ADD CONSTRAINT fk_sessions_parent_session FOREIGN KEY (parent_session_id) REFERENCES public.sessions(id) ON DELETE SET NULL;


--
-- Name: memory_injection_metrics memory_injection_metrics_session_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.memory_injection_metrics
    ADD CONSTRAINT memory_injection_metrics_session_id_fkey FOREIGN KEY (session_id) REFERENCES public.sessions(id) ON DELETE SET NULL;


--
-- Name: request_logs request_logs_client_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.request_logs
    ADD CONSTRAINT request_logs_client_id_fkey FOREIGN KEY (client_id) REFERENCES public.clients(id) ON DELETE SET NULL;


--
-- Name: sessions sessions_client_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sessions
    ADD CONSTRAINT sessions_client_id_fkey FOREIGN KEY (client_id) REFERENCES public.clients(id) ON DELETE SET NULL;


--
-- Name: truncation_events truncation_events_session_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.truncation_events
    ADD CONSTRAINT truncation_events_session_id_fkey FOREIGN KEY (session_id) REFERENCES public.sessions(id) ON DELETE SET NULL;


--
-- PostgreSQL database dump complete
--

\unrestrict vDbgLE1H1T4i660of1VpcSbuVAkJkW7cRGzQVdX4HhHLY5iSjmOqh1kk60UnTkS
