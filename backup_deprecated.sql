--
-- PostgreSQL database dump
--

\restrict 2t370lPfNe6fkMhW6MT53l8ktaDyeBOsV1zaY0KBIUg3RoTLcRhqrk3LuHW3HRf

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

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: artifacts; Type: TABLE; Schema: public; Owner: summitflow_app
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


ALTER TABLE public.artifacts OWNER TO summitflow_app;

--
-- Name: artifacts_id_seq; Type: SEQUENCE; Schema: public; Owner: summitflow_app
--

CREATE SEQUENCE public.artifacts_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.artifacts_id_seq OWNER TO summitflow_app;

--
-- Name: artifacts_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: summitflow_app
--

ALTER SEQUENCE public.artifacts_id_seq OWNED BY public.artifacts.id;


--
-- Name: feature_capabilities; Type: TABLE; Schema: public; Owner: summitflow_app
--

CREATE TABLE public.feature_capabilities (
    id integer NOT NULL,
    project_id text NOT NULL,
    feature_id character varying(20) NOT NULL,
    name character varying(255) NOT NULL,
    category character varying(100),
    description text,
    passes boolean,
    task_file character varying(255),
    task_section character varying(20),
    health_status character varying(20) DEFAULT 'active'::character varying,
    status character varying(20) DEFAULT 'planned'::character varying,
    effort character varying(10),
    priority integer DEFAULT 2,
    verification_layers jsonb DEFAULT '[]'::jsonb,
    implementation_notes text,
    acceptance_criteria jsonb DEFAULT '[]'::jsonb,
    last_verified_at timestamp with time zone,
    verified_by character varying(50),
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    layer_results jsonb DEFAULT '{}'::jsonb,
    vision_goals text[] DEFAULT '{}'::text[]
);


ALTER TABLE public.feature_capabilities OWNER TO summitflow_app;

--
-- Name: feature_capabilities_id_seq; Type: SEQUENCE; Schema: public; Owner: summitflow_app
--

CREATE SEQUENCE public.feature_capabilities_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.feature_capabilities_id_seq OWNER TO summitflow_app;

--
-- Name: feature_capabilities_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: summitflow_app
--

ALTER SEQUENCE public.feature_capabilities_id_seq OWNED BY public.feature_capabilities.id;


--
-- Name: feature_dependencies; Type: TABLE; Schema: public; Owner: summitflow_app
--

CREATE TABLE public.feature_dependencies (
    id integer NOT NULL,
    feature_id integer NOT NULL,
    depends_on_id integer NOT NULL,
    dependency_type text DEFAULT 'blocks'::text NOT NULL,
    notes text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT feature_dependencies_check CHECK ((feature_id <> depends_on_id))
);


ALTER TABLE public.feature_dependencies OWNER TO summitflow_app;

--
-- Name: feature_dependencies_id_seq; Type: SEQUENCE; Schema: public; Owner: summitflow_app
--

CREATE SEQUENCE public.feature_dependencies_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.feature_dependencies_id_seq OWNER TO summitflow_app;

--
-- Name: feature_dependencies_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: summitflow_app
--

ALTER SEQUENCE public.feature_dependencies_id_seq OWNED BY public.feature_dependencies.id;


--
-- Name: feature_tasks; Type: TABLE; Schema: public; Owner: summitflow_app
--

CREATE TABLE public.feature_tasks (
    id integer NOT NULL,
    feature_id integer NOT NULL,
    task_id character varying(20) NOT NULL,
    description text NOT NULL,
    completed boolean DEFAULT false NOT NULL,
    order_num integer DEFAULT 0 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    completed_at timestamp with time zone,
    completed_by character varying(50)
);


ALTER TABLE public.feature_tasks OWNER TO summitflow_app;

--
-- Name: feature_tasks_id_seq; Type: SEQUENCE; Schema: public; Owner: summitflow_app
--

CREATE SEQUENCE public.feature_tasks_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.feature_tasks_id_seq OWNER TO summitflow_app;

--
-- Name: feature_tasks_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: summitflow_app
--

ALTER SEQUENCE public.feature_tasks_id_seq OWNED BY public.feature_tasks.id;


--
-- Name: feature_vision_goal_mappings; Type: TABLE; Schema: public; Owner: summitflow_app
--

CREATE TABLE public.feature_vision_goal_mappings (
    id integer NOT NULL,
    feature_id integer NOT NULL,
    vision_code text NOT NULL,
    linked_at timestamp with time zone DEFAULT now(),
    linked_by character varying(50)
);


ALTER TABLE public.feature_vision_goal_mappings OWNER TO summitflow_app;

--
-- Name: feature_vision_goal_mappings_id_seq; Type: SEQUENCE; Schema: public; Owner: summitflow_app
--

CREATE SEQUENCE public.feature_vision_goal_mappings_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.feature_vision_goal_mappings_id_seq OWNER TO summitflow_app;

--
-- Name: feature_vision_goal_mappings_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: summitflow_app
--

ALTER SEQUENCE public.feature_vision_goal_mappings_id_seq OWNED BY public.feature_vision_goal_mappings.id;


--
-- Name: vision_content; Type: TABLE; Schema: public; Owner: summitflow_app
--

