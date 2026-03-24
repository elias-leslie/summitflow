import { buildQueryString, fetchWithErrorHandling, postJson, putJson } from './utils'

export interface BackupVerification {
  verified: boolean
  verified_at: string
  errors: string[]
  tree: Record<string, { count: number }>
  total_files: number
  checksum: string
  has_db?: boolean
  expects_db?: boolean
}

export interface Backup {
  id: string
  project_id: string
  name: string
  backup_type: 'manual' | 'scheduled'
  status: 'pending' | 'running' | 'completed' | 'failed' | 'completed_pending_upload'
  size_bytes: number | null
  db_size_bytes: number | null
  files_size_bytes: number | null
  location: string | null
  note: string | null
  created_at: string | null
  started_at: string | null
  completed_at: string | null
  error_message: string | null
  verified: boolean | null
  verified_at: string | null
  checksum: string | null
  total_files: number | null
  verification_json: BackupVerification | null
  source_id: string
}

export interface BackupListResponse { backups: Backup[]; total: number }
export interface BackupSource {
  id: string
  name: string
  path: string
  source_type: 'project' | 'config' | 'workspace' | 'infrastructure'
  project_id: string | null
  enabled: boolean
  frequency: 'daily' | 'weekly' | 'monthly' | 'hourly'
  retention_days: number
  last_run_at: string | null
  next_run_at: string | null
  created_at: string | null
  updated_at: string | null
}
export interface BackupCreateResponse { task_id: string; status: string; message: string }
export interface RestoreResponse { task_id: string; status: string; message: string }
export interface StorageSummary {
  total_count: number
  total_bytes: number
  by_status: Record<string, number>
}

export function backupHasDatabase(backup: Backup): boolean {
  if (typeof backup.verification_json?.has_db === 'boolean') {
    return backup.verification_json.has_db
  }
  return (backup.db_size_bytes ?? 0) > 0
}

type RestoreOptions = { dry_run?: boolean; db_only?: boolean; files_only?: boolean }
type BackupListOptions = { limit?: number; offset?: number; status?: string }
function restoreBody(opts?: RestoreOptions) {
  return {
    dry_run: opts?.dry_run ?? false,
    db_only: opts?.db_only ?? false,
    files_only: opts?.files_only ?? false,
  }
}

function backupListQuery(options?: BackupListOptions & { source_id?: string }) {
  return buildQueryString({
    limit: options?.limit ?? 50,
    offset: options?.offset,
    status: options?.status,
    source_id: options?.source_id,
  })
}

export function fetchBackups(projectId: string, options?: BackupListOptions): Promise<BackupListResponse> {
  return fetchWithErrorHandling<BackupListResponse>(
    `/api/projects/${projectId}/backups${backupListQuery(options)}`,
    { errorMessage: 'Failed to fetch backups' },
  )
}

export function fetchBackup(projectId: string, backupId: string): Promise<Backup> {
  return fetchWithErrorHandling<Backup>(
    `/api/projects/${projectId}/backups/${backupId}`,
    { errorMessage: 'Failed to fetch backup' },
  )
}

export function createBackup(projectId: string, options?: { note?: string; keep_local?: boolean }): Promise<BackupCreateResponse> {
  return postJson<BackupCreateResponse>(
    `/api/projects/${projectId}/backups`,
    { note: options?.note ?? null, keep_local: options?.keep_local ?? false },
    'Failed to create backup',
  )
}

export function restoreBackup(projectId: string, backupId: string, options?: RestoreOptions): Promise<RestoreResponse> {
  return postJson<RestoreResponse>(
    `/api/projects/${projectId}/backups/${backupId}/restore`,
    restoreBody(options),
    'Failed to restore backup',
  )
}

export function restoreSourceBackup(sourceId: string, backupId: string, options?: RestoreOptions): Promise<RestoreResponse> {
  return postJson<RestoreResponse>(
    `/api/backup-sources/${sourceId}/backups/${backupId}/restore`,
    restoreBody(options),
    'Failed to restore backup',
  )
}

