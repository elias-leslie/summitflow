import { parseBackupHealth } from './backups-health'
import { fetchWithErrorHandling, postJson } from './utils'

// ─── Storage Backends ───────────────────────────────────────────

export interface StorageBackend {
  id: string
  name: string
  backend_type: 'smb' | 'local' | string
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

export interface BackupActivity {
  backup_id: string
  run_id: string | null
  active: boolean
  phase: string
  operation_started_at: string | null
  last_verified_at: string | null
  last_verified_part: string | null
  verified_parts: number
  attention: boolean
  cancel_requested: boolean
  remote_outcome_unknown: boolean
}

export interface BackupHealthItem {
  source_id: string
  source_name: string
  source_type: string
  enabled: boolean
  health_status: 'green' | 'yellow' | 'red' | 'disabled'
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
  latest_backup_id: string | null
  offsite_status: 'verified' | 'pending' | 'failed' | 'unconfigured'
  last_offsite_verified_at: string | null
  offsite_location: string | null
  offsite_checksum: string | null
  offsite_error: string | null
  last_isolated_restore_at: string | null
  last_isolated_restore_ok: boolean | null
  backup_activity?: BackupActivity | null
}

export interface BackupHealthResponse {
  sources: BackupHealthItem[]
  pending_upload_count: number
  repositories?: BackupRepositoryHealthItem[]
}

export interface CriticalRestoreAttempt {
  status: 'verified' | 'failed' | 'running'
  attempted_at: string | null
  completed_at: string | null
  failed_source_id: string | null
  reason:
    | 'mapped-links-unresolved'
    | 'repository-locked'
    | 'restore-failed'
    | null
  cached: boolean
}

export interface CriticalRestoreHealth {
  status:
    | 'verified'
    | 'failed'
    | 'pending'
    | 'running'
    | 'stale'
    | 'untested'
    | 'unavailable'
  last_success_at: string | null
  latest_attempt: CriticalRestoreAttempt | null
  required_source_ids: string[]
  verified_source_ids: string[]
  missing_source_ids: string[]
}

export interface BackupRepositoryHealthItem {
  backend_id: string
  backend_name: string
  critical_restore: CriticalRestoreHealth
}

export function fetchStorageBackends(): Promise<StorageBackend[]> {
  return fetchWithErrorHandling<StorageBackend[]>('/api/backup-storage', {
    errorMessage: 'Failed to fetch storage backends',
  })
}

export function fetchStorageStatus(): Promise<StorageStatus> {
  return fetchWithErrorHandling<StorageStatus>('/api/backup-storage/status', {
    errorMessage: 'Failed to fetch storage status',
  })
}

export function createStorageBackend(data: {
  name: string
  backend_type?: string
  config?: Record<string, unknown>
  is_default?: boolean
}): Promise<StorageBackend> {
  return postJson<StorageBackend>(
    '/api/backup-storage',
    data,
    'Failed to create storage backend',
  )
}

export function testStorageBackend(
  id: string,
): Promise<{ success: boolean; message: string }> {
  return fetchWithErrorHandling(`/api/backup-storage/${id}/test`, {
    method: 'POST',
    errorMessage: 'Failed to test storage backend',
  })
}

export async function fetchBackupHealth(): Promise<BackupHealthResponse> {
  const value = await fetchWithErrorHandling<unknown>('/api/backups/health', {
    errorMessage: 'Failed to fetch backup health',
  })
  return parseBackupHealth(value)
}

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
  return fetchWithErrorHandling<CoverageResponse>(
    '/api/backups/infra/coverage',
    { errorMessage: 'Failed to fetch coverage' },
  )
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
  return fetchWithErrorHandling<RestoreDrillResult>(
    '/api/backups/restore-drill/infra',
    {
      method: 'POST',
      errorMessage: 'Failed to run restore drill',
    },
  )
}

// ─── System Image / Veeam ──────────────────────────────────────

export interface SystemImageSession {
  id: string
  job_name: string
  session_type: string
  state: string
  created_at: string | null
  started_at: string | null
  finished_at: string | null
}

export interface SystemImageBackupStatus {
  installed: boolean
  version: string | null
  service_active: boolean
  secure_boot_enabled: boolean
  mok_enrolled: boolean
  mok_enrollment_pending: boolean
  module_loaded: boolean
  module_signer: string | null
  repository_name: string
  repository_path: string
  repository_accessible: boolean
  job_name: string
  job_configured: boolean
  job_id: string | null
  schedule_summary: string | null
  protected_objects: string[]
  last_session: SystemImageSession | null
  active_session: SystemImageSession | null
  can_start: boolean
  blocked_reason: string | null
  next_action: string
}

export interface SystemImageActionResponse {
  status: string
  message: string
  session_id: string | null
  output: string | null
}

