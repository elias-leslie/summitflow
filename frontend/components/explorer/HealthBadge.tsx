/**
 * HealthBadge - Unified health status indicator for all explorer entry types
 *
 * Displays health status with semantic colors and contextual tooltips.
 * Designed for consistency across files, tables, tasks, endpoints, pages, and dependencies.
 */

'use client'

import { cn } from '@/lib/utils'

export type HealthStatus = 'healthy' | 'warning' | 'error' | 'unknown'

export type EntryType =
  | 'file'
  | 'table'
  | 'task'
  | 'endpoint'
  | 'page'
  | 'dependency'
  | 'architecture'

interface HealthBadgeProps {
  status: HealthStatus
  count?: number
  type?: EntryType
  size?: 'sm' | 'md' | 'lg'
  showLabel?: boolean
  className?: string
}

const statusConfig: Record<
  HealthStatus,
  {
    label: string
    dotClass: string
    textClass: string
    bgClass: string
    borderClass: string
    glow: string
  }
> = {
  healthy: {
    label: 'Healthy',
    dotClass: 'bg-emerald-500',
    textClass: 'text-emerald-400',
    bgClass: 'bg-emerald-500/10',
    borderClass: 'border-emerald-500/30',
    glow: 'shadow-[0_0_8px_rgba(16,185,129,0.5)]',
  },
  warning: {
    label: 'Warning',
    dotClass: 'bg-amber-500',
    textClass: 'text-amber-400',
    bgClass: 'bg-amber-500/10',
    borderClass: 'border-amber-500/30',
    glow: 'shadow-[0_0_8px_rgba(245,158,11,0.5)]',
  },
  error: {
    label: 'Error',
    dotClass: 'bg-rose-500',
    textClass: 'text-rose-400',
    bgClass: 'bg-rose-500/10',
    borderClass: 'border-rose-500/30',
    glow: 'shadow-[0_0_8px_rgba(244,63,94,0.5)]',
  },
  unknown: {
    label: 'Unknown',
    dotClass: 'bg-slate-500',
    textClass: 'text-slate-400',
    bgClass: 'bg-slate-500/10',
    borderClass: 'border-slate-500/30',
    glow: '',
  },
}

const sizeConfig = {
  sm: {
    dot: 'w-1.5 h-1.5',
    text: 'text-[10px]',
    gap: 'gap-1',
    padding: 'px-1.5 py-0.5',
  },
  md: {
    dot: 'w-2 h-2',
    text: 'text-xs',
    gap: 'gap-1.5',
    padding: 'px-2 py-0.5',
  },
  lg: {
    dot: 'w-2.5 h-2.5',
    text: 'text-sm',
    gap: 'gap-2',
    padding: 'px-2.5 py-1',
  },
}

const typeThresholds: Record<EntryType, string> = {
  file: 'Bloat level, staleness, complexity flags',
  table: 'Row count, completeness, freshness, schema violations',
  task: 'Success rate (<50% error, <90% warning)',
  endpoint: 'HTTP status, orphaned status',
  page: 'HTTP status, console errors',
  dependency: 'Vulnerabilities, outdated status',
  architecture: 'Parallel implementations, missing infrastructure, duplicates',
}

function buildTooltipLines(
  label: string,
  type: EntryType | undefined,
  count: number | undefined,
) {
  const tooltipLines = [label]
  if (type && typeThresholds[type]) {
    tooltipLines.push(`Checks: ${typeThresholds[type]}`)
  }
  if (count !== undefined && count > 0) {
    tooltipLines.push(`Issues: ${count}`)
  }
  return tooltipLines
}

export function HealthBadge({
  status,
  count,
  type,
  size = 'md',
  showLabel = false,
  className,
}: HealthBadgeProps) {
  const config = statusConfig[status]
  const sizes = sizeConfig[size]
  const tooltipLines = buildTooltipLines(config.label, type, count)

  const shouldPulse = status === 'error'
  const shouldGlow = status !== 'unknown'

  return (
    <span
      className={cn('inline-flex items-center', sizes.gap, className)}
      title={tooltipLines.join('\n')}
    >
      <span
        className={cn(
          'rounded-full shrink-0 transition-all duration-200',
          sizes.dot,
          config.dotClass,
          shouldGlow && config.glow,
          shouldPulse && 'animate-pulse',
        )}
      />
      {showLabel && (
        <span
          className={cn(
            sizes.text,
            config.textClass,
            'font-medium tracking-wide',
          )}
        >
          {config.label}
          {count !== undefined && count > 0 && (
            <span className="ml-1 opacity-70">({count})</span>
          )}
        </span>
      )}
    </span>
  )
}

export function HealthPill({
  status,
  count,
  type,
  className,
}: Omit<HealthBadgeProps, 'size' | 'showLabel'>) {
  const config = statusConfig[status]
  const tooltipLines = buildTooltipLines(config.label, type, count)

  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10px] font-medium tracking-wide border',
        config.bgClass,
        config.borderClass,
        config.textClass,
        className,
      )}
      title={tooltipLines.join('\n')}
    >
      <span className={cn('w-1.5 h-1.5 rounded-full', config.dotClass)} />
      {config.label}
      {count !== undefined && count > 0 && (
        <span className="opacity-70">({count})</span>
      )}
    </span>
  )
}