export function deleteBackup(projectId: string, backupId: string): Promise<{ deleted: boolean; backup_id: string }> {
  return fetchWithErrorHandling(
    `/api/projects/${projectId}/backups/${backupId}`,
    { method: 'DELETE', errorMessage: 'Failed to delete backup' },
  )
}

export function fetchStorageSummary(sourceId?: string): Promise<StorageSummary> {
  return fetchWithErrorHandling<StorageSummary>(`/api/backups/storage${buildQueryString({ source_id: sourceId })}`, { errorMessage: 'Failed to fetch storage summary' })
}

export function fetchAllBackups(options?: BackupListOptions & { source_id?: string }): Promise<BackupListResponse> {
  return fetchWithErrorHandling<BackupListResponse>(`/api/backups${backupListQuery(options)}`, { errorMessage: 'Failed to fetch backups' })
}

export function createBackupSource(data: {
  id: string; name: string; path: string; source_type?: string; project_id?: string
}): Promise<BackupSource> {
  return postJson<BackupSource>('/api/backup-sources', data, 'Failed to create backup source')
}

export function fetchBackupSources(sourceType?: string): Promise<BackupSource[]> {
  return fetchWithErrorHandling<BackupSource[]>(`/api/backup-sources${buildQueryString({ source_type: sourceType })}`, { errorMessage: 'Failed to fetch backup sources' })
}

export function fetchBackupSource(sourceId: string): Promise<BackupSource> {
  return fetchWithErrorHandling<BackupSource>(`/api/backup-sources/${sourceId}`, { errorMessage: 'Failed to fetch backup source' })
}

export function updateBackupSource(sourceId: string, data: {
  name?: string; enabled?: boolean; frequency?: string; retention_days?: number
}): Promise<BackupSource> {
  return putJson<BackupSource>(
    `/api/backup-sources/${sourceId}`,
    data,
    'Failed to update backup source',
  )
}

export function createSourceBackup(sourceId: string, options?: { note?: string; keep_local?: boolean }): Promise<BackupCreateResponse> {
  return postJson<BackupCreateResponse>(
    `/api/backup-sources/${sourceId}/backups`,
    { note: options?.note ?? null, keep_local: options?.keep_local ?? false },
    'Failed to create backup',
  )
}

export function fetchSourceBackups(sourceId: string, options?: BackupListOptions): Promise<BackupListResponse> {
  return fetchWithErrorHandling<BackupListResponse>(
    `/api/backup-sources/${sourceId}/backups${backupListQuery(options)}`,
    { errorMessage: 'Failed to fetch source backups' },
  )
}

// ─── Storage Backends ───────────────────────────────────────────

export interface StorageBackend {
  id: string
  name: string
  backend_type: string
  config: Record<string, unknown>
  is_default: boolean
  enabled: boolean
  last_test_at: string | null
  last_test_ok: boolean | null
  created_at: string | null
  updated_at: string | null
}

export interface StorageStatus {
  configured: boolean
  backend_count: number
  default_backend_id: string | null
  default_backend_name: string | null
}

export interface BackupHealthItem {
  source_id: string
  source_name: string
  source_type: string
  enabled: boolean
  health_status: 'green' | 'yellow' | 'red'
  last_success_at: string | null
  next_run_at: string | null
  failure_count_7d: number
  pending_upload_count: number
  last_restore_tested_at: string | null
  last_restore_test_ok: boolean | null
  // Extended health fields
  latest_backup_age_hours: number | null
  latest_restore_test_age_hours: number | null
  restore_test_backup_id: string | null
  coverage_complete: boolean | null
  pitr_supported: boolean
  restore_confidence: 'verified' | 'stale' | 'partial' | 'untested' | null
  // Drill tracking
  last_drill_at: string | null
  last_drill_ok: boolean | null
  last_drill_backup_id: string | null
}

