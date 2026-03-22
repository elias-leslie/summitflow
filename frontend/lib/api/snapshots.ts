import { fetchWithErrorHandling, postJson } from './utils'

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
  scope_type: 'lane' | 'project'
  scope_name: string
  branch: string | null
  head_oid: string | null
  created_at: string
  source: 'manual' | 'auto-baseline' | 'auto-periodic' | 'auto-claim'
  usage: BtrfsSnapshotUsage | null
}

export interface BtrfsScope {
  project_id: string
  scope_type: 'lane' | 'project'
  scope_name: string
  snapshot_count: number
  total_bytes: number | null
  newest_at: string | null
  oldest_at: string | null
}

export interface BtrfsPolicy {
  lane_interval_minutes: number
  project_interval_minutes: number
  baseline_stale_minutes: number
  lane_auto_keep_per_scope: number
  project_auto_keep_per_scope: number
  manual_keep_per_scope: number
}

export interface BtrfsSummary {
  total_snapshots: number
  total_usage_bytes: number
  by_source: Record<string, number>
  by_scope_type: Record<string, number>
  scope_count: number
  policy: BtrfsPolicy
  autosnap_timer_active: boolean
}

// ─── API Functions ──────────────────────────────────────────────

export function fetchSnapshots(projectId?: string, scopeType?: string): Promise<BtrfsSnapshot[]> {
  const params = new URLSearchParams()
  if (projectId) params.set('project_id', projectId)
  if (scopeType) params.set('scope_type', scopeType)
  const qs = params.toString()
  return fetchWithErrorHandling<BtrfsSnapshot[]>(
    `/api/snapshots${qs ? `?${qs}` : ''}`,
    { errorMessage: 'Failed to fetch snapshots' },
  )
}

export function fetchScopes(projectId?: string): Promise<BtrfsScope[]> {
  const qs = projectId ? `?project_id=${projectId}` : ''
  return fetchWithErrorHandling<BtrfsScope[]>(
    `/api/snapshots/scopes${qs}`,
    { errorMessage: 'Failed to fetch snapshot scopes' },
  )
}

export function fetchSnapshotPolicy(): Promise<BtrfsPolicy> {
  return fetchWithErrorHandling<BtrfsPolicy>(
    '/api/snapshots/policy',
    { errorMessage: 'Failed to fetch snapshot policy' },
  )
}

export function fetchSnapshotSummary(projectId?: string): Promise<BtrfsSummary> {
  const qs = projectId ? `?project_id=${projectId}` : ''
  return fetchWithErrorHandling<BtrfsSummary>(
    `/api/snapshots/summary${qs}`,
    { errorMessage: 'Failed to fetch snapshot summary' },
  )
}

export function createSnapshot(projectId: string, name?: string): Promise<BtrfsSnapshot> {
  return postJson<BtrfsSnapshot>(
    '/api/snapshots/snap',
    { project_id: projectId, name: name ?? null },
    'Failed to create snapshot',
  )
}

export function recoverSnapshot(snapshotId: string, projectId: string, name?: string): Promise<{ ok: boolean; recovery_path?: string; error?: string }> {
  return postJson(
    `/api/snapshots/${snapshotId}/recover`,
    { project_id: projectId, name: name ?? null },
    'Failed to recover snapshot',
  )
}

export function pruneSnapshots(dryRun = true): Promise<{ ok: boolean; dry_run: boolean; pruned: number; error?: string }> {
  return postJson(
    '/api/snapshots/prune',
    { dry_run: dryRun },
    'Failed to prune snapshots',
  )
}
