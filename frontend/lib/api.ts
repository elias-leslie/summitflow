// API Base URL - always empty to use relative URLs
// Next.js rewrites proxy /api/* to backend (works for both SSR and client-side)
// Build: 2025-12-26-v1
import { fetchWithErrorHandling, getApiBase } from "./api/utils";
import {
  fetchWithGenerationTimeout,
  roundtableSessionAction,
  buildRoundtableGenerationUrl,
} from "./api/wrappers";

// Re-export domain modules
export * from "./api/evidence";
export * from "./api/tasks";
export * from "./api/notifications";
export * from "./api/projects";

// ============================================================================
// Common Types (used by Explorer)
// ============================================================================

export type HealthStatus = "healthy" | "warning" | "error" | "unknown";

// ============================================================================
// Acceptance Criteria Types
// ============================================================================

export interface AcceptanceCriterion {
  id: string;
  criterion: string;
  verification: string;
  type: string;
  passed: boolean | null;
  verified_at: string | null;
  verification_output: string | null;
}

// =============================================================================
// Roundtable API
// =============================================================================

export interface RoundtableMessage {
  id: string;
  agent: "user" | "claude" | "gemini";
  content: string;
  timestamp: string;
  tokens_used?: number;
  model?: string | null;
}

export interface ToolStats {
  total_calls: number;
  files_read: number;
  searches: number;
  writes: number;
}

export interface RoundtableSession {
  id: string;
  project_id: string;
  mode: "spec_driven" | "quick";
  tools_enabled: boolean;
  write_enabled: boolean;
  yolo_mode: boolean;
  tool_stats: ToolStats;
  agent_override: string | null;
  model_override: string | null;
  messages: RoundtableMessage[];
  generated_features?: GeneratedFeature[];
  created_at: string;
  updated_at: string;
}

export interface RoundtableSessionInfo {
  id: string;
  project_id: string;
  title: string | null;
  status: "active" | "archived";
  mode: string;
  agent_mode: "claude" | "gemini" | "both";
  tools_enabled: boolean;
  write_enabled: boolean;
  yolo_mode: boolean;
  tool_stats?: ToolStats;
  agent_override: string | null;
  model_override: string | null;
  message_count: number;
  feature_count: number;
  created_at: string;
  updated_at: string;
}

export interface GeneratedFeature {
  capability_id: string;
  name: string;
  category: string;
  priority: number;
  description?: string;
  acceptance_criteria: { id: string; description: string }[];
}

export interface CreateSessionResponse {
  session_id: string;
  project_id: string;
  title: string | null;
  mode: string;
  agent_mode: "claude" | "gemini" | "both";
  status: "active" | "archived";
  tools_enabled: boolean;
  write_enabled: boolean;
  yolo_mode: boolean;
}

export interface CreateSessionOptions {
  title?: string;
  mode?: "spec_driven" | "quick";
  agentMode?: "claude" | "gemini" | "both";
  toolsEnabled?: boolean;
  writeEnabled?: boolean;
  yoloMode?: boolean;
}

