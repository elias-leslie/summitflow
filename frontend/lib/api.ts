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

export async function deleteProject(id: string): Promise<void> {
  const res = await fetch(`${getApiBase()}/api/projects/${id}`, {
    method: "DELETE",
  });
  if (!res.ok) throw new Error("Failed to delete project");
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
    featureId: string;
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
  featureId: string;
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
  featureId: string,
  criterionId: string,
  version?: number,
  includeEvidence = true
): Promise<ArtifactResponse> {
  const params = new URLSearchParams();
  params.append("include_evidence", includeEvidence.toString());
  if (version) params.append("version", version.toString());

  const res = await fetch(
    `${getApiBase()}/api/projects/${projectId}/evidence/${featureId}/${criterionId}?${params}`
  );
  if (!res.ok) {
    if (res.status === 404) throw new Error("No evidence captured yet");
    throw new Error("Failed to fetch evidence");
  }
  return res.json();
}

export async function refreshEvidence(
  projectId: string,
  featureId: string,
  criterionId: string,
  url: string
): Promise<{ success: boolean; version?: number; error?: string }> {
  const res = await fetch(`${getApiBase()}/api/projects/${projectId}/evidence/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ feature_id: featureId, criterion_id: criterionId, url }),
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

export function getScreenshotUrl(projectId: string, featureId: string, criterionId: string, version: number): string {
  return `${getApiBase()}/api/projects/${projectId}/evidence/${featureId}/${criterionId}/screenshot?version=${version}`;
}

// ============================================================================
// Feature Types
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

export interface Feature {
  id: number | null;
  project_id: string;
  feature_id: string;
  name: string;
  category: string | null;
  description: string | null;
  layers: string[];
  layer_results: Record<string, { passed: boolean; evidence?: string }>;
  total_tasks: number;
  completed_tasks: number;
  completion_pct: number;
  health_status: string;
  status?: "backlog" | "in_progress" | "review" | "done";
  last_verified_at: string | null;
  created_at: string | null;
  updated_at: string | null;
  priority: number | null;
  effective_priority: number;
  acceptance_criteria: AcceptanceCriterion[];
  vision_goals: string[];
}

export interface FeaturesListResponse {
  features: Feature[];
  total: number;
  filtered: number;
}

export interface FeatureSummary {
  total: number;
  category_breakdown: Record<string, number>;
  health_breakdown: Record<string, number>;
}

export interface VerificationSummary {
  total_criteria: number;
  passed: number;
  failed: number;
  pending: number;
  by_type: Record<string, { total: number; passed: number; failed: number; pending: number }>;
  last_run_at: string | null;
}

// ============================================================================
// Feature API Functions
// ============================================================================

export async function fetchFeatures(
  projectId: string,
  options: {
    category?: string;
    health_status?: string;
    limit?: number;
    offset?: number;
  } = {}
): Promise<FeaturesListResponse> {
  const params = new URLSearchParams();
  if (options.category) params.append("category", options.category);
  if (options.health_status) params.append("health_status", options.health_status);
  if (options.limit) params.append("limit", options.limit.toString());
  if (options.offset) params.append("offset", options.offset.toString());

  const queryString = params.toString();
  const res = await fetch(
    `${getApiBase()}/api/projects/${projectId}/features${queryString ? `?${queryString}` : ""}`
  );
  if (!res.ok) throw new Error("Failed to fetch features");
  return res.json();
}

export async function fetchFeatureSummary(projectId: string): Promise<FeatureSummary> {
  const res = await fetch(`${getApiBase()}/api/projects/${projectId}/features/summary`);
  if (!res.ok) throw new Error("Failed to fetch feature summary");
  return res.json();
}

export async function fetchVerificationSummary(projectId: string): Promise<VerificationSummary> {
  const res = await fetch(`${getApiBase()}/api/projects/${projectId}/features/verification-summary`);
  if (!res.ok) throw new Error("Failed to fetch verification summary");
  return res.json();
}

export type FeatureStatus = "backlog" | "in_progress" | "review" | "done";

export async function updateFeatureStatus(
  projectId: string,
  featureId: string,
  status: FeatureStatus
): Promise<{ status: string; work_status: FeatureStatus }> {
  const res = await fetch(`${getApiBase()}/api/projects/${projectId}/features/${featureId}/status`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status }),
  });
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: "Failed to update feature status" }));
    throw new Error(error.detail || "Failed to update feature status");
  }
  return res.json();
}

// ============================================================================
// Feature Tasks
// ============================================================================

export interface FeatureTask {
  id: string;
  title: string;
  status: "pending" | "running" | "paused" | "completed" | "failed";
  started_at: string | null;
  completed_at: string | null;
  duration_seconds: number | null;
}

export async function fetchFeatureTasks(
  projectId: string,
  featureId: string
): Promise<FeatureTask[]> {
  const res = await fetch(
    `${getApiBase()}/api/projects/${projectId}/features/${featureId}/tasks`
  );
  if (!res.ok) throw new Error("Failed to fetch feature tasks");
  return res.json();
}

// ============================================================================
// Vision Types
// ============================================================================

export interface VisionGoal {
  code: string;
  name: string;
  description: string | null;
  category: string | null;
  feature_count: number;
  criteria_total: number;
  criteria_passed: number;
  pass_rate: number;
}

export interface FeatureLink {
  feature_id: string;
  name: string;
  criteria_total: number;
  criteria_passed: number;
}

export interface VisionGoalDetail extends VisionGoal {
  features: FeatureLink[];
}

export interface VisionContentItem {
  id: number;
  content_type: string;
  content_key: string;
  title: string | null;
  content: string;
  order_num: number;
  metadata: Record<string, unknown> | null;
}

export interface VisionContentResponse {
  content_types: string[];
  content: Record<string, VisionContentItem[]>;
}

export interface GoalDetail {
  id: number;
  goal_code: string;
  detail_type: string;
  content: string;
  order_num: number;
  metadata: Record<string, unknown> | null;
}

// ============================================================================
// Vision API Functions
// ============================================================================

export async function fetchVisionGoals(projectId: string): Promise<VisionGoal[]> {
  const res = await fetch(`${getApiBase()}/api/projects/${projectId}/vision-goals`);
  if (!res.ok) throw new Error("Failed to fetch vision goals");
  return res.json();
}

export async function fetchVisionGoal(projectId: string, code: string): Promise<VisionGoalDetail> {
  const res = await fetch(`${getApiBase()}/api/projects/${projectId}/vision-goals/${code}`);
  if (!res.ok) throw new Error("Failed to fetch vision goal");
  return res.json();
}

export async function fetchVisionGoalDetails(projectId: string, code: string): Promise<GoalDetail[]> {
  const res = await fetch(`${getApiBase()}/api/projects/${projectId}/vision-goals/${code}/details`);
  if (!res.ok) {
    // Goal details may not exist - return empty array
    if (res.status === 404) return [];
    throw new Error("Failed to fetch vision goal details");
  }
  return res.json();
}

export async function fetchVisionContent(projectId: string): Promise<VisionContentResponse> {
  const res = await fetch(`${getApiBase()}/api/projects/${projectId}/vision`);
  if (!res.ok) throw new Error("Failed to fetch vision content");
  return res.json();
}


// ============================================================================
// Beads Types (Issue Tracking)
// ============================================================================

export interface Bead {
  id: string;
  title: string;
  description: string | null;
  notes: string | null;
  status: "open" | "in_progress" | "closed";
  priority: number;
  issue_type: string;
  labels: string[] | null;
  created_at: string | null;
  updated_at: string | null;
  closed_at: string | null;
  dependency_count: number | null;
  dependent_count: number | null;
}

export interface BeadsListResponse {
  beads: Bead[];
  total: number;
  stats: {
    total: number;
    open: number;
    closed: number;
    in_progress: number;
    by_priority: Record<number, number>;
    by_type: Record<string, number>;
  };
}

export interface BeadStatsResponse {
  total: number;
  open: number;
  closed: number;
  in_progress: number;
  by_priority: Record<number, number>;
  by_type: Record<string, number>;
}

// ============================================================================
// Beads API Functions
// ============================================================================

export async function fetchBeads(
  projectId: string,
  status?: "all" | "open" | "closed",
  limit = 100
): Promise<BeadsListResponse> {
  const params = new URLSearchParams();
  if (status) params.append("status", status);
  params.append("limit", limit.toString());

  const queryString = params.toString();
  const res = await fetch(
    `${getApiBase()}/api/projects/${projectId}/beads${queryString ? `?${queryString}` : ""}`
  );
  if (!res.ok) throw new Error("Failed to fetch beads");
  return res.json();
}

export async function fetchReadyBeads(projectId: string): Promise<BeadsListResponse> {
  const res = await fetch(`${getApiBase()}/api/projects/${projectId}/beads/ready`);
  if (!res.ok) throw new Error("Failed to fetch ready beads");
  return res.json();
}

export async function fetchBeadStats(projectId: string): Promise<BeadStatsResponse> {
  const res = await fetch(`${getApiBase()}/api/projects/${projectId}/beads/stats`);
  if (!res.ok) throw new Error("Failed to fetch bead stats");
  return res.json();
}

export async function fetchBead(projectId: string, beadId: string): Promise<Bead> {
  const res = await fetch(`${getApiBase()}/api/projects/${projectId}/beads/${beadId}`);
  if (!res.ok) throw new Error("Failed to fetch bead");
  return res.json();
}

export async function createBead(
  projectId: string,
  bead: {
    title: string;
    description?: string;
    priority?: number;
    issue_type?: string;
    labels?: string[];
  }
): Promise<Bead> {
  const res = await fetch(`${getApiBase()}/api/projects/${projectId}/beads`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(bead),
  });
  if (!res.ok) throw new Error("Failed to create bead");
  return res.json();
}

export async function updateBead(
  projectId: string,
  beadId: string,
  updates: {
    status?: string;
    priority?: number;
    title?: string;
    notes?: string;
    labels?: string[];
  }
): Promise<Bead> {
  const res = await fetch(`${getApiBase()}/api/projects/${projectId}/beads/${beadId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(updates),
  });
  if (!res.ok) throw new Error("Failed to update bead");
  return res.json();
}

