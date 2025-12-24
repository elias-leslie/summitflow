// API Base URL - always empty to use relative URLs
// Next.js rewrites proxy /api/* to backend (works for both SSR and client-side)
// Build: 2025-12-17-v6
function getApiBase(): string {
  return "";
}

export interface Project {
  id: string;
  name: string;
  base_url: string;
  health_endpoint: string;
  created_at: string;
  health_status?: string;
  root_path?: string;
}

export interface ProjectStats {
  features: number;
  tasks: number;
  bugs: number;
  blocked: number;
}

export interface ProjectWithStats {
  id: string;
  name: string;
  base_url: string;
  health_endpoint: string;
  root_path?: string;
  logo_url?: string;
  created_at: string;
  health_status?: string;
  stats: ProjectStats;
}

export interface ProjectsWithStatsResponse {
  projects: ProjectWithStats[];
  total: number;
}

export interface ProjectHealth {
  project_id: string;
  healthy: boolean;
  status_code?: number;
  response_time_ms?: number;
  error?: string;
  checked_at: string;
}

export async function fetchProjects(): Promise<Project[]> {
  const res = await fetch(`${getApiBase()}/api/projects`);
  if (!res.ok) throw new Error("Failed to fetch projects");
  return res.json();
}

export async function fetchProjectsWithStats(): Promise<ProjectsWithStatsResponse> {
  const res = await fetch(`${getApiBase()}/api/projects/with-stats`);
  if (!res.ok) throw new Error("Failed to fetch projects with stats");
  return res.json();
}

export async function fetchProject(id: string): Promise<Project> {
  const res = await fetch(`${getApiBase()}/api/projects/${id}`);
  if (!res.ok) throw new Error("Failed to fetch project");
  return res.json();
}

export async function fetchProjectHealth(id: string): Promise<ProjectHealth> {
  const res = await fetch(`${getApiBase()}/api/projects/${id}/health`);
  if (!res.ok) throw new Error("Failed to check project health");
  return res.json();
}

export async function createProject(project: {
  id: string;
  name: string;
  base_url: string;
  health_endpoint?: string;
}): Promise<Project> {
  const res = await fetch(`${getApiBase()}/api/projects`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(project),
  });
  if (!res.ok) {
    const error = await res.json();
    throw new Error(error.detail || "Failed to create project");
  }
  return res.json();
}

// ============================================================================
// Common Types (used by Explorer)
// ============================================================================

export type HealthStatus = "healthy" | "warning" | "error" | "unknown";

// ============================================================================
// Evidence Types
// ============================================================================

export interface Evidence {
  metadata: {
    url: string;
    capabilityId: string;
    criterionId: string;
    version: number;
    capturedAt: string;
    pageTitle: string;
    viewport: { width: number; height: number };
    captureTimeMs: number;
  };
  console: {
    errorCount: number;
    warningCount: number;
    errors: Array<{ text: string; source: string | null }>;
    warnings: Array<{ text: string; source: string | null }>;
  };
  network: {
    totalRequests: number;
    failedRequests: number;
    failures: Array<{ url: string; status: number | string; error?: string }>;
    slowRequests: Array<{ url: string; durationMs: number }>;
  };
  pageState: {
    hasContent: boolean;
    visibleTextSample: string;
    keyElements: {
      tables: number;
      charts: number;
      buttons: number;
      errorMessages: number;
      loadingSpinners: number;
      emptyStates: number;
    };
  };
  performance: {
    pageLoadMs: number | null;
    domContentLoadedMs: number | null;
    largestContentfulPaintMs: number | null;
  };
}

export interface Artifact {
  id: number;
  artifactId: string;
  capabilityId: string;
  criterionId: string;
  version: number;
  isCurrent: boolean;
  capturedAt: string;
  expiresAt: string;
  qualityStatus: string;
  confidence: number | null;
  userApproved: boolean | null;
  userNotes: string | null;
  fileSizeBytes: number;
}

export interface ArtifactResponse {
  artifact: Artifact;
  versions: Artifact[];
  evidence: Evidence | null;
  screenshotUrl: string;
  evidenceUrl: string;
}

// ============================================================================
// Evidence API Functions
// ============================================================================

