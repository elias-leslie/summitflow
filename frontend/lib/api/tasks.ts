/**
 * Tasks API - CRUD operations for task management
 */

import { fetchWithErrorHandling, buildQueryString, getApiBase } from "./utils";

// ============================================================================
// Task Types
// ============================================================================

export type TaskStatus = "pending" | "running" | "paused" | "completed" | "failed";
export type TaskType = "feature" | "bug" | "task";
export type AgentType = "claude" | "gemini";

export interface TaskAcceptanceCriterion {
  id: string;
  criterion: string;
  category?: "performance" | "correctness" | "security" | "quality";
  measurement?: string;
  threshold?: string | null;
  test_file?: string | null;
  test_name?: string | null;
  verified: boolean;
  verified_at?: string | null;
  verified_by?: "opus" | "test" | "human" | null;
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
  priority: number;
  labels: string[];
  task_type: TaskType;
  parent_task_id: string | null;
  capability?: CapabilityContext | null;
  blockers?: BlockerInfo[] | null;
  blocked_by_incomplete?: boolean | null;
  // AI agent reliability fields
  objective?: string | null;
  acceptance_criteria?: TaskAcceptanceCriterion[] | null;
  current_phase?: "plan" | "implement" | "test" | "verify" | "complete" | null;
  // Enrichment fields
  raw_request?: string | null;
  enrichment_status?: "none" | "draft" | "enriching" | "review" | "discussing" | "accepted" | null;
  enriched_by?: string | null;
  enriched_at?: string | null;
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

export interface StartTaskResult {
  status: string;
  task_id: string;
  celery_task_id?: string;
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
  return fetchWithErrorHandling(`/api/projects/${projectId}/tasks`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(task),
    errorMessage: "Failed to create task",
  });
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
  const query = buildQueryString(options);
  return fetchWithErrorHandling(`/api/projects/${projectId}/tasks${query}`, {
    errorMessage: "Failed to fetch tasks",
  });
}

export async function fetchReadyTasks(projectId: string, limit = 50): Promise<TaskListResponse> {
  return fetchWithErrorHandling(`/api/projects/${projectId}/tasks/ready?limit=${limit}`, {
    errorMessage: "Failed to fetch ready tasks",
  });
}

export async function fetchBlockedTasks(projectId: string, limit = 50): Promise<TaskListResponse> {
  return fetchWithErrorHandling(`/api/projects/${projectId}/tasks/blocked?limit=${limit}`, {
    errorMessage: "Failed to fetch blocked tasks",
  });
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
  return fetchWithErrorHandling(`/api/projects/${projectId}/tasks/${taskId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(updates),
    errorMessage: "Failed to update task",
  });
}

export async function fetchTask(projectId: string, taskId: string): Promise<Task> {
  return fetchWithErrorHandling(`/api/projects/${projectId}/tasks/${taskId}`, {
    errorMessage: "Failed to fetch task",
  });
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
  return fetchWithErrorHandling(`${getApiBase()}/api/projects/${projectId}/tasks/${taskId}/start`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(options),
    errorMessage: "Failed to start task",
  });
}

export async function updateTaskStatus(
  projectId: string,
  taskId: string,
  status: TaskStatus,
  taskErrorMessage?: string
): Promise<Task> {
  return fetchWithErrorHandling(`${getApiBase()}/api/projects/${projectId}/tasks/${taskId}/status`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status, error_message: taskErrorMessage }),
    errorMessage: "Failed to update task status",
  });
}

// ============================================================================
// Batch Task Creation
// ============================================================================

export interface BatchTaskCreateItem {
  title: string;
  description?: string;
  capability_id?: number;
  priority?: number;
  labels?: string[];
  task_type?: TaskType;
  parent_task_id?: string;
  objective?: string;
}

export interface BatchTaskResult {
  title: string;
  success: boolean;
  id?: string;
  error?: string;
}

export interface BatchTaskResponse {
  created: Task[];
  errors: BatchTaskResult[];
}

export async function batchCreateTasks(
  projectId: string,
  items: BatchTaskCreateItem[]
): Promise<BatchTaskResponse> {
  return fetchWithErrorHandling(`/api/projects/${projectId}/tasks/batch`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ items }),
    errorMessage: "Failed to batch create tasks",
  });
}

// ============================================================================
// Enrichment Types
// ============================================================================

export type EnrichmentStatus =
  | "none"
  | "draft"
  | "enriching"
  | "review"
  | "discussing"
  | "accepted";

export interface Subtask {
  id: string;
  task_id: string;
  subtask_id: string;
  phase: string;
  description: string;
  steps: string[];
  passes: boolean;
  passed_at: string | null;
  display_order: number;
  created_at: string | null;
}

export interface SubtasksResponse {
  subtasks: Subtask[];
  total: number;
  completed: number;
  next_subtask_id: string | null;
}

export interface EnrichmentRequest {
  raw_request: string;
  priority?: number;
  task_type?: TaskType;
}

export interface CleanupPromptResponse {
  cleaned_prompt: string;
  changes_made: string[];
}

export interface DiscussionMessage {
  role: "user" | "assistant";
  content: string;
  timestamp: string;
}

export interface DiscussionResponse {
  response: string;
  updated_task: Task | null;
  history: DiscussionMessage[];
}

// ============================================================================
// Enrichment API Functions
// ============================================================================

/**
 * Enrich a task with AI-generated objective, criteria, and subtasks.
 * @param sync If true, runs enrichment synchronously and returns enriched task.
 *             If false (default), queues enrichment and returns task with status 'enriching'.
 */
export async function enrichTask(
  projectId: string,
  request: EnrichmentRequest,
  sync = false
): Promise<Task> {
  const url = `/api/projects/${projectId}/tasks/enrich${sync ? "?sync=true" : ""}`;
  return fetchWithErrorHandling(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
    errorMessage: "Failed to enrich task",
  });
}

/**
 * Clean up and refine a raw task prompt using AI.
 */
export async function cleanupPrompt(
  projectId: string,
  rawRequest: string
): Promise<CleanupPromptResponse> {
  return fetchWithErrorHandling(`/api/projects/${projectId}/tasks/cleanup-prompt`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ raw_request: rawRequest }),
    errorMessage: "Failed to cleanup prompt",
  });
}

/**
 * Send a message to discuss and refine a task with the AI.
 */
export async function discussTask(
  projectId: string,
  taskId: string,
  message: string
): Promise<DiscussionResponse> {
  return fetchWithErrorHandling(`/api/projects/${projectId}/tasks/${taskId}/discuss`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
    errorMessage: "Failed to discuss task",
  });
}

/**
 * Accept an enriched task, moving it to 'pending' status for execution.
 */
export async function acceptTask(projectId: string, taskId: string): Promise<Task> {
  return fetchWithErrorHandling(`/api/projects/${projectId}/tasks/${taskId}/accept`, {
    method: "POST",
    errorMessage: "Failed to accept task",
  });
}

/**
 * Get subtasks for a task.
 */
export async function getSubtasks(
  projectId: string,
  taskId: string
): Promise<SubtasksResponse> {
  return fetchWithErrorHandling(`/api/projects/${projectId}/tasks/${taskId}/subtasks`, {
    errorMessage: "Failed to fetch subtasks",
  });
}

/**
 * Update a subtask's passes status.
 */
export async function updateSubtask(
  projectId: string,
  taskId: string,
  subtaskId: string,
  passes: boolean
): Promise<Subtask> {
  return fetchWithErrorHandling(
    `/api/projects/${projectId}/tasks/${taskId}/subtasks/${subtaskId}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ passes }),
      errorMessage: "Failed to update subtask",
    }
  );
}
