/**
 * Backup API - Create, list, and restore backups across all sources.
 */

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

export interface BackupListResponse {
  backups: Backup[]
  total: number
}

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

export interface BackupCreateResponse {
  task_id: string
  status: string
  message: string
}

export interface RestoreResponse {
  task_id: string
  status: string
  message: string
}

export interface StorageSummary {
  total_count: number
  total_bytes: number
  by_status: Record<string, number>
}

/**
 * List backups for a project.
 */
export async function fetchBackups(
  projectId: string,
  options?: { limit?: number; offset?: number; status?: string },
): Promise<BackupListResponse> {
  const query = buildQueryString({
    limit: options?.limit ?? 50,
    offset: options?.offset,
    status: options?.status,
  })
  return fetchWithErrorHandling<BackupListResponse>(
    `/api/projects/${projectId}/backups${query}`,
    { errorMessage: 'Failed to fetch backups' },
  )
}

/**
 * Get a single backup.
 */
export async function fetchBackup(
  projectId: string,
  backupId: string,
): Promise<Backup> {
  return fetchWithErrorHandling<Backup>(
    `/api/projects/${projectId}/backups/${backupId}`,
    { errorMessage: 'Failed to fetch backup' },
  )
}

/**
 * Create a new backup.
 */
export async function createBackup(
  projectId: string,
  options?: { note?: string; keep_local?: boolean },
): Promise<BackupCreateResponse> {
  return fetchWithErrorHandling<BackupCreateResponse>(
    `/api/projects/${projectId}/backups`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        note: options?.note ?? null,
        keep_local: options?.keep_local ?? false,
      }),
      errorMessage: 'Failed to create backup',
    },
  )
}

/**
 * Restore from a backup.
 */
export async function restoreBackup(
  projectId: string,
  backupId: string,
  options?: { dry_run?: boolean; db_only?: boolean; files_only?: boolean },
): Promise<RestoreResponse> {
  return fetchWithErrorHandling<RestoreResponse>(
    `/api/projects/${projectId}/backups/${backupId}/restore`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        dry_run: options?.dry_run ?? false,
        db_only: options?.db_only ?? false,
        files_only: options?.files_only ?? false,
      }),
      errorMessage: 'Failed to restore backup',
    },
  )
}

/**
 * Restore from a backup via source endpoint (works for all source types).
 */
export async function restoreSourceBackup(
  sourceId: string,
  backupId: string,
  options?: { dry_run?: boolean; db_only?: boolean; files_only?: boolean },
): Promise<RestoreResponse> {
  return fetchWithErrorHandling<RestoreResponse>(
    `/api/backup-sources/${sourceId}/backups/${backupId}/restore`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        dry_run: options?.dry_run ?? false,
        db_only: options?.db_only ?? false,
        files_only: options?.files_only ?? false,
      }),
      errorMessage: 'Failed to restore backup',
    },
  )
}

/**
 * Preview what would be restored.
 */
export async function previewRestore(
  projectId: string,
  backupId: string,
): Promise<{
  backup_id: string
  backup_name: string
  dry_run: boolean
  result: unknown
}> {
  return fetchWithErrorHandling(
    `/api/projects/${projectId}/backups/${backupId}/restore/preview`,
    { errorMessage: 'Failed to preview restore' },
  )
}

/**
 * Delete a backup record.
 */
export async function deleteBackup(
  projectId: string,
  backupId: string,
): Promise<{ deleted: boolean; backup_id: string }> {
  return fetchWithErrorHandling(
    `/api/projects/${projectId}/backups/${backupId}`,
    {
      method: 'DELETE',
      errorMessage: 'Failed to delete backup',
    },
  )
}

/**
 * Get storage summary (global or per-source).
 */
export async function fetchStorageSummary(
  sourceId?: string,
): Promise<StorageSummary> {
  const query = sourceId ? `?source_id=${sourceId}` : ''
  return fetchWithErrorHandling<StorageSummary>(
    `/api/backups/storage${query}`,
    { errorMessage: 'Failed to fetch storage summary' },
  )
}

/**
 * List all backups (global).
 */
export async function fetchAllBackups(options?: {
  limit?: number
  offset?: number
  status?: string
  source_id?: string
}): Promise<BackupListResponse> {
  const query = buildQueryString({
    limit: options?.limit ?? 50,
    offset: options?.offset,
    status: options?.status,
    source_id: options?.source_id,
  })
  return fetchWithErrorHandling<BackupListResponse>(`/api/backups${query}`, {
    errorMessage: 'Failed to fetch backups',
  })
}

// --- Backup Sources ---

/**
 * List all backup sources.
 */
export async function fetchBackupSources(
  sourceType?: string,
): Promise<BackupSource[]> {
  const query = sourceType ? `?source_type=${sourceType}` : ''
  return fetchWithErrorHandling<BackupSource[]>(
    `/api/backup-sources${query}`,
    { errorMessage: 'Failed to fetch backup sources' },
  )
}

/**
 * Get a single backup source.
 */
export async function fetchBackupSource(
  sourceId: string,
): Promise<BackupSource> {
  return fetchWithErrorHandling<BackupSource>(
    `/api/backup-sources/${sourceId}`,
    { errorMessage: 'Failed to fetch backup source' },
  )
}

/**
 * Update a backup source (schedule config, name, etc).
 */
export async function updateBackupSource(
  sourceId: string,
  data: {
    name?: string
    enabled?: boolean
    frequency?: string
    retention_days?: number
  },
): Promise<BackupSource> {
  return fetchWithErrorHandling<BackupSource>(
    `/api/backup-sources/${sourceId}`,
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
      errorMessage: 'Failed to update backup source',
    },
  )
}

/**
 * Create a backup for a specific source.
 */
export async function createSourceBackup(
  sourceId: string,
  options?: { note?: string; keep_local?: boolean },
): Promise<BackupCreateResponse> {
  return fetchWithErrorHandling<BackupCreateResponse>(
    `/api/backup-sources/${sourceId}/backups`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        note: options?.note ?? null,
        keep_local: options?.keep_local ?? false,
      }),
      errorMessage: 'Failed to create backup',
    },
  )
}

/**
 * List backups for a specific source.
 */
export async function fetchSourceBackups(
  sourceId: string,
  options?: { limit?: number; offset?: number; status?: string },
): Promise<BackupListResponse> {
  const query = buildQueryString({
    limit: options?.limit ?? 50,
    offset: options?.offset,
    status: options?.status,
  })
  return fetchWithErrorHandling<BackupListResponse>(
    `/api/backup-sources/${sourceId}/backups${query}`,
    { errorMessage: 'Failed to fetch source backups' },
  )
}