export async function createRoundtableSession(
  projectId: string,
  options: CreateSessionOptions = {}
): Promise<CreateSessionResponse> {
  const {
    title,
    mode = "quick",
    agentMode = "both",
    toolsEnabled = true,
    writeEnabled = false,
    yoloMode = false,
  } = options;

  return fetchWithErrorHandling(`/api/projects/${projectId}/roundtable/sessions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      title,
      mode,
      agent_mode: agentMode,
      tools_enabled: toolsEnabled,
      write_enabled: writeEnabled,
      yolo_mode: yoloMode,
    }),
    errorMessage: "Failed to create roundtable session",
  });
}

export async function listRoundtableSessions(
  projectId: string,
  status?: "active" | "archived"
): Promise<RoundtableSessionInfo[]> {
  const query = status ? `?status=${status}` : "";
  return fetchWithErrorHandling(`/api/projects/${projectId}/roundtable/sessions${query}`, {
    errorMessage: "Failed to list roundtable sessions",
  });
}

export async function getRoundtableSession(projectId: string, sessionId: string): Promise<RoundtableSession> {
  return fetchWithErrorHandling(`/api/projects/${projectId}/roundtable/sessions/${sessionId}`, {
    errorMessage: "Failed to get roundtable session",
  });
}

export async function deleteRoundtableSession(projectId: string, sessionId: string): Promise<void> {
  return fetchWithErrorHandling(`/api/projects/${projectId}/roundtable/sessions/${sessionId}`, {
    method: "DELETE",
    errorMessage: "Failed to delete roundtable session",
  });
}

export interface UpdateToolsResponse {
  session_id: string;
  tools_enabled: boolean;
  write_enabled: boolean;
  yolo_mode: boolean;
  tool_stats: ToolStats;
}

export interface UpdateToolsOptions {
  toolsEnabled?: boolean;
  writeEnabled?: boolean;
  yoloMode?: boolean;
}

export async function updateRoundtableTools(
  projectId: string,
  sessionId: string,
  options: UpdateToolsOptions
): Promise<UpdateToolsResponse> {
  const body: Record<string, boolean> = {};
  if (options.toolsEnabled !== undefined) body.tools_enabled = options.toolsEnabled;
  if (options.writeEnabled !== undefined) body.write_enabled = options.writeEnabled;
  if (options.yoloMode !== undefined) body.yolo_mode = options.yoloMode;

  return fetchWithErrorHandling(`/api/projects/${projectId}/roundtable/sessions/${sessionId}/tools`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    errorMessage: "Failed to update roundtable tools",
  });
}

export interface AgentConfigUpdate {
  agent_override: string | null;
  model_override: string | null;
}

export interface AgentConfigResponse {
  agent_override: string | null;
  model_override: string | null;
}

export async function updateRoundtableAgentConfig(
  projectId: string,
  sessionId: string,
  config: AgentConfigUpdate
): Promise<AgentConfigResponse> {
  const res = await fetch(
    `${getApiBase()}/api/projects/${projectId}/roundtable/sessions/${sessionId}/agent-config`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(config),
    }
  );
  if (!res.ok) throw new Error("Failed to update agent config");
  return res.json();
}

// SSE event types for roundtable streaming
export type RoundtableSSEEventType =
  | "user_message"
  | "agent_start"
  | "agent_complete"
  | "keepalive"
  | "done"
  | "error"
  | "permission_request";

export interface RoundtableSSEEvent {
  type: RoundtableSSEEventType;
  data: {
    id?: string;
    agent?: "claude" | "gemini";
    content?: string;
    timestamp?: string;
    tokens_used?: number;
    model?: string;
    session_id?: string;
    response_count?: number;
    message?: string; // for error events
    // Permission request fields
    permission_id?: string;
    tool_name?: string;
    params?: Record<string, unknown>;
    preview?: string;
  };
}

/**
 * Represents a pending permission request for write tool operations.
 */
export interface PermissionRequest {
  permission_id: string;
  tool_name: string;
  params: Record<string, unknown>;
  preview?: string;
  agent: "claude" | "gemini";
}

/**
 * Resolve a pending permission request (approve or deny).
 */
export async function resolvePermission(
  projectId: string,
  sessionId: string,
  permissionId: string,
  approved: boolean
): Promise<void> {
  const res = await fetch(
    `${getApiBase()}/api/projects/${projectId}/roundtable/sessions/${sessionId}/permissions/${permissionId}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ approved }),
    }
  );
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: "Failed to resolve permission" }));
    throw new Error(error.detail || "Failed to resolve permission");
  }
}

/**
 * Stream roundtable messages via SSE.
 * Returns an async generator that yields SSE events as they arrive.
 */
export async function* streamRoundtableMessage(
  projectId: string,
  sessionId: string,
  message: string,
  target: "claude" | "gemini" | "both" = "both",
  signal?: AbortSignal
): AsyncGenerator<RoundtableSSEEvent> {
  const res = await fetch(
    `${getApiBase()}/api/projects/${projectId}/roundtable/sessions/${sessionId}/messages/stream`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, target }),
      signal,
    }
  );

  if (!res.ok) {
    throw new Error("Failed to stream roundtable message");
  }

  if (!res.body) {
    throw new Error("No response body for SSE stream");
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });

      // Process complete SSE events (separated by double newlines)
      const events = buffer.split("\n\n");
      buffer = events.pop() || ""; // Keep incomplete event in buffer

      for (const eventBlock of events) {
        if (!eventBlock.trim()) continue;

        const lines = eventBlock.split("\n");
        let eventType: RoundtableSSEEventType = "done";
        let eventData = {};

        for (const line of lines) {
          if (line.startsWith("event: ")) {
            eventType = line.slice(7) as RoundtableSSEEventType;
          } else if (line.startsWith("data: ")) {
            try {
              eventData = JSON.parse(line.slice(6));
            } catch {
              console.warn("Failed to parse SSE data:", line);
            }
          }
        }

        yield { type: eventType, data: eventData };
      }
    }
  } finally {
    reader.releaseLock();
  }
}