export interface WalHealthSummary {
  enabled: boolean
  archive_segment_count: number
  archive_size_bytes: number
  last_archived_time: string | null
  failed_count: number
}

export interface BackupHealthResponse {
  sources: BackupHealthItem[]
  pending_upload_count: number
  wal: WalHealthSummary | null
}

export function fetchStorageBackends(): Promise<StorageBackend[]> {
  return fetchWithErrorHandling<StorageBackend[]>('/api/backup-storage', { errorMessage: 'Failed to fetch storage backends' })
}

export function fetchStorageStatus(): Promise<StorageStatus> {
  return fetchWithErrorHandling<StorageStatus>('/api/backup-storage/status', { errorMessage: 'Failed to fetch storage status' })
}

export function createStorageBackend(data: {
  name: string; backend_type?: string; config?: Record<string, unknown>; is_default?: boolean
}): Promise<StorageBackend> {
  return postJson<StorageBackend>('/api/backup-storage', data, 'Failed to create storage backend')
}

export function testStorageBackend(id: string): Promise<{ success: boolean; message: string }> {
  return fetchWithErrorHandling(`/api/backup-storage/${id}/test`, {
    method: 'POST', errorMessage: 'Failed to test storage backend',
  })
}

export function fetchBackupHealth(): Promise<BackupHealthResponse> {
  return fetchWithErrorHandling<BackupHealthResponse>('/api/backups/health', { errorMessage: 'Failed to fetch backup health' })
}

// ─── Coverage Contract ──────────────────────────────────────────

export interface CoverageComponent {
  key: string
  label: string
  category: 'required' | 'optional' | 'excluded'
  description: string
  archive_marker: string | null
  reason: string | null
}

export interface CoverageVerificationComponent {
  key: string
  label: string
  category: string
  present: boolean
  error: string | null
}

export interface CoverageVerificationResult {
  complete: boolean
  required_count: number
  present_count: number
  missing: string[]
  components: CoverageVerificationComponent[]
}

export interface CoverageResponse {
  contract: CoverageComponent[]
  verified: boolean
  result: CoverageVerificationResult | null
}

export function fetchInfraCoverage(): Promise<CoverageResponse> {
  return fetchWithErrorHandling<CoverageResponse>('/api/backups/infra/coverage', { errorMessage: 'Failed to fetch coverage' })
}

// ─── Restore Drill ──────────────────────────────────────────────

export interface DrillComponentResult {
  key: string
  ok: boolean
  error: string | null
}

export interface RestoreDrillResult {
  ok: boolean
  backup_id: string | null
  components: DrillComponentResult[]
  duration_ms: number | null
  error?: string
}

export function runRestoreDrill(): Promise<RestoreDrillResult> {
  return fetchWithErrorHandling<RestoreDrillResult>('/api/backups/restore-drill/infra', {
    method: 'POST', errorMessage: 'Failed to run restore drill',
  })
}

// ─── WAL Archiving ──────────────────────────────────────────────

export interface WalStatus {
  archive_mode: string
  archive_command: string
  current_lsn: string
  enabled: boolean
  pending_restart?: boolean
  archived_count?: number
  last_archived_wal?: string
  last_archived_time?: string
  failed_count?: number
  last_failed_wal?: string
  last_failed_time?: string
}

export function fetchWalStatus(): Promise<WalStatus> {
  return fetchWithErrorHandling<WalStatus>('/api/backups/wal/status', { errorMessage: 'Failed to fetch WAL status' })
}

export function enableWalArchiving(): Promise<WalStatus> {
  return fetchWithErrorHandling<WalStatus>('/api/backups/wal/enable', {
    method: 'POST', errorMessage: 'Failed to enable WAL archiving',
  })
}

export function disableWalArchiving(): Promise<WalStatus> {
  return fetchWithErrorHandling<WalStatus>('/api/backups/wal/disable', {
    method: 'POST', errorMessage: 'Failed to disable WAL archiving',
  })
}
