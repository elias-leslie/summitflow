'use client'

import { clsx } from 'clsx'
import type { ReactNode } from 'react'

type BadgeVariant =
  | 'default'
  | 'phosphor'
  | 'amber'
  | 'rose'
  | 'emerald'
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
  emerald: 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/30',
  violet: 'bg-violet-500/15 text-violet-400 border border-violet-500/30',
  slate: 'bg-slate-800 text-slate-400 border border-slate-700',
  outline: 'bg-transparent text-slate-400 border border-slate-600',
  secondary:
    'bg-slate-800 text-slate-400 border border-slate-700',
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
        'inline-flex items-center px-2 py-0.5 rounded-md text-xs font-medium mono',
        variants[variant],
        onClick && 'cursor-pointer hover:brightness-110 active:scale-[0.97] transition-all duration-150',
        className,
      )}
      onClick={onClick}
      onKeyDown={onClick ? (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onClick(); } } : undefined}
      role={onClick ? 'button' : undefined}
      tabIndex={onClick ? 0 : undefined}
    >
      {children}
    </span>
  )
}