export async function closeBead(
  projectId: string,
  beadId: string,
  reason: string
): Promise<Bead> {
  const res = await fetch(`${getApiBase()}/api/projects/${projectId}/beads/${beadId}/close`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ reason }),
  });
  if (!res.ok) throw new Error("Failed to close bead");
  return res.json();
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

export interface FeatureContext {
  id: number;
  feature_id: string;
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
  feature_id: number | null;
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
  // Optional feature context (when fetched with include=feature)
  feature?: FeatureContext | null;
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
    feature_id?: number;
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

export async function fetchTaskDependencies(projectId: string, taskId: string): Promise<TaskDependency[]> {
  const res = await fetch(`${getApiBase()}/api/projects/${projectId}/tasks/${taskId}/dependencies`);
  if (!res.ok) throw new Error("Failed to fetch dependencies");
  return res.json();
}

export async function addTaskDependency(
  projectId: string,
  taskId: string,
  dependsOnTaskId: string,
  dependencyType: "blocks" | "discovered-from" = "blocks"
): Promise<TaskDependency> {
  const res = await fetch(`${getApiBase()}/api/projects/${projectId}/tasks/${taskId}/dependencies`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ depends_on_task_id: dependsOnTaskId, dependency_type: dependencyType }),
  });
  if (!res.ok) throw new Error("Failed to add dependency");
  return res.json();
}