export async function generateFeaturesFromRoundtable(
  projectId: string,
  sessionId: string,
  agent: "claude" | "gemini" = "claude"
): Promise<{ features: GeneratedFeature[]; session_id: string }> {
  return fetchWithGenerationTimeout(
    buildRoundtableGenerationUrl(projectId, sessionId, "generate-features"),
    { agent },
    "Failed to generate features from roundtable"
  );
}

// Vision/Goals types for roundtable generation
export interface GeneratedMission {
  statement: string;
  values: string[];
}

export interface GeneratedNarrative {
  id: string;
  title: string;
  content: string;
  category: string;
}

export interface GeneratedGoal {
  code: string;
  name: string;
  description: string;
  category: string;
}

export interface GenerateVisionResponse {
  mission: GeneratedMission | null;
  narratives: GeneratedNarrative[];
  session_id: string;
}

export interface GenerateGoalsResponse {
  goals: GeneratedGoal[];
  session_id: string;
}

export async function generateVisionFromRoundtable(
  projectId: string,
  sessionId: string,
  agent: "claude" | "gemini" = "claude"
): Promise<GenerateVisionResponse> {
  return fetchWithGenerationTimeout(
    buildRoundtableGenerationUrl(projectId, sessionId, "generate-vision"),
    { agent },
    "Failed to generate vision from roundtable"
  );
}

export async function saveVisionFromRoundtable(
  projectId: string,
  sessionId: string,
  mission: GeneratedMission | null,
  narratives: GeneratedNarrative[]
): Promise<{ status: string; project_id: string }> {
  return roundtableSessionAction(
    projectId, sessionId, "save-vision",
    { mission, narratives },
    "Failed to save vision"
  );
}

export async function generateGoalsFromRoundtable(
  projectId: string,
  sessionId: string,
  agent: "claude" | "gemini" = "claude"
): Promise<GenerateGoalsResponse> {
  return fetchWithGenerationTimeout(
    buildRoundtableGenerationUrl(projectId, sessionId, "generate-goals"),
    { agent },
    "Failed to generate goals from roundtable"
  );
}

export async function saveGoalsFromRoundtable(
  projectId: string,
  sessionId: string,
  goals: GeneratedGoal[]
): Promise<{ status: string; project_id: string; goals_created: number }> {
  return roundtableSessionAction(
    projectId, sessionId, "save-goals",
    { goals },
    "Failed to save goals"
  );
}

// =============================================================================
// TDD Spec Generation API
// =============================================================================

export interface SpecTest {
  type: string;
  name: string;
  command?: string;
}

export interface SpecCapability {
  id: string;
  name: string;
  description?: string;
  tests: SpecTest[];
}

export interface SpecComponent {
  id: string;
  name: string;
  description?: string;
  priority?: number;
  capabilities: SpecCapability[];
}

export interface GeneratedSpec {
  components: SpecComponent[];
}

export interface GenerateSpecResponse {
  session_id: string;
  spec: GeneratedSpec;
  components_count: number;
  capabilities_count: number;
  tests_count: number;
}

export interface AcceptSpecResponse {
  spec_id: number;
  components_created: number;
  capabilities_created: number;
  tests_created: number;
}

export async function generateSpecFromRoundtable(
  projectId: string,
  sessionId: string,
  agent: "claude" | "gemini" = "gemini"
): Promise<GenerateSpecResponse> {
  return fetchWithGenerationTimeout(
    buildRoundtableGenerationUrl(projectId, sessionId, "generate-spec"),
    { agent_type: agent },
    "Failed to generate spec"
  );
}

export async function getSpecFromRoundtable(
  projectId: string,
  sessionId: string
): Promise<{ session_id: string; spec: GeneratedSpec | null }> {
  const res = await fetch(
    `${getApiBase()}/api/projects/${projectId}/roundtable/sessions/${sessionId}/spec`
  );
  if (!res.ok) throw new Error("Failed to get spec");
  return res.json();
}

export async function acceptSpecFromRoundtable(
  projectId: string,
  sessionId: string,
  acceptedBy: string = "user"
): Promise<AcceptSpecResponse> {
  return roundtableSessionAction(
    projectId, sessionId, "accept-spec",
    { accepted_by: acceptedBy },
    "Failed to accept spec"
  );
}

// =============================================================================
// Extraction Prompts API
// =============================================================================

export type ExtractionPromptType =
  | "feature_extraction"
  | "vision_extraction"
  | "goals_extraction";

export interface ExtractionPrompt {
  prompt_type: ExtractionPromptType;
  prompt_text: string;
  primary_agent: "claude" | "gemini";
  primary_model: string;
  is_default: boolean;
  created_at: string | null;
  updated_at: string | null;
}

