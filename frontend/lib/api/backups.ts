/**
 * Backup API - Create, list, and restore project backups.
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
}

export interface BackupListResponse {
  backups: Backup[]
  total: number
}

export interface BackupSchedule {
  id: number
  project_id: string
  enabled: boolean
  frequency: 'daily' | 'weekly' | 'monthly'
  retention_count: number
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
 * Get backup schedule for a project.
 */
export async function fetchBackupSchedule(
  projectId: string,
): Promise<BackupSchedule | null> {
  try {
    const res = await fetch(`/api/projects/${projectId}/backups/schedule`)
    if (!res.ok) {
      if (res.status === 404) return null
      throw new Error('Failed to fetch backup schedule')
    }
    const data = await res.json()
    return data
  } catch {
    return null
  }
}

/**
 * Update backup schedule for a project.
 */
export async function updateBackupSchedule(
  projectId: string,
  schedule: { enabled: boolean; frequency: string; retention_count?: number },
): Promise<BackupSchedule> {
  return fetchWithErrorHandling<BackupSchedule>(
    `/api/projects/${projectId}/backups/schedule`,
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(schedule),
      errorMessage: 'Failed to update backup schedule',
    },
  )
}

/**
 * Get storage summary (global or per-project).
 */
export async function fetchStorageSummary(
  projectId?: string,
): Promise<StorageSummary> {
  const query = projectId ? `?project_id=${projectId}` : ''
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
}): Promise<BackupListResponse> {
  const query = buildQueryString({
    limit: options?.limit ?? 50,
    offset: options?.offset,
    status: options?.status,
  })
  return fetchWithErrorHandling<BackupListResponse>(`/api/backups${query}`, {
    errorMessage: 'Failed to fetch backups',
  })
}
