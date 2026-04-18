import {
  buildQueryString,
  fetchWithErrorHandling,
  postJson,
  putJson,
} from './utils'

// Re-export infra types and functions so existing imports from this module keep working
export * from './backups-infra'

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
  status:
    | 'pending'
    | 'running'
    | 'completed'
    | 'failed'
    | 'completed_pending_upload'
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

export interface BackupListResponse {
  backups: Backup[]
  total: number
}
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

interface TaskResponse {
  task_id: string
  status: string
  message: string
}
export type BackupCreateResponse = TaskResponse
export type RestoreResponse = TaskResponse

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

type RestoreOptions = {
  dry_run?: boolean
  db_only?: boolean
  files_only?: boolean
}
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

function createBackupPost(
  url: string,
  options?: { note?: string; keep_local?: boolean },
): Promise<BackupCreateResponse> {
  return postJson<BackupCreateResponse>(
    url,
    { note: options?.note ?? null, keep_local: options?.keep_local ?? false },
    'Failed to create backup',
  )
}

export function fetchBackups(
  projectId: string,
  options?: BackupListOptions,
): Promise<BackupListResponse> {
  return fetchWithErrorHandling<BackupListResponse>(
    `/api/projects/${projectId}/backups${backupListQuery(options)}`,
    { errorMessage: 'Failed to fetch backups' },
  )
}

export function fetchBackup(
  projectId: string,
  backupId: string,
): Promise<Backup> {
  return fetchWithErrorHandling<Backup>(
    `/api/projects/${projectId}/backups/${backupId}`,
    { errorMessage: 'Failed to fetch backup' },
  )
}

export function createBackup(
  projectId: string,
  options?: { note?: string; keep_local?: boolean },
): Promise<BackupCreateResponse> {
  return createBackupPost(`/api/projects/${projectId}/backups`, options)
}

export function restoreBackup(
  projectId: string,
  backupId: string,
  options?: RestoreOptions,
): Promise<RestoreResponse> {
  return postJson<RestoreResponse>(
    `/api/projects/${projectId}/backups/${backupId}/restore`,
    restoreBody(options),
    'Failed to restore backup',
  )
}

export function restoreSourceBackup(
  sourceId: string,
  backupId: string,
  options?: RestoreOptions,
): Promise<RestoreResponse> {
  return postJson<RestoreResponse>(
    `/api/backup-sources/${sourceId}/backups/${backupId}/restore`,
    restoreBody(options),
    'Failed to restore backup',
  )
}

export function deleteBackup(
  projectId: string,
  backupId: string,
): Promise<{ deleted: boolean; backup_id: string }> {
  return fetchWithErrorHandling(
    `/api/projects/${projectId}/backups/${backupId}`,
    { method: 'DELETE', errorMessage: 'Failed to delete backup' },
  )
}

export function fetchStorageSummary(
  sourceId?: string,
): Promise<StorageSummary> {
  return fetchWithErrorHandling<StorageSummary>(
    `/api/backups/storage${buildQueryString({ source_id: sourceId })}`,
    { errorMessage: 'Failed to fetch storage summary' },
  )
}

export function fetchAllBackups(
  options?: BackupListOptions & { source_id?: string },
): Promise<BackupListResponse> {
  return fetchWithErrorHandling<BackupListResponse>(
    `/api/backups${backupListQuery(options)}`,
    { errorMessage: 'Failed to fetch backups' },
  )
}

export function createBackupSource(data: {
  id: string
  name: string
  path: string
  source_type?: string
  project_id?: string
}): Promise<BackupSource> {
  return postJson<BackupSource>(
    '/api/backup-sources',
    data,
    'Failed to create backup source',
  )
}

export function fetchBackupSources(
  sourceType?: string,
): Promise<BackupSource[]> {
  return fetchWithErrorHandling<BackupSource[]>(
    `/api/backup-sources${buildQueryString({ source_type: sourceType })}`,
    { errorMessage: 'Failed to fetch backup sources' },
  )
}

export function fetchBackupSource(sourceId: string): Promise<BackupSource> {
  return fetchWithErrorHandling<BackupSource>(
    `/api/backup-sources/${sourceId}`,
    { errorMessage: 'Failed to fetch backup source' },
  )
}

export function updateBackupSource(
  sourceId: string,
  data: {
    name?: string
    enabled?: boolean
    frequency?: string
    retention_days?: number
  },
): Promise<BackupSource> {
  return putJson<BackupSource>(
    `/api/backup-sources/${sourceId}`,
    data,
    'Failed to update backup source',
  )
}

export function createSourceBackup(
  sourceId: string,
  options?: { note?: string; keep_local?: boolean },
): Promise<BackupCreateResponse> {
  return createBackupPost(`/api/backup-sources/${sourceId}/backups`, options)
}

export function fetchSourceBackups(
  sourceId: string,
  options?: BackupListOptions,
): Promise<BackupListResponse> {
  return fetchWithErrorHandling<BackupListResponse>(
    `/api/backup-sources/${sourceId}/backups${backupListQuery(options)}`,
    { errorMessage: 'Failed to fetch source backups' },
  )
}
