--
-- PostgreSQL database dump
--

\restrict LgsTpvs7UAJBalgWeSpxTzNNPWg2FnAoQLJ9u3IWTVbo18VSLZxqN2nIPOASANU

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
    layer_results jsonb DEFAULT '{}'::jsonb,
    implementation_notes text,
    acceptance_criteria jsonb DEFAULT '[]'::jsonb,
    vision_goals text[] DEFAULT '{}'::text[],
    last_verified_at timestamp with time zone,
    verified_by character varying(50),
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
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
    completed_by character varying(50),
    files text[],
    notes text,
    status character varying(20) DEFAULT 'pending'::character varying,
    effort character varying(10),
    task_type character varying(20) DEFAULT 'implementation'::character varying
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
    project_id text,
    name text NOT NULL,
    description text,
    category text,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


ALTER TABLE public.vision_goals OWNER TO summitflow_app;

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
-- Data for Name: feature_capabilities; Type: TABLE DATA; Schema: public; Owner: summitflow_app
--

COPY public.feature_capabilities (id, project_id, feature_id, name, category, description, passes, task_file, task_section, health_status, status, effort, priority, verification_layers, layer_results, implementation_notes, acceptance_criteria, vision_goals, last_verified_at, verified_by, created_at, updated_at) FROM stdin;
\.


--
-- Data for Name: feature_dependencies; Type: TABLE DATA; Schema: public; Owner: summitflow_app
--

COPY public.feature_dependencies (id, feature_id, depends_on_id, dependency_type, notes, created_at) FROM stdin;
\.


--
-- Data for Name: feature_tasks; Type: TABLE DATA; Schema: public; Owner: summitflow_app
--

COPY public.feature_tasks (id, feature_id, task_id, description, completed, order_num, created_at, updated_at, completed_at, completed_by, files, notes, status, effort, task_type) FROM stdin;
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
\.


--
-- Data for Name: vision_goal_details; Type: TABLE DATA; Schema: public; Owner: summitflow_app
--

COPY public.vision_goal_details (id, goal_code, detail_type, content, order_num, metadata, created_at) FROM stdin;
\.


--
-- Data for Name: vision_goals; Type: TABLE DATA; Schema: public; Owner: summitflow_app
--

COPY public.vision_goals (code, project_id, name, description, category, created_at, updated_at) FROM stdin;
\.


--
-- Name: feature_capabilities_id_seq; Type: SEQUENCE SET; Schema: public; Owner: summitflow_app
--

SELECT pg_catalog.setval('public.feature_capabilities_id_seq', 1, false);


--
-- Name: feature_dependencies_id_seq; Type: SEQUENCE SET; Schema: public; Owner: summitflow_app
--

SELECT pg_catalog.setval('public.feature_dependencies_id_seq', 1, false);


--
-- Name: feature_tasks_id_seq; Type: SEQUENCE SET; Schema: public; Owner: summitflow_app
--

SELECT pg_catalog.setval('public.feature_tasks_id_seq', 1, false);


--
-- Name: feature_vision_goal_mappings_id_seq; Type: SEQUENCE SET; Schema: public; Owner: summitflow_app
--

SELECT pg_catalog.setval('public.feature_vision_goal_mappings_id_seq', 1, false);


--
-- Name: vision_content_id_seq; Type: SEQUENCE SET; Schema: public; Owner: summitflow_app
--

SELECT pg_catalog.setval('public.vision_content_id_seq', 1, false);


--
-- Name: vision_goal_details_id_seq; Type: SEQUENCE SET; Schema: public; Owner: summitflow_app
--

SELECT pg_catalog.setval('public.vision_goal_details_id_seq', 1, false);


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

\unrestrict LgsTpvs7UAJBalgWeSpxTzNNPWg2FnAoQLJ9u3IWTVbo18VSLZxqN2nIPOASANU
