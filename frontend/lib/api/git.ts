/**
 * Git management API functions.
 */

import { fetchWithErrorHandling, getApiBase } from "./utils";

export interface RepoStatus {
  path: string;
  name: string;
  branch: string;
  uncommitted: number;
  ahead: number;
  behind: number;
  state: "clean" | "dirty" | "behind" | "ahead";
}

export interface GitStatusResponse {
  repositories: RepoStatus[];
  total: number;
}

export interface SyncResult {
  path: string;
  name: string;
  branch: string;
  status: "up_to_date" | "updated" | "skipped" | "failed";
  reason?: string;
  error?: string;
}

export interface GitSyncResponse {
  results: SyncResult[];
  success: number;
  failed: number;
  skipped: number;
}

export interface WorktreeInfo {
  task_id: string;
  project_id: string;
  branch: string;
  path: string;
  commit_count: number;
  files_changed: number;
  additions: number;
  deletions: number;
}

export interface WorktreesResponse {
  worktrees: WorktreeInfo[];
  total: number;
}

/**
 * Get git status for all managed repositories.
 */
export async function fetchGitStatus(): Promise<GitStatusResponse> {
  return fetchWithErrorHandling<GitStatusResponse>(
    `${getApiBase()}/api/git/status`,
    { errorMessage: "Failed to fetch git status" },
  );
}

/**
 * Sync all repositories (pull from remote).
 */
export async function syncRepositories(): Promise<GitSyncResponse> {
  return fetchWithErrorHandling<GitSyncResponse>(
    `${getApiBase()}/api/git/sync`,
    {
      method: "POST",
      errorMessage: "Failed to sync repositories",
    },
  );
}

/**
 * Get worktrees for a project.
 */
export async function fetchWorktrees(
  projectId: string,
): Promise<WorktreesResponse> {
  return fetchWithErrorHandling<WorktreesResponse>(
    `${getApiBase()}/api/projects/${projectId}/worktrees`,
    { errorMessage: "Failed to fetch worktrees" },
  );
}

/**
 * Delete a worktree.
 */
export async function deleteWorktree(
  projectId: string,
  taskId: string,
): Promise<void> {
  await fetchWithErrorHandling<{ success: boolean }>(
    `${getApiBase()}/api/projects/${projectId}/worktrees/${taskId}`,
    {
      method: "DELETE",
      errorMessage: "Failed to delete worktree",
    },
  );
}

export interface WorktreeDiffResponse {
  task_id: string;
  files: Array<{ status: string; path: string }>;
  diff: string;
  commit_count: number;
  additions: number;
  deletions: number;
}

/**
 * Get diff for a worktree.
 */
export async function fetchWorktreeDiff(
  projectId: string,
  taskId: string,
): Promise<WorktreeDiffResponse> {
  return fetchWithErrorHandling<WorktreeDiffResponse>(
    `${getApiBase()}/api/projects/${projectId}/worktrees/${taskId}/diff`,
    { errorMessage: "Failed to fetch worktree diff" },
  );
}

export interface MergeResponse {
  success: boolean;
  message: string;
  task_id: string;
}

/**
 * Merge a worktree's branch to main.
 */
export async function mergeWorktree(
  projectId: string,
  taskId: string,
  deleteAfter: boolean = true,
): Promise<MergeResponse> {
  return fetchWithErrorHandling<MergeResponse>(
    `${getApiBase()}/api/projects/${projectId}/worktrees/${taskId}/merge`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ delete_after: deleteAfter }),
      errorMessage: "Failed to merge worktree",
    },
  );
}

export interface PushResponse {
  success: boolean;
  message: string;
  task_id: string;
  branch: string;
}

/**
 * Push a worktree's branch to remote.
 */
export async function pushWorktree(
  projectId: string,
  taskId: string,
): Promise<PushResponse> {
  return fetchWithErrorHandling<PushResponse>(
    `${getApiBase()}/api/projects/${projectId}/worktrees/${taskId}/push`,
    {
      method: "POST",
      errorMessage: "Failed to push worktree",
    },
  );
}

export interface PRCreateRequest {
  title?: string;
  body?: string;
}

export interface PRCreateResponse {
  pr_url: string;
  branch_name: string;
  task_id: string;
}

/**
 * Create a pull request for a task.
 */
export async function createPullRequest(
  taskId: string,
  request?: PRCreateRequest,
): Promise<PRCreateResponse> {
  return fetchWithErrorHandling<PRCreateResponse>(
    `${getApiBase()}/api/tasks/${taskId}/pr`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request ?? {}),
      errorMessage: "Failed to create pull request",
    },
  );
}

export interface CleanupResponse {
  removed: Array<{
    project_id: string;
    task_id: string;
    path: string;
    age_days: number;
    last_modified: string;
  }>;
  would_remove: Array<{
    project_id: string;
    task_id: string;
    path: string;
    age_days: number;
    last_modified: string;
  }>;
  dry_run: boolean;
}

/**
 * Cleanup old worktrees.
 */
export async function cleanupWorktrees(
  projectId: string,
  maxAgeDays: number = 30,
  dryRun: boolean = true,
): Promise<CleanupResponse> {
  return fetchWithErrorHandling<CleanupResponse>(
    `${getApiBase()}/api/projects/${projectId}/worktrees/cleanup`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ max_age_days: maxAgeDays, dry_run: dryRun }),
      errorMessage: "Failed to cleanup worktrees",
    },
  );
}
