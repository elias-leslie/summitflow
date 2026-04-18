/**
 * Enhanced Git API client — conflicts, diffs, commits, snapshots.
 */

import { getApiBaseUrl } from '../api-config'
import { buildQueryString, fetchWithErrorHandling } from './utils'

// --- Conflict Types ---

export interface ConflictInfo {
  task_id: string
  task_title: string
  project_id: string
  conflicting_files: string[]
  task_branch: string
  base_branch: string
  detected_at: string
  error_output?: string
}

export interface ConflictsResponse {
  conflicts: ConflictInfo[]
  count: number
}

// --- Diff Types ---

export interface DiffFile {
  path: string
  status: string
  additions: number
  deletions: number
  diff_content: string
}

export interface DiffStats {
  files_changed: number
  additions: number
  deletions: number
}

export interface TaskDiffResponse {
  task_id: string
  task_title: string
  pre_merge_sha: string | null
  merge_sha: string | null
  files: DiffFile[]
  stats: DiffStats
}

export interface MergedTaskSummary {
  task_id: string
  task_title: string
  project_id: string
  merged_at: string
  files_changed: number
  additions: number
  deletions: number
}

// --- Commit Types ---

export interface CommitInfo {
  sha: string
  short_sha: string
  message: string
  author_name: string
  author_email: string
  date: string
  repo_name: string
  files_changed: number
  insertions: number
  deletions: number
}

// --- Snapshot Types ---

export interface SnapshotInfo {
  task_id: string
  task_title: string
  sha: string
  short_sha: string
  created_at: string
  project_id: string
  repo_name: string
  is_current: boolean
  commits_ahead: number
}

// --- Checkpoint Types ---

export interface CheckpointInfo {
  task_id: string
  branch: string
  base_branch: string
  is_active: boolean
  project_id?: string
}

export interface BranchInfo {
  name: string
  is_current: boolean
  has_checkpoint: boolean
  repo_name?: string | null
  project_id?: string | null
  task_id?: string | null
  last_commit_short?: string | null
  last_commit_date?: string | null
}

// --- Project Dashboard Types ---

export interface ProjectDashboardResponse {
  checkpoints: CheckpointInfo[]
  branches: BranchInfo[]
  recent_merges: MergedTaskSummary[]
  recent_commits: CommitInfo[]
  snapshots: SnapshotInfo[]
  conflicts: ConflictInfo[]
}

// --- Project Dashboard API ---

export async function fetchProjectDashboard(
  projectId: string,
  commitsLimit = 15,
): Promise<ProjectDashboardResponse> {
  return fetchWithErrorHandling<ProjectDashboardResponse>(
    `${getApiBaseUrl()}/api/git/projects/${projectId}/dashboard?commits_limit=${commitsLimit}`,
    { errorMessage: 'Failed to fetch project dashboard' },
  )
}

// --- Conflict API ---

export async function fetchConflicts(
  projectId?: string,
): Promise<ConflictsResponse> {
  return fetchWithErrorHandling<ConflictsResponse>(
    `${getApiBaseUrl()}/api/git/conflicts${buildQueryString({ project_id: projectId })}`,
    { errorMessage: 'Failed to fetch conflicts' },
  )
}

export async function retryMerge(
  taskId: string,
): Promise<Record<string, unknown>> {
  return fetchWithErrorHandling<Record<string, unknown>>(
    `${getApiBaseUrl()}/api/git/tasks/${taskId}/retry-merge`,
    { method: 'POST', errorMessage: 'Failed to retry merge' },
  )
}

export async function dismissConflict(
  taskId: string,
): Promise<{ status: string }> {
  return fetchWithErrorHandling<{ status: string }>(
    `${getApiBaseUrl()}/api/git/tasks/${taskId}/dismiss-conflict`,
    { method: 'POST', errorMessage: 'Failed to dismiss conflict' },
  )
}

// --- Diff / Merge Review API ---

export async function fetchTaskDiff(taskId: string): Promise<TaskDiffResponse> {
  return fetchWithErrorHandling<TaskDiffResponse>(
    `${getApiBaseUrl()}/api/tasks/${taskId}/diff`,
    { errorMessage: 'Failed to fetch task diff' },
  )
}

// --- Single Commit Diff API ---

export async function fetchCommitDiff(
  sha: string,
  projectId?: string,
): Promise<TaskDiffResponse> {
  return fetchWithErrorHandling<TaskDiffResponse>(
    `${getApiBaseUrl()}/api/git/commits/${sha}/diff${buildQueryString({ project_id: projectId })}`,
    { errorMessage: 'Failed to fetch commit diff' },
  )
}

export async function revertToSnapshot(
  taskId: string,
): Promise<{ status: string; reverted_to: string }> {
  return fetchWithErrorHandling<{ status: string; reverted_to: string }>(
    `${getApiBaseUrl()}/api/git/snapshots/${taskId}/revert`,
    { method: 'POST', errorMessage: 'Failed to revert to snapshot' },
  )
}
