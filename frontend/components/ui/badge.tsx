'use client'

import { clsx } from 'clsx'
import type { ReactNode } from 'react'

type BadgeVariant =
  | 'default'
  | 'phosphor'
  | 'amber'
  | 'rose'
  | 'slate'
  | 'violet'
  | 'outline'
  | 'secondary'

interface BadgeProps {
  variant?: BadgeVariant
  children: ReactNode
  className?: string
  onClick?: () => void
}

const variants: Record<BadgeVariant, string> = {
  default: 'bg-slate-700/50 text-slate-300 border border-slate-600',
  phosphor:
    'bg-phosphor-500/15 text-phosphor-400 border border-phosphor-500/30',
  amber: 'bg-amber-500/15 text-amber-400 border border-amber-500/30',
  rose: 'bg-rose-500/15 text-rose-400 border border-rose-500/30',
  violet: 'bg-violet-500/15 text-violet-400 border border-violet-500/30',
  slate: 'bg-slate-800 text-slate-400 border border-slate-700',
  outline: 'bg-transparent text-slate-400 border border-slate-600',
  secondary:
    'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 border border-slate-200 dark:border-slate-700',
}

export function Badge({
  variant = 'default',
  children,
  className,
  onClick,
}: BadgeProps) {
  return (
    <span
      className={clsx(
        'inline-flex items-center px-2 py-0.5 rounded text-xs font-medium mono',
        variants[variant],
        onClick && 'cursor-pointer',
        className,
      )}
      onClick={onClick}
    >
      {children}
    </span>
  )
}

// Convenience wrappers for common status badges
export function SuccessBadge({
  children,
  className,
}: {
  children: ReactNode
  className?: string
}) {
  return (
    <Badge variant="phosphor" className={className}>
      {children}
    </Badge>
  )
}

export function WarningBadge({
  children,
  className,
}: {
  children: ReactNode
  className?: string
}) {
  return (
    <Badge variant="amber" className={className}>
      {children}
    </Badge>
  )
}

export function ErrorBadge({
  children,
  className,
}: {
  children: ReactNode
  className?: string
}) {
  return (
    <Badge variant="rose" className={className}>
      {children}
    </Badge>
  )
}
