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
  status: string
  reason?: string
  pushed?: boolean
  publication_complete: boolean
  evidence_recorded?: boolean
  requested_source_commit: string
  observed_at?: string
  head?: string
  ci?: { state?: string; optional_state?: string; requirements_state?: string }
  security?: { status?: string }
  delivery?: {
    uploaded_source: string | null
    pull_request_state: 'pending' | 'merged' | 'not_applicable'
    merged_source: string | null
    pull_request_url?: string | null
  }
}

export async function publishProjectChanges(
  projectId: string,
  sourceSha: string,
): Promise<ProjectPublishResponse> {
  return fetchWithErrorHandling<ProjectPublishResponse>(
    `${getApiBaseUrl()}/api/projects/${projectId}/git/publish`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ source_sha: sourceSha }),
      errorMessage: 'Failed to publish accepted source',
    },
  )
}

export interface DevelopmentEvidence {
  state: string
  source_commit: string | null
  observed_at: string | number | null
  evidence: string | null
  reason: string
  drift?: boolean
  full_coverage?: boolean
  check_count?: number
  uncommitted?: number
  unpublished?: number | null
  snapshot_id?: string | null
  runtime_health?: string
  publication_complete?: boolean
}

export interface DevelopmentProjection {
  version: 'development.v1'
  project_id: string
  observed_at: string
  working_tree: DevelopmentEvidence
  accepted: DevelopmentEvidence
  running: DevelopmentEvidence
  recovery: Record<
    'capture' | 'offsite' | 'snapshot' | 'restore',
    DevelopmentEvidence
  >
  publication: DevelopmentEvidence
  blockers: {
    state: string
    reason?: string
    items: Array<{
      task_id: string
      title: string
      status: string
      reason: string
    }>
  }
}

export interface DevelopmentStatusResponse {
  version: 'development.v1'
  repositories: Array<{ repo: RepoStatus; development: DevelopmentProjection }>
  total: number
  unavailable_repositories: Array<{
    path: string
    name: string
    reason: string
  }>
}

function object(value: unknown): Record<string, unknown> {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error('Development evidence is malformed')
  }
  return value as Record<string, unknown>
}

function decodeEvidence(value: unknown): DevelopmentEvidence {
  const row = object(value)
  if (
    typeof row.state !== 'string' ||
    typeof row.reason !== 'string' ||
    !(
      row.source_commit === null ||
      (typeof row.source_commit === 'string' &&
        /^(?:[0-9a-f]{40}|[0-9a-f]{64})$/.test(row.source_commit))
    ) ||
    !(row.evidence === null || typeof row.evidence === 'string') ||
    !(
      row.observed_at === null ||
      typeof row.observed_at === 'string' ||
      typeof row.observed_at === 'number'
    )
  )
    throw new Error('Development evidence is malformed')
  for (const key of ['drift', 'full_coverage', 'publication_complete']) {
    if (row[key] !== undefined && typeof row[key] !== 'boolean')
      throw new Error('Development evidence is malformed')
  }
  for (const key of ['snapshot_id', 'runtime_health']) {
    if (
      row[key] !== undefined &&
      row[key] !== null &&
      typeof row[key] !== 'string'
    )
      throw new Error('Development evidence is malformed')
  }
  for (const key of ['check_count', 'uncommitted', 'unpublished']) {
    if (
      row[key] !== undefined &&
      row[key] !== null &&
      typeof row[key] !== 'number'
    )
      throw new Error('Development evidence is malformed')
  }
  return row as unknown as DevelopmentEvidence
}

export function decodeDevelopmentProjection(
  value: unknown,
): DevelopmentProjection {
  const row = object(value)
  if (
    row.version !== 'development.v1' ||
    typeof row.project_id !== 'string' ||
    typeof row.observed_at !== 'string'
  ) {
    throw new Error('Unsupported development evidence')
  }
  const recovery = object(row.recovery)
  const blockers = object(row.blockers)
  if (typeof blockers.state !== 'string' || !Array.isArray(blockers.items))
    throw new Error('Task evidence is malformed')
  const items = blockers.items.map((item: unknown) => {
    const task = object(item)
    if (
      ['task_id', 'title', 'status', 'reason'].some(
        (key) => typeof task[key] !== 'string',
      )
    )
      throw new Error('Task evidence is malformed')
    return task as unknown as DevelopmentProjection['blockers']['items'][number]
  })
  return {
    version: row.version,
    project_id: row.project_id,
    observed_at: row.observed_at,
    working_tree: decodeEvidence(row.working_tree),
    accepted: decodeEvidence(row.accepted),
    running: decodeEvidence(row.running),
    publication: decodeEvidence(row.publication),
    recovery: {
      capture: decodeEvidence(recovery.capture),
      offsite: decodeEvidence(recovery.offsite),
      snapshot: decodeEvidence(recovery.snapshot),
      restore: decodeEvidence(recovery.restore),
    },
    blockers: {
      state: blockers.state,
      reason: typeof blockers.reason === 'string' ? blockers.reason : undefined,
      items,
    },
  }
}

export async function fetchProjectDevelopmentStatus(
  projectId: string,
): Promise<DevelopmentProjection> {
  const value = await fetchWithErrorHandling<unknown>(
    `${getApiBaseUrl()}/api/projects/${projectId}/development/status`,
    { errorMessage: 'Could not load development evidence' },
  )
  return decodeDevelopmentProjection(value)
}

export async function fetchDevelopmentStatus(): Promise<DevelopmentStatusResponse> {
  const value = object(
    await fetchWithErrorHandling<unknown>(
      `${getApiBaseUrl()}/api/development/status`,
      { errorMessage: 'Could not load development evidence' },
    ),
  )
  if (
    value.version !== 'development.v1' ||
    !Array.isArray(value.repositories) ||
    typeof value.total !== 'number'
  )
    throw new Error('Unsupported development evidence')
  return {
    version: value.version,
    total: value.total,
    unavailable_repositories: Array.isArray(value.unavailable_repositories)
      ? value.unavailable_repositories.map((item: unknown) => {
          const row = object(item)
          if (
            ['path', 'name', 'reason'].some(
              (key) => typeof row[key] !== 'string',
            )
          )
            throw new Error('Repository evidence is malformed')
          return row as unknown as DevelopmentStatusResponse['unavailable_repositories'][number]
        })
      : [],
    repositories: value.repositories.map((item: unknown) => {
      const row = object(item)
      const repo = object(row.repo)
      if (
        ['path', 'name', 'branch'].some(
          (key) => typeof repo[key] !== 'string',
        ) ||
        ['uncommitted', 'ahead', 'behind'].some(
          (key) => typeof repo[key] !== 'number',
        )
      )
        throw new Error('Repository evidence is malformed')
      return {
        repo: repo as unknown as RepoStatus,
        development: decodeDevelopmentProjection(row.development),
      }
    }),
  }
}
