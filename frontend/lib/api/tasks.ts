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
  priority: number;
  labels: string[];
  task_type: TaskType;
  parent_task_id: string | null;
  capability?: CapabilityContext | null;
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
