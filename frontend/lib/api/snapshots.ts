import { buildQueryString, fetchWithErrorHandling, postJson } from './utils'

// ─── Types ──────────────────────────────────────────────────────

export interface BtrfsSnapshotUsage {
  total_bytes: number
  exclusive_bytes: number
  shared_bytes: number
}

export interface BtrfsSnapshot {
  id: string
  name: string | null
  project_id: string
  scope_type: 'project'
  scope_name: string
  branch: string | null
  head_oid: string | null
  created_at: string
  source:
    | 'manual'
    | 'auto-baseline'
    | 'auto-periodic'
    | 'auto-claim'
    | 'auto-incomplete'
  usage: BtrfsSnapshotUsage | null
  recovery_path?: string | null
  recovery_active?: boolean
  pin_reason?: string | null
  deletion_error?: string | null
  source_digest?: string | null
  shared_capture?: boolean
  nested_subvolumes?: string[]
  recovery_cleanup_pending?: boolean
  recovery_deletion_error?: string | null
}

export interface BtrfsScope {
  project_id: string
  scope_type: 'project'
  scope_name: string
  scope_state: 'active' | 'archived'
  snapshot_count: number
  total_bytes: number | null
  newest_at: string | null
  oldest_at: string | null
}

export interface BtrfsPolicy {
  interval_minutes: number
  baseline_stale_minutes: number
  auto_keep_per_scope: number
  archived_auto_keep_per_scope: number
  archived_keep_per_project: number
  manual_keep_per_scope: number
  recent_hours?: number
  hourly_days?: number
}

export interface BtrfsSummary {
  total_snapshots: number
  total_usage_bytes: number | null
  by_source: Record<string, number>
  by_scope_type: Record<string, number>
  scope_count: number
  active_snapshot_count: number
  archived_snapshot_count: number
  active_scope_count: number
  archived_scope_count: number
  policy: BtrfsPolicy
  autosnap_timer_active: boolean
}

// ─── API Functions ──────────────────────────────────────────────

export function fetchSnapshots(
  projectId?: string,
  scopeType?: string,
  scopeName?: string,
  includeArchived = false,
): Promise<BtrfsSnapshot[]> {
  return fetchWithErrorHandling<BtrfsSnapshot[]>(
    `/api/snapshots${buildQueryString({
      project_id: projectId,
      scope_type: scopeType,
      scope_name: scopeName,
      include_archived: includeArchived,
    })}`,
    { errorMessage: 'Failed to fetch snapshots' },
  )
}

export function fetchScopes(
  projectId?: string,
  includeArchived = false,
): Promise<BtrfsScope[]> {
  return fetchWithErrorHandling<BtrfsScope[]>(
    `/api/snapshots/scopes${buildQueryString({
      project_id: projectId,
      include_archived: includeArchived,
    })}`,
    { errorMessage: 'Failed to fetch snapshot scopes' },
  )
}

export function fetchSnapshotSummary(
  projectId?: string,
): Promise<BtrfsSummary> {
  return fetchWithErrorHandling<BtrfsSummary>(
    `/api/snapshots/summary${buildQueryString({ project_id: projectId })}`,
    { errorMessage: 'Failed to fetch snapshot summary' },
  )
}

export function createSnapshot(
  projectId: string,
  name?: string,
): Promise<BtrfsSnapshot> {
  return postJson<BtrfsSnapshot>(
    '/api/snapshots/snap',
    { project_id: projectId, name: name ?? null },
    'Failed to create snapshot',
  )
}

export function recoverSnapshot(
  snapshotId: string,
  projectId: string,
  name?: string,
): Promise<{ ok: boolean; recovery_path?: string; error?: string }> {
  return postJson(
    `/api/snapshots/${snapshotId}/recover`,
    { project_id: projectId, name: name ?? null },
    'Failed to recover snapshot',
  )
}

export function pruneSnapshots(dryRun = true): Promise<{
  ok: boolean
  dry_run: boolean
  pruned: number
  recovery_copies?: RecoveryCopyCleanupEvent[]
  recovery_copies_deleted?: number
  recovery_cleanup_failed?: number
  error?: string
}> {
  return postJson(
    '/api/snapshots/prune',
    { dry_run: dryRun },
    'Failed to prune snapshots',
  )
}

export interface RecoveryFilePreview {
  path: string
  current_digest: string
  captured_digest: string
}

export type SelectedRecoveryPreview =
  | {
      ok: true
      snapshot_id: string
      project_id: string
      scope_path: string
      files: RecoveryFilePreview[]
      preview_digest: string
      apply_available: false
      apply_reason: string
    }
  | { ok: false; error: string }

export function previewSnapshotRecovery(
  snapshotId: string,
  projectId: string,
  paths: string[],
): Promise<SelectedRecoveryPreview> {
  return postJson<SelectedRecoveryPreview>(
    `/api/snapshots/${snapshotId}/preview`,
    { project_id: projectId, paths, owned_paths: [] },
    'Failed to preview selected recovery files',
  )
}

export function releaseSnapshotRecovery(
  snapshotId: string,
  projectId: string,
): Promise<{
  ok: boolean
  recovery_active?: boolean
  recovery_path?: string
  cleanup_pending?: boolean
  cleanup_policy?: string
  error?: string
}> {
  return postJson(
    `/api/snapshots/${snapshotId}/release`,
    { project_id: projectId },
    'Failed to release recovery protection',
  )
}

export interface RecoveryCopyCleanupEvent {
  project_id: string
  point_id: string
  root_path: string
  action: 'would-delete' | 'deleted' | 'failed'
  error: string
}