export async function removeTaskDependency(
  projectId: string,
  taskId: string,
  dependsOnTaskId: string
): Promise<void> {
  const res = await fetch(
    `${getApiBase()}/api/projects/${projectId}/tasks/${taskId}/dependencies/${dependsOnTaskId}`,
    { method: "DELETE" }
  );
  if (!res.ok) throw new Error("Failed to remove dependency");
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

export async function dismissAllNotifications(projectId: string): Promise<{ dismissed: number }> {
  const res = await fetch(`${getApiBase()}/api/projects/${projectId}/notifications/dismiss-all`, {
    method: "POST",
  });
  if (!res.ok) throw new Error("Failed to dismiss all notifications");
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
  feature_id: string;
  name: string;
  category: string;
  priority: number;
  description?: string;
  acceptance_criteria: { id: string; description: string }[];
}

export interface SendMessageResponse {
  user_message: RoundtableMessage;
  responses: RoundtableMessage[];
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

export interface UpdateSessionRequest {
  title?: string;
  status?: "active" | "archived";
  agentMode?: "claude" | "gemini" | "both";
}

export interface UpdateSessionResponse {
  id: string;
  project_id: string;
  title: string | null;
  status: "active" | "archived";
  agent_mode: "claude" | "gemini" | "both";
  updated_at: string;
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
  const url = new URL(`${getApiBase()}/api/projects/${projectId}/roundtable/sessions`);
  if (status) {
    url.searchParams.set("status", status);
  }
  const res = await fetch(url.toString());
  if (!res.ok) throw new Error("Failed to list roundtable sessions");
  return res.json();
}

export async function updateRoundtableSession(
  projectId: string,
  sessionId: string,
  updates: UpdateSessionRequest
): Promise<UpdateSessionResponse> {
  const body: Record<string, unknown> = {};
  if (updates.title !== undefined) body.title = updates.title;
  if (updates.status !== undefined) body.status = updates.status;
  if (updates.agentMode !== undefined) body.agent_mode = updates.agentMode;

  const res = await fetch(
    `${getApiBase()}/api/projects/${projectId}/roundtable/sessions/${sessionId}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }
  );
  if (!res.ok) throw new Error("Failed to update roundtable session");
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

export async function sendRoundtableMessage(
  projectId: string,
  sessionId: string,
  message: string,
  target: "claude" | "gemini" | "both" = "both"
): Promise<SendMessageResponse> {
  // Use AbortController for timeout - AI responses can take 60+ seconds
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 120000); // 2 minute timeout

  try {
    const res = await fetch(
      `${getApiBase()}/api/projects/${projectId}/roundtable/sessions/${sessionId}/messages`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message, target }),
        signal: controller.signal,
      }
    );
    if (!res.ok) throw new Error("Failed to send roundtable message");
    return res.json();
  } finally {
    clearTimeout(timeoutId);
  }
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