CREATE TABLE public.vision_content (
    id integer NOT NULL,
    project_id text NOT NULL,
    content_type text NOT NULL,
    content_key text NOT NULL,
    title text,
    content text NOT NULL,
    order_num integer DEFAULT 0,
    metadata jsonb,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


ALTER TABLE public.vision_content OWNER TO summitflow_app;

--
-- Name: vision_content_id_seq; Type: SEQUENCE; Schema: public; Owner: summitflow_app
--

CREATE SEQUENCE public.vision_content_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.vision_content_id_seq OWNER TO summitflow_app;

--
-- Name: vision_content_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: summitflow_app
--

ALTER SEQUENCE public.vision_content_id_seq OWNED BY public.vision_content.id;


--
-- Name: vision_goal_details; Type: TABLE; Schema: public; Owner: summitflow_app
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


ALTER TABLE public.vision_goal_details OWNER TO summitflow_app;

--
-- Name: vision_goal_details_id_seq; Type: SEQUENCE; Schema: public; Owner: summitflow_app
--

CREATE SEQUENCE public.vision_goal_details_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.vision_goal_details_id_seq OWNER TO summitflow_app;

--
-- Name: vision_goal_details_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: summitflow_app
--

ALTER SEQUENCE public.vision_goal_details_id_seq OWNED BY public.vision_goal_details.id;


--
-- Name: vision_goals; Type: TABLE; Schema: public; Owner: summitflow_app
--

CREATE TABLE public.vision_goals (
    code text NOT NULL,
    name text NOT NULL,
    description text,
    category text,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    project_id text
);


ALTER TABLE public.vision_goals OWNER TO summitflow_app;

--
-- Name: COLUMN vision_goals.project_id; Type: COMMENT; Schema: public; Owner: summitflow_app
--

COMMENT ON COLUMN public.vision_goals.project_id IS 'Project scope - each goal belongs to one project';


--
-- Name: artifacts id; Type: DEFAULT; Schema: public; Owner: summitflow_app
--

ALTER TABLE ONLY public.artifacts ALTER COLUMN id SET DEFAULT nextval('public.artifacts_id_seq'::regclass);


--
-- Name: feature_capabilities id; Type: DEFAULT; Schema: public; Owner: summitflow_app
--

ALTER TABLE ONLY public.feature_capabilities ALTER COLUMN id SET DEFAULT nextval('public.feature_capabilities_id_seq'::regclass);


--
-- Name: feature_dependencies id; Type: DEFAULT; Schema: public; Owner: summitflow_app
--

ALTER TABLE ONLY public.feature_dependencies ALTER COLUMN id SET DEFAULT nextval('public.feature_dependencies_id_seq'::regclass);


--
-- Name: feature_tasks id; Type: DEFAULT; Schema: public; Owner: summitflow_app
--

ALTER TABLE ONLY public.feature_tasks ALTER COLUMN id SET DEFAULT nextval('public.feature_tasks_id_seq'::regclass);


--
-- Name: feature_vision_goal_mappings id; Type: DEFAULT; Schema: public; Owner: summitflow_app
--

ALTER TABLE ONLY public.feature_vision_goal_mappings ALTER COLUMN id SET DEFAULT nextval('public.feature_vision_goal_mappings_id_seq'::regclass);


--
-- Name: vision_content id; Type: DEFAULT; Schema: public; Owner: summitflow_app
--

ALTER TABLE ONLY public.vision_content ALTER COLUMN id SET DEFAULT nextval('public.vision_content_id_seq'::regclass);


--
-- Name: vision_goal_details id; Type: DEFAULT; Schema: public; Owner: summitflow_app
--

ALTER TABLE ONLY public.vision_goal_details ALTER COLUMN id SET DEFAULT nextval('public.vision_goal_details_id_seq'::regclass);


--
-- Data for Name: artifacts; Type: TABLE DATA; Schema: public; Owner: summitflow_app
--

COPY public.artifacts (id, project_id, artifact_id, feature_id, criterion_id, artifact_type, file_path, file_size_bytes, version, is_current, captured_at, expires_at, quality_status, quality_issues, confidence, ai_reviewed_at, ai_reviewed_by, ai_evidence, user_reviewed_at, user_approved, user_notes, created_at, updated_at) FROM stdin;
\.


--
-- Data for Name: feature_capabilities; Type: TABLE DATA; Schema: public; Owner: summitflow_app
--

COPY public.feature_capabilities (id, project_id, feature_id, name, category, description, passes, task_file, task_section, health_status, status, effort, priority, verification_layers, implementation_notes, acceptance_criteria, last_verified_at, verified_by, created_at, updated_at, layer_results, vision_goals) FROM stdin;
314	summitflow	FEAT-001	Test Kanban Feature	feature	Testing Kanban	\N	\N	\N	active	planned	\N	2	[]	\N	[{"id": "ac-1", "passes": false, "description": "Test criterion 1"}, {"id": "ac-2", "passes": false, "description": "Test criterion 2"}]	\N	\N	2025-12-20 15:22:37.287705-05	2025-12-20 16:59:19.759964-05	{}	{}
\.


--
-- Data for Name: feature_dependencies; Type: TABLE DATA; Schema: public; Owner: summitflow_app
--

COPY public.feature_dependencies (id, feature_id, depends_on_id, dependency_type, notes, created_at) FROM stdin;
\.


--
-- Data for Name: feature_tasks; Type: TABLE DATA; Schema: public; Owner: summitflow_app
--

COPY public.feature_tasks (id, feature_id, task_id, description, completed, order_num, created_at, updated_at, completed_at, completed_by) FROM stdin;
\.


--
-- Data for Name: feature_vision_goal_mappings; Type: TABLE DATA; Schema: public; Owner: summitflow_app
--

COPY public.feature_vision_goal_mappings (id, feature_id, vision_code, linked_at, linked_by) FROM stdin;
\.


--
-- Data for Name: vision_content; Type: TABLE DATA; Schema: public; Owner: summitflow_app
--

COPY public.vision_content (id, project_id, content_type, content_key, title, content, order_num, metadata, created_at, updated_at) FROM stdin;
1	portfolio-ai	mission	core	Mission Statement	Build a self-operating investment intelligence system that autonomously monitors markets, generates trade ideas, validates strategies through backtesting and paper trading, and presents plain-language insights—while keeping humans in the loop for final decisions.	0	\N	2025-12-08 16:35:22.065477-05	2025-12-08 16:35:22.065477-05
2	portfolio-ai	vision	what	What We're Building	Portfolio AI is an AI-led investment intelligence platform that democratizes sophisticated market analysis by transforming complex financial data into clear, actionable insights accessible to all investors—regardless of technical expertise.\n\nWe combine the analytical power of AI agents (Claude/Gemini) with deterministic trading strategies, multi-source data redundancy, and rigorous backtesting to create a system that:\n\n1. Thinks autonomously - Continuously monitors markets, evaluates opportunities, and generates ideas without manual intervention\n2. Speaks plainly - Eliminates financial jargon and presents insights in clear, everyday language\n3. Validates rigorously - Tests every strategy against historical data and tracks paper trading performance before risking real capital\n4. Operates reliably - Uses multiple data sources, automated monitoring, and production-grade infrastructure to ensure 24/7 availability	1	{"key_points": ["Thinks autonomously", "Speaks plainly", "Validates rigorously", "Operates reliably"]}	2025-12-08 16:35:22.065477-05	2025-12-08 16:35:22.065477-05
3	portfolio-ai	vision	why	Why It Matters	Traditional Problem:\n• Expensive - Professional analysts cost thousands per year\n• Complex - Financial jargon creates barriers for non-experts\n• Time-consuming - Manual research takes hours daily\n• Risky - Acting on untested ideas can lead to losses\n\nOur Solution:\n• Autonomous - AI agents work 24/7, no human intervention needed\n• Accessible - Zero jargon, plain-language explanations anyone can understand\n• Validated - Every strategy backtested and paper-traded before recommendation\n• Transparent - Full visibility into AI reasoning, data sources, and performance metrics	2	{"problems": ["Expensive", "Complex", "Time-consuming", "Risky"], "solutions": ["Autonomous", "Accessible", "Validated", "Transparent"]}	2025-12-08 16:35:22.065477-05	2025-12-08 16:35:22.065477-05
4	portfolio-ai	principle	principle-2	Transparency Over Black Boxes	Every recommendation includes full rationale and supporting data. Data sources are tracked and displayed (YFinance, Polygon, etc.). AI reasoning is logged and reviewable. Performance metrics are tracked and visible.	2	{"icon": "eye", "key_points": ["Full rationale included", "Data sources tracked", "AI reasoning logged", "Performance metrics visible"]}	2025-12-08 16:35:22.065477-05	2025-12-08 16:35:22.065477-05
5	portfolio-ai	principle	principle-3	Validate Before Execute	All strategies must pass backtesting before paper trading. Paper trades must show positive results before recommendation. LLM reviewers (Claude/Gemini) provide independent analysis. Disagreements between reviewers are flagged and logged.	3	{"icon": "check-circle", "key_points": ["Backtesting required", "Paper trades first", "Independent LLM review", "Disagreements flagged"]}	2025-12-08 16:35:22.065477-05	2025-12-08 16:35:22.065477-05
6	portfolio-ai	principle	principle-4	Accessibility Without Compromise	Plain-language narratives with zero financial jargon. Complex analytics presented visually (charts, gauges, sparklines). Mobile-responsive design for on-the-go access. Dark/light themes and accessibility support (ARIA labels, keyboard navigation).	4	{"icon": "accessibility", "key_points": ["Zero jargon", "Visual analytics", "Mobile responsive", "Accessibility support"]}	2025-12-08 16:35:22.065477-05	2025-12-08 16:35:22.065477-05
7	portfolio-ai	principle	principle-5	Reliability Through Redundancy	Multi-source data failover (6 operational sources). Automated freshness monitoring with scheduled data refreshes. PostgreSQL with connection pooling for production-grade performance. Comprehensive error handling and graceful degradation.	5	{"icon": "shield", "key_points": ["Multi-source failover", "Automated freshness monitoring", "PostgreSQL with pooling", "Graceful degradation"]}	2025-12-08 16:35:22.065477-05	2025-12-08 16:35:22.065477-05
8	portfolio-ai	principle	principle-6	Developer Velocity & Code Quality	Comprehensive test coverage (85%+ target). Mypy --strict type safety compliance. Modular architecture (<500 lines per file). Automated maintenance and scheduled cleanup.	6	{"icon": "code", "key_points": ["85%+ test coverage", "Mypy --strict", "Modular architecture", "Automated maintenance"]}	2025-12-08 16:35:22.065477-05	2025-12-08 16:35:22.065477-05
9	portfolio-ai	success_metric	system	System Performance	Core system reliability and performance targets.	1	{"metrics": [{"name": "Uptime", "target": "99.9%", "description": "System availability"}, {"name": "Data Freshness", "target": "<24 hours", "description": "All monitored tables"}, {"name": "API Response Time", "target": "<500ms", "description": "Portfolio endpoints"}, {"name": "Test Pass Rate", "target": "100%", "description": "All 508+ tests passing"}]}	2025-12-08 16:35:22.065477-05	2025-12-08 16:35:22.065477-05
10	portfolio-ai	success_metric	ai_agent	AI Agent Performance	Autonomous operation and trading performance targets.	2	{"metrics": [{"name": "Idea Generation", "target": "Daily at 03:30 UTC", "description": "Autonomous runs"}, {"name": "Backtest Success", "target": "80%+", "description": "Strategies show positive returns"}, {"name": "Paper Trade Win Rate", "target": "60%+", "description": "Simulated trades profitable"}, {"name": "LLM Agreement", "target": "<20%", "description": "Disagreement rate between reviewers"}]}	2025-12-08 16:35:22.065477-05	2025-12-08 16:35:22.065477-05
11	portfolio-ai	success_metric	ux	User Experience	Interface performance and accessibility targets.	3	{"metrics": [{"name": "Page Load", "target": "<2 seconds", "description": "All pages"}, {"name": "Mobile Responsive", "target": "100%", "description": "Functionality on phones/tablets"}, {"name": "Accessibility", "target": "WCAG AA", "description": "Compliance level"}, {"name": "Error Rate", "target": "<1%", "description": "API failures"}]}	2025-12-08 16:35:22.065477-05	2025-12-08 16:35:22.065477-05
12	portfolio-ai	success_metric	quality	Code Quality	Development standards and code health targets.	4	{"metrics": [{"name": "Test Coverage", "target": "85%+", "description": "Code coverage"}, {"name": "Type Safety", "target": "100%", "description": "Mypy --strict compliance"}, {"name": "File Size", "target": "0 files >800 lines", "description": "Hard limit"}, {"name": "Complexity", "target": "0 functions >100 lines", "description": "Critical threshold"}]}	2025-12-08 16:35:22.065477-05	2025-12-08 16:35:22.065477-05
13	portfolio-ai	roadmap_phase	phase-1	Phase 1: Foundation & Core Trading	MVP features including portfolio, watchlist, agents, PostgreSQL, and multi-source data infrastructure.	1	{"icon": "check-circle", "status": "complete", "features": ["Portfolio tracking", "Watchlist management", "Trading agents", "PostgreSQL database", "Multi-source data"]}	2025-12-08 16:35:22.065477-05	2025-12-08 16:35:22.065477-05
14	portfolio-ai	roadmap_phase	phase-2	Phase 2: Narrative Intelligence	Signal classification, trading styles, and plain-language insights for all positions.	2	{"icon": "check-circle", "status": "complete", "features": ["Signal classification", "Trading style detection", "Plain-language insights", "Confidence scoring"]}	2025-12-08 16:35:22.065477-05	2025-12-08 16:35:22.065477-05
15	portfolio-ai	roadmap_phase	phase-3	Phase 3: Autonomous Trading MVP	Backtesting, paper trading, and multi-agent collaboration for strategy validation.	3	{"icon": "check-circle", "status": "complete", "features": ["Backtesting engine", "Paper trading", "Multi-agent collaboration", "Strategy validation"]}	2025-12-08 16:35:22.065477-05	2025-12-08 16:35:22.065477-05
16	portfolio-ai	roadmap_phase	phase-4	Phase 4: Production Readiness	Validation systems, deployment automation, and git workflow integration.	4	{"icon": "loader", "status": "in_progress", "features": ["Feature validation", "Deployment automation", "Git automation", "Production monitoring"]}	2025-12-08 16:35:22.065477-05	2025-12-08 16:35:22.065477-05
17	portfolio-ai	roadmap_phase	phase-5	Phase 5: Intelligence Layer Phase 2	Sentiment scoring, fundamental data integration, and advanced AI summaries.	5	{"icon": "calendar", "status": "planned", "features": ["Sentiment scoring", "Fundamental data", "AI summaries", "Advanced analytics"]}	2025-12-08 16:35:22.065477-05	2025-12-08 16:35:22.065477-05
18	portfolio-ai	example	news-sentiment	Example: News Sentiment Analysis	How we transform raw news into actionable intelligence.\n\n❌ Old Approach: Display raw news headlines, expect users to interpret sentiment themselves\n\n✅ Our Approach:\n1. Fetch news from multiple sources (Google News RSS)\n2. Run VADER sentiment analysis (-1.0 to +1.0)\n3. Classify as Positive/Neutral/Negative with plain-language labels\n4. Generate AI insight: "Recent positive earnings beat drove 8% gain - watch for pullback"\n5. Show data source and timestamp for transparency\n6. Update automatically on schedule (6-hour cache TTL)	1	{"principles_applied": ["Transparency Over Black Boxes", "Accessibility Without Compromise", "Reliability Through Redundancy"]}	2025-12-08 16:35:22.065477-05	2025-12-08 16:35:22.065477-05
19	portfolio-ai	example	backtesting	Example: Backtesting a Strategy	How we validate strategies before recommending them.\n\n❌ Old Approach: Implement strategy in production, learn from losses\n\n✅ Our Approach:\n1. Define deterministic strategy (BUY signal: price > EMA-20, RSI 30-70, MACD > 0)\n2. Backtest against 252 days of historical data\n3. Calculate performance: Sharpe ratio, max drawdown, win rate, total return\n4. Generate equity curve visualization\n5. Only proceed to paper trading if backtest shows positive results\n6. Track paper trade performance before any recommendation	2	{"principles_applied": ["Validate Before Execute", "Humans Decide, AI Advises", "Transparency Over Black Boxes"]}	2025-12-08 16:35:22.065477-05	2025-12-08 16:35:22.065477-05
20	portfolio-ai	closing	north-star	Our North Star	Portfolio AI represents a fundamental shift in how individual investors approach markets: from manual research and guesswork to automated intelligence and validated strategies. By combining the analytical power of AI with rigorous backtesting, transparent reasoning, and plain-language communication, we aim to level the playing field between retail investors and professionals.\n\nEvery investor deserves sophisticated analysis, delivered clearly, validated rigorously, and available 24/7.	0	\N	2025-12-08 16:35:22.065477-05	2025-12-08 16:35:22.065477-05
21	portfolio-ai	principle	principle-1	Autonomous Agents, Human Oversight	AI agents autonomously research, analyze, backtest, and execute paper trades. Humans provide strategic guidance and can intervene when needed, but do not approve every action. The only hard boundary: no connection to real money or live trading environments.	1	{"icon": "bot", "key_points": ["Agents research and analyze autonomously", "Agents execute paper trades independently", "Humans guide and nudge, not approve every action", "Hard boundary: no real money trading"]}	2025-12-08 16:35:22.065477-05	2025-12-08 18:47:11.246191-05
23	summitflow	vision	what-we-build	What We Build	SummitFlow is the control center for AI-powered development. It tracks what needs to be done (tasks), understands the codebase (Explorer), orchestrates multiple AI agents working together (Roundtable), and manages automated workflows.	1	\N	2025-12-20 10:38:04.391169-05	2025-12-20 10:38:04.391169-05
24	summitflow	vision	why-we-build	Why We Build	The goal is to make developers 10x more productive by handling the cognitive overhead of complex projects. AI agents should work for you, not create more work.	2	\N	2025-12-20 10:38:04.391169-05	2025-12-20 10:38:04.391169-05
25	context-hub	mission	mission-statement	Mission	Unified memory service that captures, learns from, and provides context for every AI agent action across all systems.	1	\N	2025-12-20 10:40:06.212256-05	2025-12-20 10:40:06.212256-05
26	context-hub	vision	what-we-build	What We Build	Context Hub is the memory layer for our entire AI ecosystem. Every tool call from Claude Code, every Roundtable discussion, every Portfolio-AI automation contributes to a shared knowledge base.	1	\N	2025-12-20 10:40:06.232247-05	2025-12-20 10:40:06.232247-05
27	context-hub	vision	why-we-build	Why We Build	The system learns patterns, remembers decisions, and provides relevant context to future agent sessions - making every AI interaction smarter than the last.	2	\N	2025-12-20 10:40:06.252273-05	2025-12-20 10:40:06.252273-05
22	summitflow	mission	mission-statement	Mission	Test mission	1	{"values": ["test"]}	2025-12-20 10:38:04.391169-05	2025-12-20 16:41:46.250027-05
\.


--
-- Data for Name: vision_goal_details; Type: TABLE DATA; Schema: public; Owner: summitflow_app
--

COPY public.vision_goal_details (id, goal_code, detail_type, content, order_num, metadata, created_at) FROM stdin;
2	VG-INTEL	objective	Transform raw market data into actionable insights	0	\N	2025-12-08 16:35:22.088437-05
3	VG-INTEL	feature	Signal Fusion: Combine news sentiment, fundamentals, and technical indicators into unified BUY/HOLD/AVOID recommendations	1	{"highlight": "Signal Fusion"}	2025-12-08 16:35:22.088437-05
4	VG-INTEL	feature	Confidence Scoring: Provide 0-10 strength scores with supporting evidence	2	{"highlight": "Confidence Scoring"}	2025-12-08 16:35:22.088437-05
5	VG-INTEL	feature	Style Classification: Recommend optimal trading approach (Index/Trend/Value/Swing/Event) with holding periods	3	{"highlight": "Style Classification"}	2025-12-08 16:35:22.088437-05
6	VG-INTEL	feature	Position Sizing: Calculate entry/stop/target prices with risk-adjusted position sizes	4	{"highlight": "Position Sizing"}	2025-12-08 16:35:22.088437-05
7	VG-INTEL	feature	Plain Language: Generate narratives that explain "why" in everyday terms (no jargon)	5	{"highlight": "Plain Language"}	2025-12-08 16:35:22.088437-05
8	VG-INTEL	success_criterion	All recommendations include confidence score, rationale, and supporting data	1	\N	2025-12-08 16:35:22.088437-05
9	VG-INTEL	success_criterion	Users understand insights without needing financial expertise	2	\N	2025-12-08 16:35:22.088437-05
10	VG-INTEL	success_criterion	AI explanations pass plain-language readability tests	3	\N	2025-12-08 16:35:22.088437-05
11	VG-AUTO	objective	Use AI agents as analysts, not execution authorities	0	\N	2025-12-08 16:35:22.088437-05
12	VG-AUTO	feature	Market Discovery: Discovery Agent scans news/economic data for broad opportunities	1	{"highlight": "Market Discovery"}	2025-12-08 16:35:22.088437-05
13	VG-AUTO	feature	Portfolio Analysis: Portfolio Analyzer generates personalized ideas based on holdings	2	{"highlight": "Portfolio Analysis"}	2025-12-08 16:35:22.088437-05
14	VG-AUTO	feature	Strategy Review: LLM reviewers (Claude/Gemini) independently analyze proposed strategies	3	{"highlight": "Strategy Review"}	2025-12-08 16:35:22.088437-05
15	VG-AUTO	feature	Disagreement Detection: Flag when multiple LLMs disagree on recommendations	4	{"highlight": "Disagreement Detection"}	2025-12-08 16:35:22.088437-05
16	VG-AUTO	feature	Autonomous Execution: Paper trades execute automatically based on validated strategies	5	{"highlight": "Autonomous Execution"}	2025-12-08 16:35:22.088437-05
17	VG-AUTO	success_criterion	Agents generate ideas autonomously on schedule (daily at 03:30 UTC)	1	\N	2025-12-08 16:35:22.088437-05
18	VG-AUTO	success_criterion	LLM reviewers provide independent analysis with reasoning	2	\N	2025-12-08 16:35:22.088437-05
19	VG-AUTO	success_criterion	Disagreements are logged and surfaced to users	3	\N	2025-12-08 16:35:22.088437-05
20	VG-AUTO	success_criterion	Zero manual intervention required for routine operations	4	\N	2025-12-08 16:35:22.088437-05
21	VG-PORT	objective	Unified monitoring of owned and watched positions	0	\N	2025-12-08 16:35:22.088437-05
22	VG-PORT	feature	Real-Time Analytics: Beta, volatility, concentration, sector exposure, Sharpe ratio, diversification	1	{"highlight": "Real-Time Analytics"}	2025-12-08 16:35:22.088437-05
23	VG-PORT	feature	Watchlist Scoring: Real-time scoring with 7-day history and alert detection	2	{"highlight": "Watchlist Scoring"}	2025-12-08 16:35:22.088437-05
24	VG-PORT	feature	Narrative Intelligence: Plain-language insights for every watchlist ticker	3	{"highlight": "Narrative Intelligence"}	2025-12-08 16:35:22.088437-05
25	VG-PORT	feature	Auto-Sync: Portfolio holdings automatically added to watchlist	4	{"highlight": "Auto-Sync"}	2025-12-08 16:35:22.088437-05
26	VG-PORT	feature	Source Tracking: Display which data source provided each quote	5	{"highlight": "Source Tracking"}	2025-12-08 16:35:22.088437-05
27	VG-PORT	success_criterion	All portfolio positions show current analytics within 15 minutes	1	\N	2025-12-08 16:35:22.088437-05
28	VG-PORT	success_criterion	Watchlist scores update on user-configurable schedule (default: 1 minute)	2	\N	2025-12-08 16:35:22.088437-05
29	VG-PORT	success_criterion	Users can see data provenance (source indicators)	3	\N	2025-12-08 16:35:22.088437-05
30	VG-PORT	success_criterion	Portfolio and watchlist data synchronized automatically	4	\N	2025-12-08 16:35:22.088437-05
31	VG-VALID	objective	Never recommend untested strategies	0	\N	2025-12-08 16:35:22.088437-05
32	VG-VALID	feature	Backtesting: Replay strategies against historical data with performance metrics	1	{"highlight": "Backtesting"}	2025-12-08 16:35:22.088437-05
33	VG-VALID	feature	Paper Trading: Execute trades in simulation with cash management	2	{"highlight": "Paper Trading"}	2025-12-08 16:35:22.088437-05
34	VG-VALID	feature	Performance Tracking: Sharpe ratio, max drawdown, win rate, total return	3	{"highlight": "Performance Tracking"}	2025-12-08 16:35:22.088437-05
35	VG-VALID	feature	Equity Curves: Visual comparison of strategy performance over time	4	{"highlight": "Equity Curves"}	2025-12-08 16:35:22.088437-05
36	VG-VALID	feature	Transaction Audit: Complete history of all simulated trades	5	{"highlight": "Transaction Audit"}	2025-12-08 16:35:22.088437-05
37	VG-VALID	success_criterion	Every strategy backtested before paper trading	1	\N	2025-12-08 16:35:22.088437-05
38	VG-VALID	success_criterion	Paper trades tracked with full transaction history	2	\N	2025-12-08 16:35:22.088437-05
39	VG-VALID	success_criterion	Performance metrics updated daily	3	\N	2025-12-08 16:35:22.088437-05
40	VG-VALID	success_criterion	Equity curves available for visual comparison	4	\N	2025-12-08 16:35:22.088437-05
41	VG-RELY	objective	Production-grade reliability with zero single points of failure	0	\N	2025-12-08 16:35:22.088437-05
42	VG-RELY	feature	Multi-Source Failover: 6 operational data sources with priority-based failover	1	{"highlight": "Multi-Source Failover"}	2025-12-08 16:35:22.088437-05
43	VG-RELY	feature	Freshness Monitoring: Automated checks with scheduled data refreshes	2	{"highlight": "Freshness Monitoring"}	2025-12-08 16:35:22.088437-05
44	VG-RELY	feature	PostgreSQL: Production database with connection pooling (4x throughput)	3	{"highlight": "PostgreSQL"}	2025-12-08 16:35:22.088437-05
45	VG-RELY	feature	Health Dashboard: Real-time system health with 9+ monitored subsystems	4	{"highlight": "Health Dashboard"}	2025-12-08 16:35:22.088437-05
46	VG-RELY	feature	Scheduled Maintenance: Automated cleanup of stale data (logs, news, temp files)	5	{"highlight": "Scheduled Maintenance"}	2025-12-08 16:35:22.088437-05
47	VG-RELY	success_criterion	Zero downtime from single data source failures	1	\N	2025-12-08 16:35:22.088437-05
48	VG-RELY	success_criterion	Data freshness <24 hours for all tables	2	\N	2025-12-08 16:35:22.088437-05
49	VG-RELY	success_criterion	Health dashboard shows all systems green	3	\N	2025-12-08 16:35:22.088437-05
50	VG-RELY	success_criterion	Automated maintenance runs without intervention	4	\N	2025-12-08 16:35:22.088437-05
51	VG-UX	objective	Professional, responsive, delightful interface	0	\N	2025-12-08 16:35:22.088437-05
52	VG-UX	feature	Real-Time Updates: Auto-refresh with progress tracking and toast notifications	1	{"highlight": "Real-Time Updates"}	2025-12-08 16:35:22.088437-05
53	VG-UX	feature	Visual Analytics: Equity curves, sparklines, Fear & Greed gauge, sector allocation	2	{"highlight": "Visual Analytics"}	2025-12-08 16:35:22.088437-05
54	VG-UX	feature	Mobile Responsive: Full functionality on phones/tablets	3	{"highlight": "Mobile Responsive"}	2025-12-08 16:35:22.088437-05
55	VG-UX	feature	Theming: Dark/light modes with CSS variables	4	{"highlight": "Theming"}	2025-12-08 16:35:22.088437-05
56	VG-UX	feature	Accessibility: ARIA labels, keyboard navigation, screen reader support	5	{"highlight": "Accessibility"}	2025-12-08 16:35:22.088437-05
57	VG-UX	success_criterion	All pages mobile-responsive (tested on iPhone 12 Pro)	1	\N	2025-12-08 16:35:22.088437-05
58	VG-UX	success_criterion	WCAG AA accessibility compliance	2	\N	2025-12-08 16:35:22.088437-05
59	VG-UX	success_criterion	Page load times <2 seconds	3	\N	2025-12-08 16:35:22.088437-05
60	VG-UX	success_criterion	Real-time updates without page refresh	4	\N	2025-12-08 16:35:22.088437-05
61	VG-QUAL	objective	Maintainable, testable, high-quality codebase	0	\N	2025-12-08 16:35:22.088437-05
62	VG-QUAL	feature	Test Coverage: 85%+ with 508 passing tests	1	{"highlight": "Test Coverage"}	2025-12-08 16:35:22.088437-05
63	VG-QUAL	feature	Type Safety: Mypy --strict compliance across all modules	2	{"highlight": "Type Safety"}	2025-12-08 16:35:22.088437-05
64	VG-QUAL	feature	Modular Architecture: Single-responsibility modules <500 lines	3	{"highlight": "Modular Architecture"}	2025-12-08 16:35:22.088437-05
65	VG-QUAL	feature	Automated Linting: Ruff + mypy in pre-commit hooks	4	{"highlight": "Automated Linting"}	2025-12-08 16:35:22.088437-05
66	VG-QUAL	feature	Documentation: Comprehensive docs for all major systems	5	{"highlight": "Documentation"}	2025-12-08 16:35:22.088437-05
67	VG-QUAL	success_criterion	All tests passing (100% pass rate)	1	\N	2025-12-08 16:35:22.088437-05
68	VG-QUAL	success_criterion	Zero mypy --strict errors	2	\N	2025-12-08 16:35:22.088437-05
69	VG-QUAL	success_criterion	All files <800 lines (hard limit)	3	\N	2025-12-08 16:35:22.088437-05
70	VG-QUAL	success_criterion	Pre-commit hooks enforce quality standards	4	\N	2025-12-08 16:35:22.088437-05
\.


--
-- Data for Name: vision_goals; Type: TABLE DATA; Schema: public; Owner: summitflow_app
--

COPY public.vision_goals (code, name, description, category, created_at, updated_at, project_id) FROM stdin;
VG-PERF	VG-PERF (auto-created)	Vision goal auto-created during migration from feature_capabilities.vision_goals array	other	2025-12-08 16:36:17.772809-05	2025-12-08 16:36:17.772809-05	portfolio-ai
VG-DEVHUB	Developer Command Center	Central hub for AI-assisted development - tasks, agents, codebase health in one place	platform	2025-12-20 10:36:25.03227-05	2025-12-20 10:36:25.03227-05	summitflow
VG-TASKFLOW	Intelligent Task Management	Track issues, manage dependencies, automate workflows with AI-powered prioritization	workflow	2025-12-20 10:36:25.057019-05	2025-12-20 10:36:25.057019-05	summitflow
VG-EXPLORE	Codebase Intelligence	Unified view of files, tables, endpoints, and their relationships across projects	intelligence	2025-12-20 10:36:25.076885-05	2025-12-20 10:36:25.076885-05	summitflow
VG-AGENTS	Multi-Agent Orchestration	Roundtable discussions, task execution, and agent monitoring with Claude and Gemini	agents	2025-12-20 10:36:25.097109-05	2025-12-20 10:36:25.097109-05	summitflow
VG-COHERENCE	Architecture Coherence	Enforce DRY principles, prevent silos, maintain consistent patterns across codebase	quality	2025-12-20 10:36:25.117312-05	2025-12-20 10:36:25.117312-05	summitflow
VG-QUAL	Code Quality	Testing, documentation, and coding standards. Maintainable, testable, high-quality codebase.	quality	2025-12-06 17:12:38.627691-05	2025-12-20 10:40:53.481915-05	summitflow
VG-CAPTURE	Observation Capture	Fire-and-forget capture of all agent tool executions with less than 100ms latency impact	capture	2025-12-20 10:37:03.295245-05	2025-12-20 10:37:03.295245-05	context-hub
VG-MEMORY	Persistent Memory	Store and retrieve observations, patterns, and learnings across sessions and projects	memory	2025-12-20 10:37:03.320082-05	2025-12-20 10:37:03.320082-05	context-hub
VG-CONTEXT	Intelligent Context	Progressive disclosure for 87% token reduction - agents get focused, relevant context only	context	2025-12-20 10:37:03.33985-05	2025-12-20 10:37:03.33985-05	context-hub
VG-LEARNING	Auto-Learning System	Pattern recognition, weekly reflection, and automatic application of learnings to projects	learning	2025-12-20 10:37:03.360204-05	2025-12-20 10:37:03.360204-05	context-hub
VG-UNIVERSAL	Universal Integration	SDK and hooks for Claude Code, SummitFlow, Portfolio-AI, and any future AI systems	integration	2025-12-20 10:37:03.379452-05	2025-12-20 10:37:03.379452-05	context-hub
VG-INTEL	Market Intelligence	AI-driven market insights and analysis. Transform raw market data into actionable insights through signal fusion, confidence scoring, and style classification.	intelligence	2025-12-06 17:12:38.627691-05	2025-12-06 17:41:42.893444-05	portfolio-ai
VG-AUTO	Autonomous Operation	Self-running trading and research agents. Use AI agents as analysts for market discovery, portfolio analysis, and strategy review.	automation	2025-12-06 17:12:38.627691-05	2025-12-06 17:41:42.893444-05	portfolio-ai
VG-PORT	Portfolio Management	Position tracking, analytics, and optimization. Unified monitoring of owned and watched positions with real-time analytics.	portfolio	2025-12-06 17:12:38.627691-05	2025-12-06 17:41:42.893444-05	portfolio-ai
VG-VALID	Strategy Validation	Backtesting, walk-forward analysis, and monte carlo simulation. Never recommend untested strategies.	validation	2025-12-06 17:12:38.627691-05	2025-12-06 17:41:42.893444-05	portfolio-ai
VG-RELY	System Reliability	Monitoring, health checks, and fault tolerance. Production-grade reliability with observability.	reliability	2025-12-06 17:12:38.627691-05	2025-12-20 10:40:53.501037-05	portfolio-ai
VG-UX	User Experience	Professional, responsive, and intuitive interface. Real-time updates and clear feedback.	ux	2025-12-06 17:12:38.627691-05	2025-12-20 10:40:53.522849-05	portfolio-ai
\.


--
-- Name: artifacts_id_seq; Type: SEQUENCE SET; Schema: public; Owner: summitflow_app
--

SELECT pg_catalog.setval('public.artifacts_id_seq', 1, false);


--
-- Name: feature_capabilities_id_seq; Type: SEQUENCE SET; Schema: public; Owner: summitflow_app
--

SELECT pg_catalog.setval('public.feature_capabilities_id_seq', 320, true);


--
-- Name: feature_dependencies_id_seq; Type: SEQUENCE SET; Schema: public; Owner: summitflow_app
--

SELECT pg_catalog.setval('public.feature_dependencies_id_seq', 1, false);


--
-- Name: feature_tasks_id_seq; Type: SEQUENCE SET; Schema: public; Owner: summitflow_app
--

SELECT pg_catalog.setval('public.feature_tasks_id_seq', 109, true);


--
-- Name: feature_vision_goal_mappings_id_seq; Type: SEQUENCE SET; Schema: public; Owner: summitflow_app
--

SELECT pg_catalog.setval('public.feature_vision_goal_mappings_id_seq', 1, false);


--
-- Name: vision_content_id_seq; Type: SEQUENCE SET; Schema: public; Owner: summitflow_app
--

SELECT pg_catalog.setval('public.vision_content_id_seq', 29, true);


--
-- Name: vision_goal_details_id_seq; Type: SEQUENCE SET; Schema: public; Owner: summitflow_app
--

SELECT pg_catalog.setval('public.vision_goal_details_id_seq', 70, true);


--
-- Name: artifacts artifacts_pkey; Type: CONSTRAINT; Schema: public; Owner: summitflow_app
--

ALTER TABLE ONLY public.artifacts
    ADD CONSTRAINT artifacts_pkey PRIMARY KEY (id);


--
-- Name: artifacts artifacts_project_id_artifact_id_key; Type: CONSTRAINT; Schema: public; Owner: summitflow_app
--

ALTER TABLE ONLY public.artifacts
    ADD CONSTRAINT artifacts_project_id_artifact_id_key UNIQUE (project_id, artifact_id);


--
-- Name: feature_capabilities feature_capabilities_pkey; Type: CONSTRAINT; Schema: public; Owner: summitflow_app
--

ALTER TABLE ONLY public.feature_capabilities
    ADD CONSTRAINT feature_capabilities_pkey PRIMARY KEY (id);


--
-- Name: feature_capabilities feature_capabilities_project_id_feature_id_key; Type: CONSTRAINT; Schema: public; Owner: summitflow_app
--

ALTER TABLE ONLY public.feature_capabilities
    ADD CONSTRAINT feature_capabilities_project_id_feature_id_key UNIQUE (project_id, feature_id);


--
-- Name: feature_dependencies feature_dependencies_feature_id_depends_on_id_key; Type: CONSTRAINT; Schema: public; Owner: summitflow_app
--

ALTER TABLE ONLY public.feature_dependencies
    ADD CONSTRAINT feature_dependencies_feature_id_depends_on_id_key UNIQUE (feature_id, depends_on_id);


--
-- Name: feature_dependencies feature_dependencies_pkey; Type: CONSTRAINT; Schema: public; Owner: summitflow_app
--

ALTER TABLE ONLY public.feature_dependencies
    ADD CONSTRAINT feature_dependencies_pkey PRIMARY KEY (id);


--
-- Name: feature_tasks feature_tasks_pkey; Type: CONSTRAINT; Schema: public; Owner: summitflow_app
--

ALTER TABLE ONLY public.feature_tasks
    ADD CONSTRAINT feature_tasks_pkey PRIMARY KEY (id);


--
-- Name: feature_tasks feature_tasks_unique_task; Type: CONSTRAINT; Schema: public; Owner: summitflow_app
--

ALTER TABLE ONLY public.feature_tasks
    ADD CONSTRAINT feature_tasks_unique_task UNIQUE (feature_id, task_id);


--
-- Name: feature_vision_goal_mappings feature_vision_goal_mappings_feature_id_vision_code_key; Type: CONSTRAINT; Schema: public; Owner: summitflow_app
--

ALTER TABLE ONLY public.feature_vision_goal_mappings
    ADD CONSTRAINT feature_vision_goal_mappings_feature_id_vision_code_key UNIQUE (feature_id, vision_code);


--
-- Name: feature_vision_goal_mappings feature_vision_goal_mappings_pkey; Type: CONSTRAINT; Schema: public; Owner: summitflow_app
--

ALTER TABLE ONLY public.feature_vision_goal_mappings
    ADD CONSTRAINT feature_vision_goal_mappings_pkey PRIMARY KEY (id);


--
-- Name: vision_content vision_content_pkey; Type: CONSTRAINT; Schema: public; Owner: summitflow_app
--

ALTER TABLE ONLY public.vision_content
    ADD CONSTRAINT vision_content_pkey PRIMARY KEY (id);


--
-- Name: vision_content vision_content_project_id_content_type_content_key_key; Type: CONSTRAINT; Schema: public; Owner: summitflow_app
--

ALTER TABLE ONLY public.vision_content
    ADD CONSTRAINT vision_content_project_id_content_type_content_key_key UNIQUE (project_id, content_type, content_key);


--
-- Name: vision_goal_details vision_goal_details_goal_code_detail_type_order_num_key; Type: CONSTRAINT; Schema: public; Owner: summitflow_app
--

ALTER TABLE ONLY public.vision_goal_details
    ADD CONSTRAINT vision_goal_details_goal_code_detail_type_order_num_key UNIQUE (goal_code, detail_type, order_num);


--
-- Name: vision_goal_details vision_goal_details_pkey; Type: CONSTRAINT; Schema: public; Owner: summitflow_app
--

ALTER TABLE ONLY public.vision_goal_details
    ADD CONSTRAINT vision_goal_details_pkey PRIMARY KEY (id);


--
-- Name: vision_goals vision_goals_pkey; Type: CONSTRAINT; Schema: public; Owner: summitflow_app
--

ALTER TABLE ONLY public.vision_goals
    ADD CONSTRAINT vision_goals_pkey PRIMARY KEY (code);


--
-- Name: idx_artifacts_criterion; Type: INDEX; Schema: public; Owner: summitflow_app
--

CREATE INDEX idx_artifacts_criterion ON public.artifacts USING btree (criterion_id);


--
-- Name: idx_artifacts_current; Type: INDEX; Schema: public; Owner: summitflow_app
--

CREATE INDEX idx_artifacts_current ON public.artifacts USING btree (is_current) WHERE (is_current = true);


--
-- Name: idx_artifacts_feature; Type: INDEX; Schema: public; Owner: summitflow_app
--

CREATE INDEX idx_artifacts_feature ON public.artifacts USING btree (feature_id);


--
-- Name: idx_artifacts_project; Type: INDEX; Schema: public; Owner: summitflow_app
--

CREATE INDEX idx_artifacts_project ON public.artifacts USING btree (project_id);


--
-- Name: idx_artifacts_quality; Type: INDEX; Schema: public; Owner: summitflow_app
--

CREATE INDEX idx_artifacts_quality ON public.artifacts USING btree (quality_status);


--
-- Name: idx_feature_category; Type: INDEX; Schema: public; Owner: summitflow_app
--

CREATE INDEX idx_feature_category ON public.feature_capabilities USING btree (category);


--
-- Name: idx_feature_deps_depends; Type: INDEX; Schema: public; Owner: summitflow_app
--

CREATE INDEX idx_feature_deps_depends ON public.feature_dependencies USING btree (depends_on_id);


--
-- Name: idx_feature_deps_feature; Type: INDEX; Schema: public; Owner: summitflow_app
--

CREATE INDEX idx_feature_deps_feature ON public.feature_dependencies USING btree (feature_id);


--
-- Name: idx_feature_passes; Type: INDEX; Schema: public; Owner: summitflow_app
--

CREATE INDEX idx_feature_passes ON public.feature_capabilities USING btree (passes);


--
-- Name: idx_feature_project; Type: INDEX; Schema: public; Owner: summitflow_app
--

CREATE INDEX idx_feature_project ON public.feature_capabilities USING btree (project_id);


--
-- Name: idx_feature_status; Type: INDEX; Schema: public; Owner: summitflow_app
--

CREATE INDEX idx_feature_status ON public.feature_capabilities USING btree (status);


--
-- Name: idx_feature_tasks_completed; Type: INDEX; Schema: public; Owner: summitflow_app
--

CREATE INDEX idx_feature_tasks_completed ON public.feature_tasks USING btree (completed);


--
-- Name: idx_feature_tasks_feature; Type: INDEX; Schema: public; Owner: summitflow_app
--

CREATE INDEX idx_feature_tasks_feature ON public.feature_tasks USING btree (feature_id);


--
-- Name: idx_fvgm_feature; Type: INDEX; Schema: public; Owner: summitflow_app
--

CREATE INDEX idx_fvgm_feature ON public.feature_vision_goal_mappings USING btree (feature_id);


--
-- Name: idx_fvgm_vision; Type: INDEX; Schema: public; Owner: summitflow_app
--

CREATE INDEX idx_fvgm_vision ON public.feature_vision_goal_mappings USING btree (vision_code);


--
-- Name: idx_vision_content_project; Type: INDEX; Schema: public; Owner: summitflow_app
--

CREATE INDEX idx_vision_content_project ON public.vision_content USING btree (project_id);


--
-- Name: idx_vision_content_type; Type: INDEX; Schema: public; Owner: summitflow_app
--

CREATE INDEX idx_vision_content_type ON public.vision_content USING btree (content_type);


--
-- Name: idx_vision_goal_details_code; Type: INDEX; Schema: public; Owner: summitflow_app
--

CREATE INDEX idx_vision_goal_details_code ON public.vision_goal_details USING btree (goal_code);


--
-- Name: idx_vision_goal_details_type; Type: INDEX; Schema: public; Owner: summitflow_app
--

CREATE INDEX idx_vision_goal_details_type ON public.vision_goal_details USING btree (detail_type);


--
-- Name: idx_vision_goals_category; Type: INDEX; Schema: public; Owner: summitflow_app
--

CREATE INDEX idx_vision_goals_category ON public.vision_goals USING btree (category);


--
-- Name: idx_vision_goals_project; Type: INDEX; Schema: public; Owner: summitflow_app
--

CREATE INDEX idx_vision_goals_project ON public.vision_goals USING btree (project_id);


--
-- Name: artifacts artifacts_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: summitflow_app
--

ALTER TABLE ONLY public.artifacts
    ADD CONSTRAINT artifacts_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE CASCADE;


--
-- Name: feature_capabilities feature_capabilities_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: summitflow_app
--

ALTER TABLE ONLY public.feature_capabilities
    ADD CONSTRAINT feature_capabilities_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE CASCADE;


--
-- Name: feature_dependencies feature_dependencies_depends_on_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: summitflow_app
--

ALTER TABLE ONLY public.feature_dependencies
    ADD CONSTRAINT feature_dependencies_depends_on_id_fkey FOREIGN KEY (depends_on_id) REFERENCES public.feature_capabilities(id) ON DELETE CASCADE;


--
-- Name: feature_dependencies feature_dependencies_feature_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: summitflow_app
--

ALTER TABLE ONLY public.feature_dependencies
    ADD CONSTRAINT feature_dependencies_feature_id_fkey FOREIGN KEY (feature_id) REFERENCES public.feature_capabilities(id) ON DELETE CASCADE;


--
-- Name: feature_tasks feature_tasks_feature_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: summitflow_app
--

ALTER TABLE ONLY public.feature_tasks
    ADD CONSTRAINT feature_tasks_feature_id_fkey FOREIGN KEY (feature_id) REFERENCES public.feature_capabilities(id) ON DELETE CASCADE;


--
-- Name: feature_vision_goal_mappings feature_vision_goal_mappings_feature_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: summitflow_app
--

ALTER TABLE ONLY public.feature_vision_goal_mappings
    ADD CONSTRAINT feature_vision_goal_mappings_feature_id_fkey FOREIGN KEY (feature_id) REFERENCES public.feature_capabilities(id) ON DELETE CASCADE;


--
-- Name: feature_vision_goal_mappings feature_vision_goal_mappings_vision_code_fkey; Type: FK CONSTRAINT; Schema: public; Owner: summitflow_app
--

ALTER TABLE ONLY public.feature_vision_goal_mappings
    ADD CONSTRAINT feature_vision_goal_mappings_vision_code_fkey FOREIGN KEY (vision_code) REFERENCES public.vision_goals(code) ON DELETE CASCADE;


--
-- Name: vision_content vision_content_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: summitflow_app
--

ALTER TABLE ONLY public.vision_content
    ADD CONSTRAINT vision_content_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE CASCADE;


--
-- Name: vision_goal_details vision_goal_details_goal_code_fkey; Type: FK CONSTRAINT; Schema: public; Owner: summitflow_app
--

ALTER TABLE ONLY public.vision_goal_details
    ADD CONSTRAINT vision_goal_details_goal_code_fkey FOREIGN KEY (goal_code) REFERENCES public.vision_goals(code) ON DELETE CASCADE;


--
-- Name: vision_goals vision_goals_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: summitflow_app
--

ALTER TABLE ONLY public.vision_goals
    ADD CONSTRAINT vision_goals_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id);


--
-- PostgreSQL database dump complete
--

\unrestrict 2t370lPfNe6fkMhW6MT53l8ktaDyeBOsV1zaY0KBIUg3RoTLcRhqrk3LuHW3HRf
