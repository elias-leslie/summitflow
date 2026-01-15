/**
 * Tasks API - CRUD operations for task management
 */

import { fetchWithErrorHandling, buildQueryString, getApiBase } from "./utils";

// ============================================================================
// Task Types
// ============================================================================

export type TaskStatus =
  | "pending"
  | "running"
  | "paused"
  | "blocked"
  | "pr_created"
  | "ai_reviewing"
  | "human_review"
  | "completed"
  | "failed"
  | "cancelled";
export type TaskType = "feature" | "bug" | "task";
export type AgentType = "claude" | "gemini";

export interface TaskAcceptanceCriterion {
  id: string;
  criterion_id?: string;
  criterion: string;
  category?: "performance" | "correctness" | "security" | "quality";
  measurement?: string;
  threshold?: string | null;
  verify_command?: string | null;
  verify_by?: "test" | "opus" | "human" | "agent";
  expected_output?: string | null;
  test_file?: string | null;
  test_name?: string | null;
  verified: boolean;
  verified_at?: string | null;
  verified_by_who?: "opus" | "test" | "human" | "agent" | null;
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
  verification_result?: Record<string, unknown> | null;
  // Enrichment fields
  raw_request?: string | null;
  enrichment_status?: EnrichmentStatus | null;
  enriched_by?: string | null;
  enriched_at?: string | null;
  // Autonomous execution flag
  autonomous?: boolean;
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
  },
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
  } = {},
): Promise<TaskListResponse> {
  const query = buildQueryString(options);
  return fetchWithErrorHandling(`/api/projects/${projectId}/tasks${query}`, {
    errorMessage: "Failed to fetch tasks",
  });
}

export async function fetchReadyTasks(
  projectId: string,
  limit = 50,
): Promise<TaskListResponse> {
  return fetchWithErrorHandling(
    `/api/projects/${projectId}/tasks/ready?limit=${limit}`,
    {
      errorMessage: "Failed to fetch ready tasks",
    },
  );
}

export async function fetchBlockedTasks(
  projectId: string,
  limit = 50,
): Promise<TaskListResponse> {
  return fetchWithErrorHandling(
    `/api/projects/${projectId}/tasks/blocked?limit=${limit}`,
    {
      errorMessage: "Failed to fetch blocked tasks",
    },
  );
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
    autonomous?: boolean;
  },
): Promise<Task> {
  return fetchWithErrorHandling(`/api/projects/${projectId}/tasks/${taskId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(updates),
    errorMessage: "Failed to update task",
  });
}

export async function fetchTask(
  projectId: string,
  taskId: string,
): Promise<Task> {
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
  },
): Promise<StartTaskResult> {
  return fetchWithErrorHandling(
    `${getApiBase()}/api/projects/${projectId}/tasks/${taskId}/start`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(options),
      errorMessage: "Failed to start task",
    },
  );
}

export async function updateTaskStatus(
  projectId: string,
  taskId: string,
  status: TaskStatus,
  taskErrorMessage?: string,
): Promise<Task> {
  return fetchWithErrorHandling(
    `${getApiBase()}/api/projects/${projectId}/tasks/${taskId}/status`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status, error_message: taskErrorMessage }),
      errorMessage: "Failed to update task status",
    },
  );
}

// ============================================================================
// Autonomous Execution
// ============================================================================

export interface ExecuteTaskOptions {
  model?: string;
}

export interface ExecuteTaskResponse {
  execution_id: string;
  task_id: string;
  status: string;
}

/**
 * Start autonomous orchestrator execution for a task.
 * Queues the task for execution via Celery with streaming to WebSocket.
 */
export async function executeTask(
  projectId: string,
  taskId: string,
  options?: ExecuteTaskOptions,
): Promise<ExecuteTaskResponse> {
  return fetchWithErrorHandling(
    `${getApiBase()}/api/projects/${projectId}/tasks/${taskId}/execute`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(options || {}),
      errorMessage: "Failed to start task execution",
    },
  );
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
  items: BatchTaskCreateItem[],
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
  | "accepted"
  | "failed";

export interface Step {
  id: number;
  subtask_id: string;
  step_number: number;
  description: string;
  spec: Record<string, unknown> | null;
  passes: boolean;
  passed_at: string | null;
  created_at: string | null;
}

export interface StepSummary {
  total: number;
  completed: number;
  progress_percent: number;
}

export interface Subtask {
  id: string;
  task_id: string;
  subtask_id: string;
  phase: string;
  description: string;
  steps: string[]; // JSONB array (legacy)
  steps_from_table?: Step[]; // Normalized table steps (when include_steps=true)
  step_summary?: StepSummary; // Step completion summary (when include_steps=true)
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
  sync = false,
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
  rawRequest: string,
): Promise<CleanupPromptResponse> {
  return fetchWithErrorHandling(
    `/api/projects/${projectId}/tasks/cleanup-prompt`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ raw_request: rawRequest }),
      errorMessage: "Failed to cleanup prompt",
    },
  );
}

/**
 * Send a message to discuss and refine a task with the AI.
 */
export async function discussTask(
  projectId: string,
  taskId: string,
  message: string,
): Promise<DiscussionResponse> {
  return fetchWithErrorHandling(
    `/api/projects/${projectId}/tasks/${taskId}/discuss`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message }),
      errorMessage: "Failed to discuss task",
    },
  );
}

/**
 * Accept an enriched task, moving it to 'pending' status for execution.
 */
export async function acceptTask(
  projectId: string,
  taskId: string,
): Promise<Task> {
  return fetchWithErrorHandling(
    `/api/projects/${projectId}/tasks/${taskId}/accept`,
    {
      method: "POST",
      errorMessage: "Failed to accept task",
    },
  );
}

/**
 * Get subtasks for a task.
 */
export async function getSubtasks(
  projectId: string,
  taskId: string,
): Promise<SubtasksResponse> {
  return fetchWithErrorHandling(
    `/api/projects/${projectId}/tasks/${taskId}/subtasks`,
    {
      errorMessage: "Failed to fetch subtasks",
    },
  );
}

/**
 * Update a subtask's passes status.
 */
export async function updateSubtask(
  projectId: string,
  taskId: string,
  subtaskId: string,
  passes: boolean,
): Promise<Subtask> {
  return fetchWithErrorHandling(
    `/api/projects/${projectId}/tasks/${taskId}/subtasks/${subtaskId}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ passes }),
      errorMessage: "Failed to update subtask",
    },
  );
}

