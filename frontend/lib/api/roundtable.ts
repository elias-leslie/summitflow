import { buildQueryString, fetchWithErrorHandling, getApiBase } from "./utils";
import { fetchWithGenerationTimeout, roundtableSessionAction, buildRoundtableGenerationUrl } from "./wrappers";

// =============================================================================
// Roundtable Types
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

export interface AgentConfigUpdate {
  agent_override: string | null;
  model_override: string | null;
}

export interface AgentConfigResponse {
  agent_override: string | null;
  model_override: string | null;
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
    message?: string;
    permission_id?: string;
    tool_name?: string;
    params?: Record<string, unknown>;
    preview?: string;
  };
}

export interface PermissionRequest {
  permission_id: string;
  tool_name: string;
  params: Record<string, unknown>;
  preview?: string;
  agent: "claude" | "gemini";
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

// =============================================================================
// Roundtable Session API
// =============================================================================

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
  const query = buildQueryString({ status });
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

export async function updateRoundtableAgentConfig(
  projectId: string,
  sessionId: string,
  config: AgentConfigUpdate
): Promise<AgentConfigResponse> {
  return fetchWithErrorHandling(
    `/api/projects/${projectId}/roundtable/sessions/${sessionId}/agent-config`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(config),
      errorMessage: "Failed to update agent config",
    }
  );
}

export async function resolvePermission(
  projectId: string,
  sessionId: string,
  permissionId: string,
  approved: boolean
): Promise<void> {
  await fetchWithErrorHandling(
    `/api/projects/${projectId}/roundtable/sessions/${sessionId}/permissions/${permissionId}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ approved }),
      errorMessage: "Failed to resolve permission",
    }
  );
}

// =============================================================================
// Roundtable Streaming
// =============================================================================

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

      const events = buffer.split("\n\n");
      buffer = events.pop() || "";

      for (const eventBlock of events) {
        if (!eventBlock.trim()) continue;

        const lines = eventBlock.split("\n");
        let eventType: RoundtableSSEEventType = "done";
        let eventData: Record<string, unknown> = {};

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

// =============================================================================
// Roundtable Generation
// =============================================================================

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
