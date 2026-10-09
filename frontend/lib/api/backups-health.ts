import type {
  BackupActivity,
  BackupHealthItem,
  BackupHealthResponse,
  BackupRepositoryHealthItem,
  CriticalRestoreAttempt,
  CriticalRestoreHealth,
} from './backups-infra'

type Validator = (value: unknown) => boolean
type Schema = Record<string, Validator>

const string: Validator = (value) => typeof value === 'string'
const timestamp: Validator = (value) =>
  typeof value === 'string' && Number.isFinite(Date.parse(value))
const boolean: Validator = (value) => typeof value === 'boolean'
const number: Validator = (value) =>
  typeof value === 'number' && Number.isFinite(value)
const count: Validator = (value) =>
  number(value) && Number.isInteger(value) && (value as number) >= 0
const nullable =
  (validate: Validator): Validator =>
  (value) =>
    value === null || validate(value)
const optional =
  (validate: Validator): Validator =>
  (value) =>
    value === undefined || validate(value)
const oneOf =
  (...values: string[]): Validator =>
  (value) =>
    typeof value === 'string' && values.includes(value)
const strings: Validator = (value) =>
  Array.isArray(value) && value.every(string)

function matches(value: unknown, schema: Schema): boolean {
  return (
    value !== null &&
    typeof value === 'object' &&
    !Array.isArray(value) &&
    Object.entries(schema).every(([key, validate]) =>
      validate((value as Record<string, unknown>)[key]),
    )
  )
}

const activitySchema: Record<keyof BackupActivity, Validator> = {
  backup_id: string,
  run_id: nullable(string),
  active: boolean,
  phase: string,
  operation_started_at: nullable(string),
  last_verified_at: nullable(string),
  last_verified_part: nullable(string),
  verified_parts: count,
  attention: boolean,
  cancel_requested: boolean,
  remote_outcome_unknown: boolean,
}

const sourceSchema: Record<keyof BackupHealthItem, Validator> = {
  source_id: string,
  source_name: string,
  source_type: string,
  enabled: boolean,
  health_status: oneOf('green', 'yellow', 'red', 'disabled'),
  last_success_at: nullable(string),
  next_run_at: nullable(string),
  failure_count_7d: count,
  pending_upload_count: count,
  last_restore_tested_at: nullable(string),
  last_restore_test_ok: nullable(boolean),
  latest_backup_age_hours: nullable(number),
  latest_restore_test_age_hours: nullable(number),
  restore_test_backup_id: nullable(string),
  coverage_complete: nullable(boolean),
  pitr_supported: boolean,
  restore_confidence: nullable(
    oneOf('verified', 'stale', 'partial', 'untested'),
  ),
  last_drill_at: nullable(string),
  last_drill_ok: nullable(boolean),
  last_drill_backup_id: nullable(string),
  latest_backup_id: nullable(string),
  offsite_status: oneOf('verified', 'pending', 'failed', 'unconfigured'),
  last_offsite_verified_at: nullable(string),
  offsite_location: nullable(string),
  offsite_checksum: nullable(string),
  offsite_error: nullable(string),
  last_isolated_restore_at: nullable(string),
  last_isolated_restore_ok: nullable(boolean),
  backup_activity: optional(
    nullable((value) => matches(value, activitySchema)),
  ),
}

const attemptSchema: Record<keyof CriticalRestoreAttempt, Validator> = {
  status: oneOf('verified', 'failed', 'running'),
  attempted_at: nullable(timestamp),
  completed_at: nullable(timestamp),
  failed_source_id: nullable(string),
  reason: nullable(
    oneOf('mapped-links-unresolved', 'repository-locked', 'restore-failed'),
  ),
  cached: boolean,
}

const restoreSchema: Record<keyof CriticalRestoreHealth, Validator> = {
  status: oneOf(
    'verified',
    'failed',
    'pending',
    'running',
    'stale',
    'untested',
    'unavailable',
  ),
  last_success_at: nullable(timestamp),
  latest_attempt: nullable((value) => matches(value, attemptSchema)),
  required_source_ids: strings,
  verified_source_ids: strings,
  missing_source_ids: strings,
}

const repositorySchema: Record<keyof BackupRepositoryHealthItem, Validator> = {
  backend_id: string,
  backend_name: string,
  critical_restore: (value) => matches(value, restoreSchema),
}

// Validate at the HTTP boundary. Older servers omit repository health entirely;
// that is an unavailable weekly result, not a successful empty result.
export function parseBackupHealth(value: unknown): BackupHealthResponse {
  if (
    !matches(value, {
      sources: (items) =>
        Array.isArray(items) &&
        items.every((item) => matches(item, sourceSchema)),
      pending_upload_count: count,
      repositories: optional(
        (items) =>
          Array.isArray(items) &&
          items.every((item) => matches(item, repositorySchema)),
      ),
    })
  ) {
    throw new Error('Backup health response is incompatible')
  }
  return value as BackupHealthResponse
}
