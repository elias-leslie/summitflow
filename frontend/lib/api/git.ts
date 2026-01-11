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
