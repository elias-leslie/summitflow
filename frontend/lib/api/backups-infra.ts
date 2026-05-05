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

export interface BackupHealthResponse {
  sources: BackupHealthItem[]
  pending_upload_count: number
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

export function fetchBackupHealth(): Promise<BackupHealthResponse> {
  return fetchWithErrorHandling<BackupHealthResponse>('/api/backups/health', {
    errorMessage: 'Failed to fetch backup health',
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
