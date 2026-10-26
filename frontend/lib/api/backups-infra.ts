import { fetchWithErrorHandling, postJson } from './utils'

// ─── Recovery key ───────────────────────────────────────────────

export interface BackupEncryptionStatus {
  configured: boolean
  ready: boolean
  key_id: string | null
  roundtrip_verified_at: string | null
  identity_exported: boolean
  can_manage_key: boolean
  protection_limit?: string
}

export function fetchBackupEncryption(): Promise<BackupEncryptionStatus> {
  return fetchWithErrorHandling('/api/backups/encryption', {
    cache: 'no-store',
    errorMessage: 'Could not load backup encryption status',
  })
}

export function setupBackupEncryption(): Promise<BackupEncryptionStatus> {
  return postJson(
    '/api/backups/encryption/setup',
    {},
    'Could not set up backup encryption',
  )
}

// Secret responses are fetched only on explicit owner action, never through a
// query cache. Callers keep them in memory only and clear revealed text on hide.
export function exportBackupRecoveryKey(): Promise<{
  key_id: string
  recovery_key: string
}> {
  return fetchWithErrorHandling('/api/backups/encryption/export', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: '{}',
    cache: 'no-store',
    errorMessage: 'Could not retrieve the backup recovery key',
  })
}

export function verifyBackupRecoveryKey(
  recoveryKey: string,
): Promise<BackupEncryptionStatus> {
  return fetchWithErrorHandling('/api/backups/encryption/verify', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ recovery_key: recoveryKey }),
    cache: 'no-store',
    errorMessage: 'The recovery key did not decrypt the test backup',
  })
}

export function importBackupRecoveryKey(
  recoveryKey: string,
): Promise<BackupEncryptionStatus> {
  return fetchWithErrorHandling('/api/backups/encryption/import', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ recovery_key: recoveryKey }),
    cache: 'no-store',
    errorMessage: 'Could not restore the saved recovery key',
  })
}

// ─── Backups run by other projects ──────────────────────────────

export interface ExternalBackupSource {
  id: string
  name: string | null
  owner_project: string | null
  kind: 'systemd_unit' | 'artifact_glob'
  target: string
  frequency: string
  ok: boolean
  stale_after_hours: number
  last_success_at: string | null
  last_status: string | null
  last_error: string | null
}

export function fetchExternalBackups(): Promise<{
  generated_at: string
  sources: ExternalBackupSource[]
}> {
  return fetchWithErrorHandling('/api/backups/external', {
    errorMessage: 'Failed to load backups other projects run',
  })
}
