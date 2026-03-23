'use client'

import { clsx } from 'clsx'

interface SkeletonProps {
  className?: string
}

export function Skeleton({ className }: SkeletonProps) {
  return (
    <div
      className={clsx(
        'rounded-md bg-slate-800/50 relative overflow-hidden',
        className,
      )}
    >
      <div className="absolute inset-0 bg-gradient-to-r from-transparent via-white/[0.04] to-transparent animate-shimmer" />
    </div>
  )
}