export async function fetchEvidence(
  projectId: string,
  capabilityId: string,
  criterionId: string,
  version?: number,
  includeEvidence = true
): Promise<ArtifactResponse> {
  const params = new URLSearchParams();
  params.append("include_evidence", includeEvidence.toString());
  if (version) params.append("version", version.toString());

  const res = await fetch(
    `${getApiBase()}/api/projects/${projectId}/evidence/${capabilityId}/${criterionId}?${params}`
  );
  if (!res.ok) {
    if (res.status === 404) throw new Error("No evidence captured yet");
    throw new Error("Failed to fetch evidence");
  }
  return res.json();
}

export async function refreshEvidence(
  projectId: string,
  capabilityId: string,
  criterionId: string,
  url: string
): Promise<{ success: boolean; version?: number; error?: string }> {
  const res = await fetch(`${getApiBase()}/api/projects/${projectId}/evidence/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ capability_id: capabilityId, criterion_id: criterionId, url }),
  });
  if (!res.ok) throw new Error("Failed to refresh evidence");
  return res.json();
}

export async function submitEvidenceReview(
  projectId: string,
  evidenceId: string,
  approved: boolean | null,
  notes?: string
): Promise<{ success: boolean }> {
  const res = await fetch(`${getApiBase()}/api/projects/${projectId}/evidence/${evidenceId}/review`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ approved, notes }),
  });
  if (!res.ok) throw new Error("Failed to submit review");
  return res.json();
}

export function getScreenshotUrl(projectId: string, capabilityId: string, criterionId: string, version: number): string {
  return `${getApiBase()}/api/projects/${projectId}/evidence/${capabilityId}/${criterionId}/screenshot?version=${version}`;
}

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

// ============================================================================
// Task Types
// ============================================================================

export type TaskStatus = "pending" | "running" | "paused" | "completed" | "failed";
export type TaskType = "feature" | "bug" | "task";

export interface TaskAcceptanceCriterion {
  id: string;
  description: string;
  passes: boolean;
}

export interface CapabilityContext {
  id: number;
  capability_id: string;
  name: string;
  criteria_passed: number;
  criteria_total: number;
  acceptance_criteria?: TaskAcceptanceCriterion[] | null;
}

export interface BlockerInfo {
  id: string;
  title: string;
  status: string;
  priority: number;
}

export interface Task {
  id: string;
  project_id: string;
  capability_id: number | null;
  title: string;
  description: string | null;
  status: TaskStatus;
  current_criterion_id: string | null;
  spec_content: string | null;
  plan_content: Record<string, unknown> | null;
  progress_log: string | null;
  error_message: string | null;
  branch_name: string | null;
  commits: string[];
  pull_request_url: string | null;
  total_sessions: number;
  total_tokens_used: number;
  created_at: string | null;
  started_at: string | null;
  completed_at: string | null;
  // Issue tracking fields
  priority: number;
  labels: string[];
  task_type: TaskType;
  parent_task_id: string | null;
  // Optional capability context (when fetched with include=capability)
  capability?: CapabilityContext | null;
  // Optional blocker context (when fetched with include=blockers)
  blockers?: BlockerInfo[] | null;
  blocked_by_incomplete?: boolean | null;
}

export interface TaskListResponse {
  tasks: Task[];
  total: number;
}

export interface TaskDependency {
  id: number;
  task_id: string;
  depends_on_task_id: string;
  dependency_type: string;
  created_at: string | null;
  depends_on_title?: string;
  depends_on_status?: string;
}

// ============================================================================
// Task API Functions
// ============================================================================

export async function createTask(
  projectId: string,
  task: {
    title: string;
    description?: string;
    capability_id?: number;
    priority?: number;
    labels?: string[];
    task_type?: TaskType;
    parent_task_id?: string;
  }
): Promise<Task> {
  const res = await fetch(`${getApiBase()}/api/projects/${projectId}/tasks`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(task),
  });
  if (!res.ok) {
    const error = await res.json();
    throw new Error(error.detail || "Failed to create task");
  }
  return res.json();
}

export async function fetchTasks(
  projectId: string,
  options: {
    status?: TaskStatus;
    type?: TaskType;
    priority?: number;
    labels?: string;
    include?: string;
    limit?: number;
    offset?: number;
  } = {}
): Promise<TaskListResponse> {
  const params = new URLSearchParams();
  if (options.status) params.append("status", options.status);
  if (options.type) params.append("type", options.type);
  if (options.priority !== undefined) params.append("priority", options.priority.toString());
  if (options.labels) params.append("labels", options.labels);
  if (options.include) params.append("include", options.include);
  if (options.limit) params.append("limit", options.limit.toString());
  if (options.offset) params.append("offset", options.offset.toString());

  const queryString = params.toString();
  const res = await fetch(
    `${getApiBase()}/api/projects/${projectId}/tasks${queryString ? `?${queryString}` : ""}`
  );
  if (!res.ok) throw new Error("Failed to fetch tasks");
  return res.json();
}

export async function fetchReadyTasks(projectId: string, limit = 50): Promise<TaskListResponse> {
  const res = await fetch(`${getApiBase()}/api/projects/${projectId}/tasks/ready?limit=${limit}`);
  if (!res.ok) throw new Error("Failed to fetch ready tasks");
  return res.json();
}

export async function fetchBlockedTasks(projectId: string, limit = 50): Promise<TaskListResponse> {
  const res = await fetch(`${getApiBase()}/api/projects/${projectId}/tasks/blocked?limit=${limit}`);
  if (!res.ok) throw new Error("Failed to fetch blocked tasks");
  return res.json();
}

export async function updateTask(
  projectId: string,
  taskId: string,
  updates: {
    title?: string;
    description?: string;
    priority?: number;
    labels?: string[];
    task_type?: TaskType;
    parent_task_id?: string;
  }
): Promise<Task> {
  const res = await fetch(`${getApiBase()}/api/projects/${projectId}/tasks/${taskId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(updates),
  });
  if (!res.ok) {
    const error = await res.json();
    throw new Error(error.detail || "Failed to update task");
  }
  return res.json();
}

