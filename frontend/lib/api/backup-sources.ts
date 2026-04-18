import type { BackupListResponse } from './backups'
import {
  buildQueryString,
  fetchWithErrorHandling,
  postJson,
  putJson,
} from './utils'

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

export interface BackupCreateResponse {
  task_id: string
  status: string
  message: string
}
export type RestoreOptions = {
  dry_run?: boolean
  db_only?: boolean
  files_only?: boolean
}
export type BackupListOptions = {
  limit?: number
  offset?: number
  status?: string
}

function listQuery(options?: BackupListOptions) {
  return buildQueryString({
    limit: options?.limit ?? 50,
    offset: options?.offset,
    status: options?.status,
  })
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
  return postJson<BackupCreateResponse>(
    `/api/backup-sources/${sourceId}/backups`,
    { note: options?.note ?? null, keep_local: options?.keep_local ?? false },
    'Failed to create backup',
  )
}

export function fetchSourceBackups(
  sourceId: string,
  options?: BackupListOptions,
): Promise<BackupListResponse> {
  return fetchWithErrorHandling<BackupListResponse>(
    `/api/backup-sources/${sourceId}/backups${listQuery(options)}`,
    { errorMessage: 'Failed to fetch source backups' },
  )
}

export function restoreSourceBackup(
  sourceId: string,
  backupId: string,
  options?: RestoreOptions,
): Promise<BackupCreateResponse> {
  return postJson<BackupCreateResponse>(
    `/api/backup-sources/${sourceId}/backups/${backupId}/restore`,
    {
      dry_run: options?.dry_run ?? false,
      db_only: options?.db_only ?? false,
      files_only: options?.files_only ?? false,
    },
    'Failed to restore backup',
  )
}
