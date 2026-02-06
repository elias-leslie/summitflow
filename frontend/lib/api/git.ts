/**
 * Git management API functions.
 */

import { fetchWithErrorHandling, getApiBase } from './utils'

export interface RepoStatus {
  path: string
  name: string
  branch: string
  uncommitted: number
  ahead: number
  behind: number
  state: 'clean' | 'dirty' | 'behind' | 'ahead'
}

export interface GitStatusResponse {
  repositories: RepoStatus[]
  total: number
}

export interface SyncResult {
  path: string
  name: string
  branch: string
  status: 'up_to_date' | 'updated' | 'skipped' | 'failed'
  reason?: string
  error?: string
}

export interface GitSyncResponse {
  results: SyncResult[]
  success: number
  failed: number
  skipped: number
}

/**
 * Get git status for all managed repositories.
 */
export async function fetchGitStatus(): Promise<GitStatusResponse> {
  return fetchWithErrorHandling<GitStatusResponse>(
    `${getApiBase()}/api/git/status`,
    { errorMessage: 'Failed to fetch git status' },
  )
}

/**
 * Get git status for a specific project.
 */
export async function fetchProjectGitStatus(
  projectId: string,
): Promise<GitStatusResponse> {
  return fetchWithErrorHandling<GitStatusResponse>(
    `${getApiBase()}/api/projects/${projectId}/git/status`,
    { errorMessage: 'Failed to fetch project git status' },
  )
}

/**
 * Sync all repositories (pull from remote).
 */
export async function syncRepositories(): Promise<GitSyncResponse> {
  return fetchWithErrorHandling<GitSyncResponse>(
    `${getApiBase()}/api/git/sync`,
    {
      method: 'POST',
      errorMessage: 'Failed to sync repositories',
    },
  )
}

export interface PRCreateRequest {
  title?: string
  body?: string
}

export interface PRCreateResponse {
  pr_url: string
  branch_name: string
  task_id: string
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
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request ?? {}),
      errorMessage: 'Failed to create pull request',
    },
  )
}

/**
 * Pull changes for a specific project's repository.
 */
export async function pullRepository(projectId: string): Promise<GitSyncResponse> {
  return fetchWithErrorHandling<GitSyncResponse>(
    `${getApiBase()}/api/projects/${projectId}/git/pull`,
    {
      method: 'POST',
      errorMessage: 'Failed to pull repository',
    },
  )
}

/**
 * Push changes for a specific project's repository.
 */
export async function pushRepository(projectId: string): Promise<GitSyncResponse> {
  return fetchWithErrorHandling<GitSyncResponse>(
    `${getApiBase()}/api/projects/${projectId}/git/push`,
    {
      method: 'POST',
      errorMessage: 'Failed to push repository',
    },
  )
}

/**
 * Fetch changes for a specific project's repository.
 */
export async function fetchRepository(projectId: string): Promise<GitSyncResponse> {
  return fetchWithErrorHandling<GitSyncResponse>(
    `${getApiBase()}/api/projects/${projectId}/git/fetch`,
    {
      method: 'POST',
      errorMessage: 'Failed to fetch repository',
    },
  )
}

export interface SmartSyncResponse {
  success: boolean
  status: string
  gates: string
  errors: string[]
  message: string
  reason: string
  pushed: boolean
  raw_output: string
}

export async function smartSyncProject(projectId: string): Promise<SmartSyncResponse> {
  return fetchWithErrorHandling<SmartSyncResponse>(
    `${getApiBase()}/api/projects/${projectId}/git/smart-sync`,
    {
      method: 'POST',
      errorMessage: 'Failed to smart sync project',
    },
  )
}