export async function fetchTask(projectId: string, taskId: string): Promise<Task> {
  const res = await fetch(`${getApiBase()}/api/projects/${projectId}/tasks/${taskId}`);
  if (!res.ok) throw new Error("Failed to fetch task");
  return res.json();
}

export type AgentType = "claude" | "gemini";

export interface StartTaskResult {
  status: string;
  task_id: string;
  celery_task_id?: string;
}

export async function startTask(
  projectId: string,
  taskId: string,
  options: {
    agent_type: AgentType;
    model?: string;
    allow_delegation?: boolean;
  }
): Promise<StartTaskResult> {
  const res = await fetch(`${getApiBase()}/api/projects/${projectId}/tasks/${taskId}/start`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(options),
  });
  if (!res.ok) {
    const error = await res.json();
    throw new Error(error.detail || "Failed to start task");
  }
  return res.json();
}

export async function updateTaskStatus(
  projectId: string,
  taskId: string,
  status: TaskStatus,
  errorMessage?: string
): Promise<Task> {
  const res = await fetch(`${getApiBase()}/api/projects/${projectId}/tasks/${taskId}/status`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status, error_message: errorMessage }),
  });
  if (!res.ok) {
    const error = await res.json();
    throw new Error(error.detail || "Failed to update task status");
  }
  return res.json();
}

// ============================================================================
// Notifications
// ============================================================================

export interface Notification {
  id: string;
  project_id: string;
  task_id: string | null;
  type: "task_failed" | "task_needs_input" | "task_completed" | "system";
  title: string;
  message: string;
  severity: "info" | "warning" | "error" | "critical";
  status: "pending" | "read" | "dismissed";
  metadata: Record<string, unknown>;
  created_at: string | null;
  read_at: string | null;
  dismissed_at: string | null;
}

export interface NotificationListResponse {
  items: Notification[];
  total: number;
  pending_count: number;
}

export async function fetchNotifications(
  projectId: string,
  options: { status?: string; limit?: number; offset?: number; include_dismissed?: boolean } = {}
): Promise<NotificationListResponse> {
  const params = new URLSearchParams();
  if (options.status) params.append("status", options.status);
  if (options.limit) params.append("limit", options.limit.toString());
  if (options.offset) params.append("offset", options.offset.toString());
  if (options.include_dismissed) params.append("include_dismissed", "true");

  const queryString = params.toString();
  const res = await fetch(
    `${getApiBase()}/api/projects/${projectId}/notifications${queryString ? `?${queryString}` : ""}`
  );
  if (!res.ok) throw new Error("Failed to fetch notifications");
  return res.json();
}

export async function fetchNotificationCount(projectId: string): Promise<number> {
  const res = await fetch(`${getApiBase()}/api/projects/${projectId}/notifications/count`);
  if (!res.ok) throw new Error("Failed to fetch notification count");
  const data = await res.json();
  return data.pending;
}

export async function markNotificationRead(projectId: string, notificationId: string): Promise<Notification> {
  const res = await fetch(
    `${getApiBase()}/api/projects/${projectId}/notifications/${notificationId}/read`,
    { method: "PATCH" }
  );
  if (!res.ok) throw new Error("Failed to mark notification as read");
  return res.json();
}