// ============================================================================
// Step API Functions
// ============================================================================

/**
 * Get steps for a subtask from the normalized table.
 */
export async function getSteps(
  projectId: string,
  taskId: string,
  subtaskId: string,
): Promise<Step[]> {
  return fetchWithErrorHandling(
    `/api/projects/${projectId}/tasks/${taskId}/subtasks/${subtaskId}/steps`,
    {
      errorMessage: "Failed to fetch steps",
    },
  );
}

/**
 * Update a step's passes status.
 */
export async function updateStep(
  projectId: string,
  taskId: string,
  subtaskId: string,
  stepNumber: number,
  passes: boolean,
): Promise<Step> {
  return fetchWithErrorHandling(
    `/api/projects/${projectId}/tasks/${taskId}/subtasks/${subtaskId}/steps/${stepNumber}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ passes }),
      errorMessage: "Failed to update step",
    },
  );
}

/**
 * Get step completion summary for a subtask.
 */
export async function getStepSummary(
  projectId: string,
  taskId: string,
  subtaskId: string,
): Promise<StepSummary> {
  return fetchWithErrorHandling(
    `/api/projects/${projectId}/tasks/${taskId}/subtasks/${subtaskId}/steps/summary`,
    {
      errorMessage: "Failed to fetch step summary",
    },
  );
}

/**
 * Get subtasks with steps included.
 */
export async function getSubtasksWithSteps(
  projectId: string,
  taskId: string,
): Promise<SubtasksResponse> {
  return fetchWithErrorHandling(
    `/api/projects/${projectId}/tasks/${taskId}/subtasks?include_steps=true`,
    {
      errorMessage: "Failed to fetch subtasks with steps",
    },
  );
}

// ============================================================================
// Acceptance Criteria Functions
// ============================================================================

export interface CriterionVerifyRequest {
  verified?: boolean;
  verified_by: "test" | "opus" | "human" | "agent";
}

export interface CriterionVerifyResponse {
  status: string;
  task_id: string;
  criterion_id: string;
  verified_by: string;
}

/**
 * Get all acceptance criteria for a task.
 */
export async function getTaskCriteria(
  projectId: string,
  taskId: string,
): Promise<TaskAcceptanceCriterion[]> {
  return fetchWithErrorHandling(
    `/api/projects/${projectId}/tasks/${taskId}/criteria`,
    {
      errorMessage: "Failed to fetch task criteria",
    },
  );
}

/**
 * Verify (mark as passed/failed) a task criterion.
 */
export async function verifyTaskCriterion(
  projectId: string,
  taskId: string,
  criterionId: string,
  verifiedBy: "test" | "opus" | "human" | "agent" = "human",
  verified: boolean = true,
): Promise<CriterionVerifyResponse> {
  return fetchWithErrorHandling(
    `/api/projects/${projectId}/tasks/${taskId}/criteria/${criterionId}/verify`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ verified, verified_by: verifiedBy }),
      errorMessage: "Failed to verify criterion",
    },
  );
}
