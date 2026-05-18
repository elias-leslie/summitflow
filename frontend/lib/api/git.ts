/**
 * Git management API functions.
 */

import { getApiBaseUrl } from '../api-config'
import { fetchWithErrorHandling } from './utils'

export interface RepoWorkspaceSummary {
  active_checkpoints: number
  dirty_checkpoints: number
  dirty_main_repo?: boolean
  branches_with_checkpoints: number
  orphan_branches: number
  prunable_branches: number
  needs_cleanup: boolean
  checkpoint_task_ids: string[]
  orphan_branch_names?: string[]
  prunable_branch_names?: string[]
  salvage_task_ids?: string[]
  review_orphan_task_ids?: string[]
  orphan_details?: OrphanBranchSummary[]
}

export interface OrphanBranchSummary {
  branch_name: string
  task_id: string
  resolution: string
  task_status?: string | null
  commits_ahead: number
  commits_behind?: number
  files_changed: number
  has_node_modules_artifact: boolean
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

export interface GitCleanupSummary {
  repos: number
  repos_needing_cleanup: number
  active_checkpoints: number
  dirty_checkpoints: number
  stale_checkpoints: number
  snapshot_residue: number
}

export interface GitCleanupRepository {
  project_id: string
  path: string
  active_checkpoints: number
  dirty_checkpoints: number
  dirty_main_repo?: boolean
  stale_checkpoints: number
  snapshot_residue: number
  needs_merge_count: number
  conflict_count: number
  review_count: number
  orphan_details?: OrphanBranchSummary[]
  needs_cleanup: boolean
}

export interface GitCleanupPayload {
  summary: GitCleanupSummary
  repositories: GitCleanupRepository[]
  checkpoints: Array<{
    task_id: string
    base_branch: string
    project_id?: string | null
  }>
  total: number
}

export interface GitCleanupStatusResponse {
  payload: GitCleanupPayload
  compact: string
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
 * Fetch remote refs for all managed repositories without merging.
 */
export async function checkGitRemotes(): Promise<GitSyncResponse> {
  return fetchWithErrorHandling<GitSyncResponse>(
    `${getApiBaseUrl()}/api/git/fetch`,
    {
      method: 'POST',
      errorMessage: 'Failed to check remote git status',
    },
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

/**
 * Fetch remote refs for a specific project's repository without merging.
 */
export async function checkProjectGitRemote(
  projectId: string,
): Promise<GitSyncResponse> {
  return fetchWithErrorHandling<GitSyncResponse>(
    `${getApiBaseUrl()}/api/projects/${projectId}/git/fetch`,
    {
      method: 'POST',
      errorMessage: 'Failed to check project git remote',
    },
  )
}

export interface ProjectPublishResponse {
  success: boolean
  status: string
  gates: string
  errors: string[]
  message: string
  reason: string
  pushed: boolean
  raw_output: string
}

export async function publishProjectChanges(
  projectId: string,
): Promise<ProjectPublishResponse> {
  return fetchWithErrorHandling<ProjectPublishResponse>(
    `${getApiBaseUrl()}/api/projects/${projectId}/git/publish`,
    {
      method: 'POST',
      errorMessage: 'Failed to publish project changes',
    },
  )
}