export async function dismissNotification(projectId: string, notificationId: string): Promise<Notification> {
  const res = await fetch(
    `${getApiBase()}/api/projects/${projectId}/notifications/${notificationId}/dismiss`,
    { method: "PATCH" }
  );
  if (!res.ok) throw new Error("Failed to dismiss notification");
  return res.json();
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

  const res = await fetch(`${getApiBase()}/api/projects/${projectId}/roundtable/sessions`, {
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
  });
  if (!res.ok) throw new Error("Failed to create roundtable session");
  return res.json();
}

export async function listRoundtableSessions(
  projectId: string,
  status?: "active" | "archived"
): Promise<RoundtableSessionInfo[]> {
  const params = status ? `?status=${status}` : "";
  const res = await fetch(
    `${getApiBase()}/api/projects/${projectId}/roundtable/sessions${params}`
  );
  if (!res.ok) throw new Error("Failed to list roundtable sessions");
  return res.json();
}

export async function getRoundtableSession(projectId: string, sessionId: string): Promise<RoundtableSession> {
  const res = await fetch(`${getApiBase()}/api/projects/${projectId}/roundtable/sessions/${sessionId}`);
  if (!res.ok) throw new Error("Failed to get roundtable session");
  return res.json();
}

export async function deleteRoundtableSession(projectId: string, sessionId: string): Promise<void> {
  const res = await fetch(`${getApiBase()}/api/projects/${projectId}/roundtable/sessions/${sessionId}`, {
    method: "DELETE",
  });
  if (!res.ok) throw new Error("Failed to delete roundtable session");
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

  const res = await fetch(
    `${getApiBase()}/api/projects/${projectId}/roundtable/sessions/${sessionId}/tools`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }
  );
  if (!res.ok) throw new Error("Failed to update roundtable tools");
  return res.json();
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
  // Use AbortController for timeout - feature extraction can take time
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 120000); // 2 minute timeout

  try {
    const res = await fetch(
      `${getApiBase()}/api/projects/${projectId}/roundtable/sessions/${sessionId}/generate-features`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ agent }),
        signal: controller.signal,
      }
    );
    if (!res.ok) throw new Error("Failed to generate features from roundtable");
    return res.json();
  } finally {
    clearTimeout(timeoutId);
  }
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
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 120000);

  try {
    const res = await fetch(
      `${getApiBase()}/api/projects/${projectId}/roundtable/sessions/${sessionId}/generate-vision`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ agent }),
        signal: controller.signal,
      }
    );
    if (!res.ok) throw new Error("Failed to generate vision from roundtable");
    return res.json();
  } finally {
    clearTimeout(timeoutId);
  }
}

export async function saveVisionFromRoundtable(
  projectId: string,
  sessionId: string,
  mission: GeneratedMission | null,
  narratives: GeneratedNarrative[]
): Promise<{ status: string; project_id: string }> {
  const res = await fetch(
    `${getApiBase()}/api/projects/${projectId}/roundtable/sessions/${sessionId}/save-vision`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mission, narratives }),
    }
  );
  if (!res.ok) throw new Error("Failed to save vision");
  return res.json();
}

export async function generateGoalsFromRoundtable(
  projectId: string,
  sessionId: string,
  agent: "claude" | "gemini" = "claude"
): Promise<GenerateGoalsResponse> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 120000);

  try {
    const res = await fetch(
      `${getApiBase()}/api/projects/${projectId}/roundtable/sessions/${sessionId}/generate-goals`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ agent }),
        signal: controller.signal,
      }
    );
    if (!res.ok) throw new Error("Failed to generate goals from roundtable");
    return res.json();
  } finally {
    clearTimeout(timeoutId);
  }
}

