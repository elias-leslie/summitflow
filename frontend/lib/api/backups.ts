import { buildQueryString, fetchWithErrorHandling } from './utils'

export interface Backup {
  id: string
  project_id: string
  name: string
  backup_type: 'manual' | 'scheduled'
  status: 'pending' | 'running' | 'completed' | 'failed'
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
  verification_json: {
    verified: boolean
    verified_at: string
    errors: string[]
    tree: Record<string, { count: number }>
    total_files: number
    checksum: string
  } | null
  source_id: string
}

export interface BackupListResponse { backups: Backup[]; total: number }
export interface BackupSource {
  id: string
  name: string
  path: string
  source_type: 'project' | 'config' | 'workspace'
  project_id: string | null
  enabled: boolean
  frequency: 'daily' | 'weekly' | 'monthly'
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

type RestoreOptions = { dry_run?: boolean; db_only?: boolean; files_only?: boolean }
type BackupListOptions = { limit?: number; offset?: number; status?: string }
const JSON_HEADERS = { 'Content-Type': 'application/json' }

function restoreBody(opts?: RestoreOptions) {
  return JSON.stringify({
    dry_run: opts?.dry_run ?? false,
    db_only: opts?.db_only ?? false,
    files_only: opts?.files_only ?? false,
  })
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
  return fetchWithErrorHandling<BackupCreateResponse>(
    `/api/projects/${projectId}/backups`,
    {
      method: 'POST',
      headers: JSON_HEADERS,
      body: JSON.stringify({ note: options?.note ?? null, keep_local: options?.keep_local ?? false }),
      errorMessage: 'Failed to create backup',
    },
  )
}

export function restoreBackup(projectId: string, backupId: string, options?: RestoreOptions): Promise<RestoreResponse> {
  return fetchWithErrorHandling<RestoreResponse>(
    `/api/projects/${projectId}/backups/${backupId}/restore`,
    { method: 'POST', headers: JSON_HEADERS, body: restoreBody(options), errorMessage: 'Failed to restore backup' },
  )
}

export function restoreSourceBackup(sourceId: string, backupId: string, options?: RestoreOptions): Promise<RestoreResponse> {
  return fetchWithErrorHandling<RestoreResponse>(
    `/api/backup-sources/${sourceId}/backups/${backupId}/restore`,
    { method: 'POST', headers: JSON_HEADERS, body: restoreBody(options), errorMessage: 'Failed to restore backup' },
  )
}

export function previewRestore(projectId: string, backupId: string): Promise<{
  backup_id: string; backup_name: string; dry_run: boolean; result: unknown
}> {
  return fetchWithErrorHandling(
    `/api/projects/${projectId}/backups/${backupId}/restore/preview`,
    { errorMessage: 'Failed to preview restore' },
  )
}

export function deleteBackup(projectId: string, backupId: string): Promise<{ deleted: boolean; backup_id: string }> {
  return fetchWithErrorHandling(
    `/api/projects/${projectId}/backups/${backupId}`,
    { method: 'DELETE', errorMessage: 'Failed to delete backup' },
  )
}

export function fetchStorageSummary(sourceId?: string): Promise<StorageSummary> {
  const query = sourceId ? `?source_id=${sourceId}` : ''
  return fetchWithErrorHandling<StorageSummary>(`/api/backups/storage${query}`, { errorMessage: 'Failed to fetch storage summary' })
}

export function fetchAllBackups(options?: BackupListOptions & { source_id?: string }): Promise<BackupListResponse> {
  return fetchWithErrorHandling<BackupListResponse>(`/api/backups${backupListQuery(options)}`, { errorMessage: 'Failed to fetch backups' })
}

export function fetchBackupSources(sourceType?: string): Promise<BackupSource[]> {
  const query = sourceType ? `?source_type=${sourceType}` : ''
  return fetchWithErrorHandling<BackupSource[]>(`/api/backup-sources${query}`, { errorMessage: 'Failed to fetch backup sources' })
}

export function fetchBackupSource(sourceId: string): Promise<BackupSource> {
  return fetchWithErrorHandling<BackupSource>(`/api/backup-sources/${sourceId}`, { errorMessage: 'Failed to fetch backup source' })
}

export function updateBackupSource(sourceId: string, data: {
  name?: string; enabled?: boolean; frequency?: string; retention_days?: number
}): Promise<BackupSource> {
  return fetchWithErrorHandling<BackupSource>(
    `/api/backup-sources/${sourceId}`,
    { method: 'PUT', headers: JSON_HEADERS, body: JSON.stringify(data), errorMessage: 'Failed to update backup source' },
  )
}

export function createSourceBackup(sourceId: string, options?: { note?: string; keep_local?: boolean }): Promise<BackupCreateResponse> {
  return fetchWithErrorHandling<BackupCreateResponse>(
    `/api/backup-sources/${sourceId}/backups`,
    {
      method: 'POST',
      headers: JSON_HEADERS,
      body: JSON.stringify({ note: options?.note ?? null, keep_local: options?.keep_local ?? false }),
      errorMessage: 'Failed to create backup',
    },
  )
}

export function fetchSourceBackups(sourceId: string, options?: BackupListOptions): Promise<BackupListResponse> {
  return fetchWithErrorHandling<BackupListResponse>(
    `/api/backup-sources/${sourceId}/backups${backupListQuery(options)}`,
    { errorMessage: 'Failed to fetch source backups' },
  )
}
