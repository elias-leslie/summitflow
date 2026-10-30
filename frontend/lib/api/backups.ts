import { fetchWithErrorHandling, postJson } from './utils'

// Recovery key and the backups other projects run live in their own module.
export * from './backups-infra'

export interface BackupProblem {
  key: string
  title: string
  message: string
}

export interface LocalRun {
  status: string | null
  started_at: string | null
  finished_at: string | null
  error: string | null
}

export interface LocalBackups {
  enabled: boolean
  schedule: string
  keeps: string
  retention: string | null
  last_run: LocalRun | null
  last_good_at: string | null
  next_run_at: string | null
  target: {
    path: string
    free_bytes: number
    used_bytes: number
    total_bytes: number
  } | null
  /** Recovery points per subvolume; null when the drive could not be listed. */
  points: Record<string, number> | null
}

export interface DriveJob {
  status: string | null
  snapshot_id: string | null
  time: string | null
  bytes: number | null
  added_bytes: number | null
  files: number | null
  error: string | null
}

/** A guest the last daily run found powered off: it cannot change, so its last copy stays current. */
export interface OfflineGuest {
  guest: string
  /** When it was first found off after a copy; null when it may have run since without being copied. */
  offline_since: string | null
  last_copy_at: string | null
}

export interface DriveCheck {
  status: string | null
  /** How much stored data one weekly check reads back, such as "500M". */
  sample: string | null
  checked_at: string | null
  last_ok_at: string | null
  failures: number
  error: string | null
}

export interface DriveTestRestore {
  at: string | null
  status: string | null
  error: string | null
}

export interface DriveCleanup {
  ran_at: string | null
  pruned_at: string | null
  snapshots: number | null
  prune_error: string | null
}

export interface DriveRun {
  started_at: string | null
  finished_at: string | null
  status: string | null
  error: string | null
}

export interface DriveBackups {
  schedule: string
  repository: string | null
  last_attempt_at: string | null
  last_success_at: string | null
  status: string | null
  error: string | null
  running: { started_at: string | null } | null
  jobs: Record<string, DriveJob>
  offline: Record<string, OfflineGuest>
  check: DriveCheck | null
  spot_restore: DriveTestRestore | null
  maintenance: DriveCleanup | null
  runs: DriveRun[]
}

export interface OldBackups {
  local_repository: {
    path: string | null
    bytes: number | null
    /** Measured gone by the weekly verify job (its restic config file is missing). */
    missing: boolean
  }
  drive_snapshots: {
    count: number | null
    ages_out_after_days: number
    /** The backup run's window is so long the age-out is effectively paused. */
    paused: boolean
  }
  retired_sources: number
}

export interface BackupOverview {
  generated_at: string
  ok: boolean
  problems: BackupProblem[]
  local: LocalBackups
  offsite: DriveBackups
  legacy: OldBackups
}

export interface BackupRunResponse {
  started: boolean
  unit: string | null
  offsite: boolean
  error?: string | null
}

type Raw = Record<string, unknown>

const obj = (value: unknown): Raw | null =>
  value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Raw)
    : null
const str = (value: unknown): string | null =>
  typeof value === 'string' && value ? value : null
const num = (value: unknown): number | null =>
  typeof value === 'number' && Number.isFinite(value) ? value : null

function record<T>(value: unknown, read: (item: Raw) => T): Record<string, T> {
  const out: Record<string, T> = {}
  for (const [key, item] of Object.entries(obj(value) ?? {})) {
    const row = obj(item)
    if (row) out[key] = read(row)
  }
  return out
}

function counts(value: unknown): Record<string, number> | null {
  const row = obj(value)
  if (!row) return null
  return record(
    Object.fromEntries(
      Object.entries(row).map(([key, count]) => [key, { count }]),
    ),
    (item) => num(item.count) ?? 0,
  )
}

function readRun(value: unknown): LocalRun | null {
  const row = obj(value)
  return row
    ? {
        status: str(row.status),
        started_at: str(row.started_at),
        finished_at: str(row.finished_at),
        error: str(row.error),
      }
    : null
}