export async function saveGoalsFromRoundtable(
  projectId: string,
  sessionId: string,
  goals: GeneratedGoal[]
): Promise<{ status: string; project_id: string; goals_created: number }> {
  const res = await fetch(
    `${getApiBase()}/api/projects/${projectId}/roundtable/sessions/${sessionId}/save-goals`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ goals }),
    }
  );
  if (!res.ok) throw new Error("Failed to save goals");
  return res.json();
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
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 120000); // 2 min timeout

  try {
    const res = await fetch(
      `${getApiBase()}/api/projects/${projectId}/roundtable/sessions/${sessionId}/generate-spec`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ agent_type: agent }),
        signal: controller.signal,
      }
    );
    if (!res.ok) throw new Error("Failed to generate spec");
    return res.json();
  } finally {
    clearTimeout(timeoutId);
  }
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
  const res = await fetch(
    `${getApiBase()}/api/projects/${projectId}/roundtable/sessions/${sessionId}/accept-spec`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ accepted_by: acceptedBy }),
    }
  );
  if (!res.ok) throw new Error("Failed to accept spec");
  return res.json();
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
  verification_enabled: boolean;
  verification_agent: "claude" | "gemini" | null;
  verification_model: string | null;
  verification_prompt: string | null;
  is_default: boolean;
  created_at: string | null;
  updated_at: string | null;
}

export interface ExtractionPromptUpdate {
  prompt_text: string;
  primary_agent?: "claude" | "gemini";
  primary_model?: string;
  verification_enabled?: boolean;
  verification_agent?: "claude" | "gemini" | null;
  verification_model?: string | null;
  verification_prompt?: string | null;
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
        verification_enabled: config.verification_enabled ?? false,
        verification_agent: config.verification_agent ?? null,
        verification_model: config.verification_model ?? null,
        verification_prompt: config.verification_prompt ?? null,
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

// ============================================================================
// Unified Prompts API
// ============================================================================

export type PromptCategory = "spec" | "recovery" | "qa" | "extraction";

export interface Prompt {
  prompt_type: string;
  prompt_text: string;
  primary_agent: string;
  primary_model: string;
  verification_enabled: boolean;
  verification_agent: string | null;
  verification_model: string | null;
  verification_prompt: string | null;
  category: PromptCategory;
  thinking_budget: number;
  tools_enabled: string[];
  is_default: boolean;
  created_at: string | null;
  updated_at: string | null;
}

export interface PromptsExport {
  project_id: string;
  exported_at: string;
  prompts: Prompt[];
}

export interface PromptUpdate {
  prompt_text: string;
  primary_agent?: string;
  primary_model?: string;
  verification_enabled?: boolean;
  verification_agent?: string | null;
  verification_model?: string | null;
  verification_prompt?: string | null;
  category?: PromptCategory;
  thinking_budget?: number;
  tools_enabled?: string[];
}

export async function fetchPrompts(
  projectId: string,
  category?: PromptCategory
): Promise<Prompt[]> {
  const url = category
    ? `${getApiBase()}/api/projects/${projectId}/prompts?category=${category}`
    : `${getApiBase()}/api/projects/${projectId}/prompts`;
  const res = await fetch(url);
  if (!res.ok) throw new Error("Failed to fetch prompts");
  return res.json();
}

export async function fetchPrompt(
  projectId: string,
  promptType: string
): Promise<Prompt> {
  const res = await fetch(
    `${getApiBase()}/api/projects/${projectId}/prompts/${promptType}`
  );
  if (!res.ok) throw new Error("Failed to fetch prompt");
  return res.json();
}

export async function updatePrompt(
  projectId: string,
  promptType: string,
  config: PromptUpdate
): Promise<Prompt> {
  const res = await fetch(
    `${getApiBase()}/api/projects/${projectId}/prompts/${promptType}`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(config),
    }
  );
  if (!res.ok) throw new Error("Failed to update prompt");
  return res.json();
}

export async function deletePrompt(
  projectId: string,
  promptType: string
): Promise<{ deleted: boolean; reverted_to_default: boolean; prompt_type: string }> {
  const res = await fetch(
    `${getApiBase()}/api/projects/${projectId}/prompts/${promptType}`,
    { method: "DELETE" }
  );
  if (!res.ok) throw new Error("Failed to delete prompt");
  return res.json();
}

export async function exportPrompts(
  projectId: string,
  category?: PromptCategory
): Promise<PromptsExport> {
  const url = category
    ? `${getApiBase()}/api/projects/${projectId}/prompts/export?category=${category}`
    : `${getApiBase()}/api/projects/${projectId}/prompts/export`;
  const res = await fetch(url);
  if (!res.ok) throw new Error("Failed to export prompts");
  return res.json();
}

export async function importPrompts(
  projectId: string,
  prompts: PromptUpdate[]
): Promise<{ imported: number; updated: number; failed: number }> {
  const res = await fetch(
    `${getApiBase()}/api/projects/${projectId}/prompts/import`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompts }),
    }
  );
  if (!res.ok) throw new Error("Failed to import prompts");
  return res.json();
}