export interface ExtractionPromptUpdate {
  prompt_text: string;
  primary_agent?: "claude" | "gemini";
  primary_model?: string;
}

export interface ExtractionPromptsExport {
  project_id: string;
  exported_at: string;
  prompts: ExtractionPrompt[];
}

export async function getExtractionPrompts(
  projectId: string
): Promise<ExtractionPrompt[]> {
  const res = await fetch(
    `${getApiBase()}/api/projects/${projectId}/roundtable/extraction-prompts`
  );
  if (!res.ok) throw new Error("Failed to fetch extraction prompts");
  return res.json();
}

export async function getExtractionPrompt(
  projectId: string,
  promptType: ExtractionPromptType
): Promise<ExtractionPrompt> {
  const res = await fetch(
    `${getApiBase()}/api/projects/${projectId}/roundtable/extraction-prompts/${promptType}`
  );
  if (!res.ok) throw new Error("Failed to fetch extraction prompt");
  return res.json();
}

export async function updateExtractionPrompt(
  projectId: string,
  promptType: ExtractionPromptType,
  config: ExtractionPromptUpdate
): Promise<ExtractionPrompt> {
  const res = await fetch(
    `${getApiBase()}/api/projects/${projectId}/roundtable/extraction-prompts/${promptType}`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        prompt_text: config.prompt_text,
        primary_agent: config.primary_agent ?? "claude",
        primary_model: config.primary_model ?? "claude-sonnet-4-5",
      }),
    }
  );
  if (!res.ok) throw new Error("Failed to update extraction prompt");
  return res.json();
}

export async function deleteExtractionPrompt(
  projectId: string,
  promptType: ExtractionPromptType
): Promise<{ deleted: boolean; reverted_to_default: boolean; prompt_type: string }> {
  const res = await fetch(
    `${getApiBase()}/api/projects/${projectId}/roundtable/extraction-prompts/${promptType}`,
    { method: "DELETE" }
  );
  if (!res.ok) throw new Error("Failed to delete extraction prompt");
  return res.json();
}

export async function exportExtractionPrompts(
  projectId: string,
  format: "json" = "json"
): Promise<ExtractionPromptsExport> {
  const res = await fetch(
    `${getApiBase()}/api/projects/${projectId}/roundtable/extraction-prompts/export?format=${format}`
  );
  if (!res.ok) throw new Error("Failed to export extraction prompts");
  return res.json();
}

// =============================================================================
// TDD Tests API
// =============================================================================

export interface TddTest {
  id: number;
  project_id: string;
  test_id: string;
  name: string;
  test_type: string;
  command: string | null;
  script: string | null;
  config: Record<string, unknown>;
  working_dir: string | null;
  timeout_seconds: number;
  last_run_at: string | null;
  last_result: string | null;
  last_duration_ms: number | null;
  last_output: string | null;
  last_error: string | null;
  run_count: number;
  pass_count: number;
  fail_count: number;
  flaky_score: number;
  created_at: string | null;
  updated_at: string | null;
}

export interface TddTestRunHistory {
  id: number;
  test_id: number;
  run_type: string;
  result: string;
  duration_ms: number;
  output: string | null;
  error: string | null;
  evidence_path: string | null;
  triggered_by: string | null;
  created_at: string | null;
}

export interface TddTestLinkedCapability {
  id: number;
  capability_id: string;
  name: string;
  status: string;
  is_primary: boolean;
}

export interface TddTestWithHistory extends TddTest {
  run_history: TddTestRunHistory[];
  linked_capabilities: TddTestLinkedCapability[];
}

export interface TestRunResult {
  test_id: string;
  result: string;
  duration_ms: number;
  output: string | null;
  error: string | null;
}

export interface ImportTestsResult {
  imported_count: number;
  skipped_count: number;
  tests: TddTest[];
  errors: string[];
}

export async function fetchTddTests(
  projectId: string,
  type?: string
): Promise<TddTest[]> {
  const params = new URLSearchParams();
  if (type) params.append("type", type);

  const queryString = params.toString();
  const res = await fetch(
    `${getApiBase()}/api/projects/${projectId}/tests${queryString ? `?${queryString}` : ""}`
  );
  if (!res.ok) throw new Error("Failed to fetch tests");
  return res.json();
}

export async function fetchTddTest(
  projectId: string,
  testId: string
): Promise<TddTestWithHistory> {
  const res = await fetch(`${getApiBase()}/api/projects/${projectId}/tests/${testId}`);
  if (!res.ok) throw new Error("Failed to fetch test");
  return res.json();
}

