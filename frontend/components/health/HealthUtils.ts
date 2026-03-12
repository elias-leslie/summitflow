import { formatDate, formatTimeAgo } from '@/lib/format'
import type {
  CheckResult,
  HealthCheckSummary,
  QualityCheckStatus,
} from './HealthTypes'

const CHECK_LABELS: Record<string, string> = {
  biome: 'Biome',
  pyright: 'Types',
  pytest: 'Pytest',
  ruff: 'Ruff',
  sqlfluff: 'SQLFluff',
  tsc: 'TypeScript',
  types: 'Types',
}

export function formatFilePath(path: string | null): string {
  if (!path) return 'Unknown file'

  const parts = path.split('/').filter(Boolean)
  if (parts.length <= 3) {
    return parts.join('/')
  }

  return parts.slice(-3).join('/')
}

export function formatCheckLabel(
  checkType: string,
  checkName?: string | null,
): string {
  if (checkName?.trim()) {
    return checkName.trim()
  }

  return CHECK_LABELS[checkType] ?? checkType.toUpperCase()
}

export function summarizeError(
  error: unknown,
  fallback: string,
): string {
  if (error instanceof Error) {
    return error.message || fallback
  }

  if (typeof error === 'string' && error.trim()) {
    return error
  }

  return fallback
}

export function getHealthCheckState(
  check: HealthCheckSummary,
): {
  dotColor: string
  textColor: string
  badgeLabel: string
} {
  const status = check.status as QualityCheckStatus
  const isPassing = status === 'pass' || status === 'passing'
  const hasWarnings = check.warning_count > 0
  const isSkipped = status === 'skipped'

  if (isSkipped) {
    return {
      dotColor: 'bg-slate-500',
      textColor: 'text-slate-400',
      badgeLabel: 'Skipped',
    }
  }

  if (isPassing && hasWarnings) {
    return {
      dotColor: 'bg-amber-500',
      textColor: 'text-amber-300',
      badgeLabel: `${check.warning_count} warning${check.warning_count === 1 ? '' : 's'}`,
    }
  }

  if (isPassing) {
    return {
      dotColor: 'bg-emerald-500',
      textColor: 'text-emerald-300',
      badgeLabel: 'Passing',
    }
  }

  return {
    dotColor: 'bg-rose-500',
    textColor: 'text-rose-300',
    badgeLabel: `${check.error_count} error${check.error_count === 1 ? '' : 's'}`,
  }
}

export function formatLastRun(timestamp: string | null | undefined): string {
  if (!timestamp) return 'Never'
  return `${formatTimeAgo(timestamp, 'Never')} · ${formatDate(timestamp)}`
}

export function formatIssueStatus(item: CheckResult): string {
  if (item.escalation_task_id) {
    return 'Escalated'
  }

  if (item.fix_attempts > 0) {
    return `${item.fix_attempts} attempt${item.fix_attempts === 1 ? '' : 's'}`
  }

  return 'Pending'
}