function readLocal(row: Raw): LocalBackups {
  const target = obj(row.target)
  return {
    enabled: row.enabled !== false,
    schedule: str(row.schedule) ?? 'every 4 hours',
    keeps: str(row.keeps) ?? '7 days',
    retention: str(row.retention),
    last_run: readRun(row.last_run),
    last_good_at: str(row.last_good_at),
    next_run_at: str(row.next_run_at),
    target:
      target && num(target.total_bytes) !== null
        ? {
            path: str(target.path) ?? '',
            free_bytes: num(target.free_bytes) ?? 0,
            used_bytes: num(target.used_bytes) ?? 0,
            total_bytes: num(target.total_bytes) ?? 0,
          }
        : null,
    points: counts(row.points),
  }
}

function readDrive(row: Raw): DriveBackups {
  const check = obj(row.check)
  const spot = obj(row.spot_restore)
  const upkeep = obj(row.maintenance)
  const running = obj(row.running)
  return {
    schedule: str(row.schedule) ?? 'daily',
    repository: str(row.repository),
    last_attempt_at: str(row.last_attempt_at),
    last_success_at: str(row.last_success_at),
    status: str(row.status),
    error: str(row.error),
    running: running ? { started_at: str(running.started_at) } : null,
    jobs: record(row.jobs, (job) => ({
      status: str(job.status),
      snapshot_id: str(job.snapshot_id),
      time: str(job.time),
      bytes: num(job.bytes),
      added_bytes: num(job.added_bytes),
      files: num(job.files),
      error: str(job.error),
    })),
    offline: record(row.offline, (guest) => ({
      guest: str(guest.guest) ?? '',
      offline_since: str(guest.offline_since),
      last_copy_at: str(guest.last_copy_at),
    })),
    check: check && {
      status: str(check.status),
      sample: str(check.sample),
      checked_at: str(check.checked_at),
      last_ok_at: str(check.last_ok_at),
      failures: num(check.failures) ?? 0,
      error: str(check.error),
    },
    spot_restore: spot && {
      at: str(spot.at),
      status: str(spot.status),
      error: str(spot.error),
    },
    maintenance: upkeep && {
      ran_at: str(upkeep.ran_at),
      pruned_at: str(upkeep.pruned_at),
      snapshots: num(upkeep.snapshots),
      prune_error: str(upkeep.prune_error),
    },
    runs: (Array.isArray(row.runs) ? row.runs : []).flatMap((item) => {
      const run = readRun(item)
      return run ? [run] : []
    }),
  }
}

/** Reads the overview defensively: fields are null before the first Drive run. */
export function parseBackupOverview(value: unknown): BackupOverview {
  const row = obj(value)
  const local = obj(row?.local)
  const drive = obj(row?.offsite)
  if (!row || !local || !drive) throw new Error('Unexpected backup status')
  const legacy = obj(row.legacy) ?? {}
  const repository = obj(legacy.local_repository) ?? {}
  const snapshots = obj(legacy.drive_snapshots) ?? {}
  return {
    generated_at: str(row.generated_at) ?? new Date().toISOString(),
    ok: row.ok === true,
    problems: (Array.isArray(row.problems) ? row.problems : []).flatMap(
      (item) => {
        const problem = obj(item)
        return problem
          ? [
              {
                key: str(problem.key) ?? str(problem.title) ?? 'problem',
                title: str(problem.title) ?? 'Backup problem',
                message: str(problem.message) ?? '',
              },
            ]
          : []
      },
    ),
    local: readLocal(local),
    offsite: readDrive(drive),
    legacy: {
      local_repository: {
        path: str(repository.path),
        bytes: num(repository.bytes),
        missing: repository.missing === true,
      },
      drive_snapshots: {
        count: num(snapshots.count),
        ages_out_after_days: num(snapshots.ages_out_after_days) ?? 30,
        paused: snapshots.paused === true,
      },
      retired_sources: num(legacy.retired_sources) ?? 0,
    },
  }
}

export async function fetchBackupOverview(): Promise<BackupOverview> {
  const value = await fetchWithErrorHandling<unknown>(
    '/api/backups/overview?points=true',
    { errorMessage: 'Could not load backup status', cache: 'no-store' },
  )
  return parseBackupOverview(value)
}

/** Start a local backup now; `offsite` also makes today's Google Drive copy. */
export function runBackupNow(offsite: boolean): Promise<BackupRunResponse> {
  return postJson<BackupRunResponse>(
    `/api/backups/run?offsite=${offsite}`,
    {},
    'Could not start the backup',
  )
}