export async function runTddTest(
  projectId: string,
  testId: string
): Promise<TestRunResult> {
  const res = await fetch(`${getApiBase()}/api/projects/${projectId}/tests/${testId}/run`, {
    method: "POST",
  });
  if (!res.ok) throw new Error("Failed to run test");
  return res.json();
}

export async function runTddTests(
  projectId: string,
  options: { testIds?: string[]; tier?: string }
): Promise<TestRunResult[]> {
  const res = await fetch(`${getApiBase()}/api/projects/${projectId}/tests/run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      test_ids: options.testIds,
      tier: options.tier,
    }),
  });
  if (!res.ok) throw new Error("Failed to run tests");
  return res.json();
}

export async function importTddTests(
  projectId: string,
  sourceType: string = "all",
  discover: boolean = true
): Promise<ImportTestsResult> {
  const res = await fetch(`${getApiBase()}/api/projects/${projectId}/tests/import`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      source_type: sourceType,
      discover,
    }),
  });
  if (!res.ok) throw new Error("Failed to import tests");
  return res.json();
}

// =============================================================================
// TDD Components API
// =============================================================================

export interface TddComponent {
  id: number;
  project_id: string;
  component_id: string;
  name: string;
  description: string | null;
  priority: number;
  status: string;
  created_at: string | null;
  updated_at: string | null;
}

export interface TddCapability {
  id: number;
  project_id: string;
  component_id: number;
  capability_id: string;
  name: string;
  description: string | null;
  priority: number;
  status: string;
  locked_at: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface TddCapabilityWithTests extends TddCapability {
  tests: {
    id: number;
    test_id: string;
    name: string;
    test_type: string;
    last_result: string | null;
    is_primary: boolean;
  }[];
}

export async function fetchTddComponents(projectId: string): Promise<TddComponent[]> {
  const res = await fetch(`${getApiBase()}/api/projects/${projectId}/components`);
  if (!res.ok) throw new Error("Failed to fetch components");
  return res.json();
}

export interface ComponentSuggestion {
  suggested_name: string;
  type: "page_group" | "endpoint_group" | "directory";
  path: string;
  entry_count: number;
  entries: { id: number; path: string }[];
}

export async function fetchComponentSuggestions(
  projectId: string,
  source: string
): Promise<ComponentSuggestion[]> {
  const res = await fetch(
    `${getApiBase()}/api/projects/${projectId}/tdd/component-suggestions?source=${source}`
  );
  if (!res.ok) throw new Error("Failed to fetch component suggestions");
  return res.json();
}

export interface CreateComponentRequest {
  component_id: string;
  name: string;
  description?: string;
  priority?: number;
  explorer_entry_id?: number;
}

export async function createTddComponent(
  projectId: string,
  component: CreateComponentRequest
): Promise<TddComponent> {
  const res = await fetch(`${getApiBase()}/api/projects/${projectId}/components`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(component),
  });
  if (!res.ok) {
    const error = await res.json().catch(() => ({}));
    throw new Error(error.detail || "Failed to create component");
  }
  return res.json();
}

export async function fetchTddComponent(
  projectId: string,
  componentId: string
): Promise<TddComponent> {
  const res = await fetch(`${getApiBase()}/api/projects/${projectId}/components/${componentId}`);
  if (!res.ok) throw new Error("Failed to fetch component");
  return res.json();
}

export async function fetchTddCapabilities(
  projectId: string,
  componentDbId?: number
): Promise<TddCapability[]> {
  const params = new URLSearchParams();
  if (componentDbId !== undefined) params.append("component", componentDbId.toString());

  const queryString = params.toString();
  const res = await fetch(
    `${getApiBase()}/api/projects/${projectId}/capabilities${queryString ? `?${queryString}` : ""}`
  );
  if (!res.ok) throw new Error("Failed to fetch capabilities");
  return res.json();
}

export async function fetchTddCapability(
  projectId: string,
  capabilityId: string
): Promise<TddCapabilityWithTests> {
  const res = await fetch(`${getApiBase()}/api/projects/${projectId}/capabilities/${capabilityId}`);
  if (!res.ok) throw new Error("Failed to fetch capability");
  return res.json();
}

export async function lockTddCapability(
  projectId: string,
  capabilityId: string
): Promise<TddCapability> {
  const res = await fetch(
    `${getApiBase()}/api/projects/${projectId}/capabilities/${capabilityId}/lock`,
    { method: "POST" }
  );
  if (!res.ok) throw new Error("Failed to lock capability");
  return res.json();
}

// Re-export Prompts API
export * from "./api/prompts";