export function fetchSystemImageBackupStatus(): Promise<SystemImageBackupStatus> {
  return fetchWithErrorHandling<SystemImageBackupStatus>(
    '/api/backups/system-image',
    { errorMessage: 'Failed to fetch system-image backup status' },
  )
}

export function startSystemImageBackup(): Promise<SystemImageActionResponse> {
  return fetchWithErrorHandling<SystemImageActionResponse>(
    '/api/backups/system-image/start',
    {
      method: 'POST',
      errorMessage: 'Failed to start system-image backup',
    },
  )
}

export function stopSystemImageBackup(): Promise<SystemImageActionResponse> {
  return fetchWithErrorHandling<SystemImageActionResponse>(
    '/api/backups/system-image/stop',
    {
      method: 'POST',
      errorMessage: 'Failed to stop system-image backup',
    },
  )
}

export interface NativeHostBackupStatus {
  engine: 'btrbk'
  enabled: boolean
  installed: boolean
  configured: boolean
  ready: boolean
  retention: string
  windows_method: 'Veeam'
  blocked_reason?: string | null
  sources?: string[]
  target?: string
  capacity?: {
    admitted: boolean
    expected_growth_bytes: number
    reserve_bytes: number
    free_bytes: number
    used_bytes: number
    source_filesystems: Array<{
      path: string
      used_bytes: number
      free_bytes: number
      under_pressure: boolean
    }>
    under_pressure: boolean
    reason: string | null
  }
  last_result?: {
    status: string
    started_at?: string | null
    finished_at?: string | null
    evidence?: string | null
    error?: string | null
    remaining_capacity_bytes?: number
    reclaimed_bytes?: number
    boot_path?: string | null
  } | null
}

function nativeHostObject(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value))
    throw new Error('Native Linux backup status is malformed')
  return value as Record<string, unknown>
}

function validateNativeHostFields(
  row: Record<string, unknown>,
  fields: Record<
    string,
    'boolean' | 'number' | 'string' | 'optionalString' | 'optionalNumber'
  >,
) {
  for (const [key, kind] of Object.entries(fields)) {
    const value = row[key]
    if (kind === 'optionalString' && (value === undefined || value === null))
      continue
    if (kind === 'optionalNumber' && value === undefined) continue
    const type =
      kind === 'optionalString'
        ? 'string'
        : kind === 'optionalNumber'
          ? 'number'
          : kind
    if (
      typeof value !== type ||
      (type === 'number' &&
        (typeof value !== 'number' || !Number.isFinite(value) || value < 0))
    )
      throw new Error('Native Linux backup status is malformed')
  }
}

export async function fetchNativeHostBackupStatus(): Promise<NativeHostBackupStatus> {
  const row = nativeHostObject(
    await fetchWithErrorHandling<unknown>('/api/backups/native-host', {
      cache: 'no-store',
      errorMessage: 'Could not load native Linux backup status',
    }),
  )
  validateNativeHostFields(row, {
    enabled: 'boolean',
    installed: 'boolean',
    configured: 'boolean',
    ready: 'boolean',
    retention: 'string',
    blocked_reason: 'optionalString',
    target: 'optionalString',
  })
  if (
    row.engine !== 'btrbk' ||
    row.windows_method !== 'Veeam' ||
    row.target === null ||
    (row.sources !== undefined &&
      (!Array.isArray(row.sources) ||
        row.sources.some((source) => typeof source !== 'string')))
  )
    throw new Error('Native Linux backup status is malformed')
  if (row.capacity !== undefined) {
    const capacity = nativeHostObject(row.capacity)
    validateNativeHostFields(capacity, {
      admitted: 'boolean',
      expected_growth_bytes: 'number',
      reserve_bytes: 'number',
      free_bytes: 'number',
      used_bytes: 'number',
      under_pressure: 'boolean',
      reason: 'optionalString',
    })
    if (
      capacity.reason === undefined ||
      !Array.isArray(capacity.source_filesystems)
    )
      throw new Error('Native Linux backup status is malformed')
    for (const source of capacity.source_filesystems) {
      validateNativeHostFields(nativeHostObject(source), {
        path: 'string',
        used_bytes: 'number',
        free_bytes: 'number',
        under_pressure: 'boolean',
      })
    }
  }
  if (row.last_result !== undefined && row.last_result !== null) {
    validateNativeHostFields(nativeHostObject(row.last_result), {
      status: 'string',
      started_at: 'optionalString',
      finished_at: 'optionalString',
      evidence: 'optionalString',
      error: 'optionalString',
      boot_path: 'optionalString',
      remaining_capacity_bytes: 'optionalNumber',
      reclaimed_bytes: 'optionalNumber',
    })
  }
  return row as unknown as NativeHostBackupStatus
}
