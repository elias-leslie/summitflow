'use client'

import { clsx } from 'clsx'
import { CheckCircle2, Clock, RefreshCw, Upload, XCircle } from 'lucide-react'
import type { Backup } from '@/lib/api/backups'

const STATUS_CONFIG = {
  pending: {
    icon: Clock,
    className: 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30',
  },
  running: {
    icon: RefreshCw,
    className: 'bg-blue-500/20 text-blue-400 border-blue-500/30',
  },
  completed: {
    icon: CheckCircle2,
    className: 'bg-green-500/20 text-green-400 border-green-500/30',
  },
  completed_pending_upload: {
    icon: Upload,
    className: 'bg-amber-500/20 text-amber-400 border-amber-500/30',
  },
  failed: {
    icon: XCircle,
    className: 'bg-red-500/20 text-red-400 border-red-500/30',
  },
} as const

export function StatusBadge({ status }: { status: Backup['status'] }) {
  const config = STATUS_CONFIG[status]
  const Icon = config.icon

  return (
    <span
      className={clsx(
        'inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium border',
        config.className,
      )}
    >
      <Icon
        className={clsx('w-3 h-3', status === 'running' && 'animate-spin')}
      />
      {status}
    </span>
  )
}
