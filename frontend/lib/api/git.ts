/**
 * Git management API functions.
 */

import { getApiBaseUrl } from '../api-config'
import { fetchWithErrorHandling } from './utils'

export interface RepoWorkspaceSummary {
  active_worktrees: number
  dirty_worktrees: number
  branches_with_worktrees: number
  task_branches: number
  orphan_branches: number
  prunable_branches: number
  needs_cleanup: boolean
  worktree_task_ids: string[]
  orphan_branch_names?: string[]
  prunable_branch_names?: string[]
  salvage_task_ids?: string[]
  review_orphan_task_ids?: string[]
}

export interface RepoStatus {
  path: string
  name: string
  project_id?: string | null
  branch: string
  uncommitted: number
  ahead: number
  behind: number
  state: 'clean' | 'dirty' | 'behind' | 'ahead'
  workspace_summary?: RepoWorkspaceSummary | null
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
    `${getApiBaseUrl()}/api/git/status`,
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
    `${getApiBaseUrl()}/api/projects/${projectId}/git/status`,
    { errorMessage: 'Failed to fetch project git status' },
  )
}

/**
 * Pull changes for a specific project's repository.
 */
export async function pullRepository(
  projectId: string,
): Promise<GitSyncResponse> {
  return fetchWithErrorHandling<GitSyncResponse>(
    `${getApiBaseUrl()}/api/projects/${projectId}/git/pull`,
    {
      method: 'POST',
      errorMessage: 'Failed to pull repository',
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

export async function smartSyncProject(
  projectId: string,
): Promise<SmartSyncResponse> {
  return fetchWithErrorHandling<SmartSyncResponse>(
    `${getApiBaseUrl()}/api/projects/${projectId}/git/smart-sync`,
    {
      method: 'POST',
      errorMessage: 'Failed to smart sync project',
    },
  )
}
