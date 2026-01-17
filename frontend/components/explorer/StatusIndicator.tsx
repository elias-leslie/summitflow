/**
 * StatusIndicator - Health status visualization
 *
 * Displays health status as a glowing dot with optional label.
 * Uses phosphor-inspired colors that pulse for attention states.
 */

'use client'

import { cn } from '@/lib/utils'
import type { HealthStatus } from './types'

interface StatusIndicatorProps {
  status: HealthStatus
  size?: 'sm' | 'md' | 'lg'
  showLabel?: boolean
  pulse?: boolean
  className?: string
}

const statusConfig: Record<
  HealthStatus,
  { label: string; dotClass: string; textClass: string }
> = {
  fresh: {
    label: 'Fresh',
    dotClass: 'bg-phosphor-500 shadow-[0_0_8px_rgba(0,200,83,0.6)]',
    textClass: 'text-phosphor-400',
  },
  active: {
    label: 'Active',
    dotClass: 'bg-phosphor-500 shadow-[0_0_8px_rgba(0,200,83,0.6)]',
    textClass: 'text-phosphor-400',
  },
  stale: {
    label: 'Stale',
    dotClass: 'bg-amber-400 shadow-[0_0_8px_rgba(251,191,36,0.6)]',
    textClass: 'text-amber-400',
  },
  orphan: {
    label: 'Orphan',
    dotClass: 'bg-rose-500 shadow-[0_0_8px_rgba(244,63,94,0.6)]',
    textClass: 'text-rose-400',
  },
  unknown: {
    label: 'Unknown',
    dotClass: 'bg-slate-600',
    textClass: 'text-slate-500',
  },
}

const sizeConfig = {
  sm: { dot: 'w-1.5 h-1.5', text: 'text-xs', gap: 'gap-1.5' },
  md: { dot: 'w-2 h-2', text: 'text-xs', gap: 'gap-2' },
  lg: { dot: 'w-2.5 h-2.5', text: 'text-sm', gap: 'gap-2' },
}

export function StatusIndicator({
  status,
  size = 'md',
  showLabel = false,
  pulse = false,
  className,
}: StatusIndicatorProps) {
  const config = statusConfig[status]
  const sizes = sizeConfig[size]

  // Pulse animation for stale/orphan states
  const shouldPulse = pulse || status === 'stale' || status === 'orphan'

  return (
    <span
      className={cn('inline-flex items-center', sizes.gap, className)}
      title={config.label}
    >
      <span
        className={cn(
          'rounded-full flex-shrink-0',
          sizes.dot,
          config.dotClass,
          shouldPulse && status !== 'unknown' && 'animate-pulse',
        )}
      />
      {showLabel && (
        <span className={cn(sizes.text, config.textClass, 'font-medium')}>
          {config.label}
        </span>
      )}
    </span>
  )
}

/**
 * StatusBorder - Left border accent for rows
 */
export function StatusBorder({
  status,
  children,
  className,
}: {
  status: HealthStatus
  children: React.ReactNode
  className?: string
}) {
  const borderColors: Record<HealthStatus, string> = {
    fresh: 'border-l-phosphor-500',
    active: 'border-l-phosphor-500',
    stale: 'border-l-amber-400',
    orphan: 'border-l-rose-500',
    unknown: 'border-l-slate-600',
  }

  return (
    <div className={cn('border-l-2', borderColors[status], className)}>
      {children}
    </div>
  )
}
